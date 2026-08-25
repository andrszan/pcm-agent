from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import HookMatcher

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import parse_agent_decision, render_decision_system_prompt, request_decision
from common.files import resolve_workspace_output
from common.state import requirement_step_result_path, write_requirement_step_result, write_state
from config import LLMConfig
from steps.step_02_project_intake.step import OUTPUTS as PRODUCT_OUTPUT_PATHS
from steps.step_05_project_readiness.step import (
    CHECKLIST,
    checklist_contents,
    load_product_outputs,
    product_output_contents,
    verify_existing_readiness_success,
)
from steps.step_07_solution_design.step import DESIGN_PATH, verify_existing_solution_success
from steps.step_13_select_requirement.step import has_complete_success as has_selection_success

STEP = 14
NAME = "形成活动 TRD"
CURRENT_NODE = "requirement:14_trd_design"
NEXT_NODE = "requirement:15_development"
PHASE = "phase_1_requirement_development"
SKILL_NAME = "trd-design"
ARCHITECTURE_PATH = Path("docs/design/工程架构设计.md")
UI_UX_FRAMEWORK_PATH = Path("docs/ui-ux/framework.md")
BACKLOG_PATH = Path("docs/backlog/backlog.md")
MAX_DECISION_ROUNDS = 8
TRD_DESIGN_MAX_TURNS = 48
TRD_DESIGN_MAX_BUDGET_USD = 16.0
TRD_AGENT_TOOLS = ["Read", "Glob", "Grep", "Write", "Edit", "Skill"]

_HEX_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_FORBIDDEN_TITLE_CHARACTERS = set('<>:"/\\|?*')

TRD_DESIGN_DECISION_RULES = """- completed：当前正式需求的活动 TRD 已写入唯一指定路径，已基于权威产品资料、正式 Backlog、总体技术方案、工程架构、适用的产品级体验框架和实际代码事实收敛范围、行为、技术方案、验证场景及需求级体验设计；阻碍实现的高影响决定已经明确采用当前基线，Agent 回复和 TRD 均不得仍把这些事项写成“实现前必须确认”“确认前不得实现”或等价实现门槛；只允许保留不妨碍当前实现的后续验证、可调整细节和外部未核验范围；没有越界实现功能或修改其它文件，也没有执行 Git 写操作。
- continue：活动 TRD、当前工程事实核验或会影响实现的产品与技术决定仍可在当前项目中补全；若 Agent 报告仍有实现前必须确认的登录标识、多角色、通知语义、会话、密码与限制、恢复渠道、导航或无障碍等事项，必须给出具体下一步指令，基于项目事实和最小安全方案收敛当前实现基线，不能仅因这些事项已被列出就判定完成。
- blocked：只能用于缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务或线下动作。"""

BASE_DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key="trd_design",
    state_key="trd_design",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=TRD_DESIGN_MAX_TURNS,
    max_budget_usd=TRD_DESIGN_MAX_BUDGET_USD,
    decision_system_prompt=render_decision_system_prompt(TRD_DESIGN_DECISION_RULES, {}),
)


class TRDDesignBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        *,
        requirement_id: str,
        branch: str,
        trd_path: str,
        trd_session_id: str | None,
        outputs: list[str] | None = None,
    ) -> None:
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.requirement_id = requirement_id
        self.branch = branch
        self.trd_path = trd_path
        self.trd_session_id = trd_session_id
        self.outputs = outputs or []


def result(
    status: str,
    summary: str,
    *,
    requirement_id: str | None = None,
    branch: str | None = None,
    trd_path: str | None = None,
    trd_session_id: str | None = None,
    outputs: list[str] | None = None,
    blocked: dict[str, Any] | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": outputs or [],
        "blocked": blocked,
        "error": error,
        "requirement_id": requirement_id,
        "branch": branch,
        "trd_path": trd_path,
        "trd_session_id": trd_session_id,
    }


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


def _read_json(path: Path, message: str) -> dict[str, Any]:
    if path.is_symlink():
        raise RuntimeError(message)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(message) from error
    if not isinstance(value, dict):
        raise RuntimeError(message)
    return value


def _workspace_from_state(state: dict[str, Any]) -> Path:
    try:
        root_value = state["workspace"]["root"]
        workspace_value = state["workspace"]["final_path"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    if not isinstance(root_value, str) or not isinstance(workspace_value, str):
        raise RuntimeError("工作区状态记录不完整")
    root = Path(root_value)
    workspace = Path(workspace_value)
    if not root.is_absolute() or not workspace.is_absolute() or workspace.is_symlink():
        raise RuntimeError("工作区状态路径不符合约定")
    root = root.resolve()
    workspace = workspace.resolve()
    if workspace.parent != root or not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    return workspace


def _context(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("phase") != PHASE or _position(state) not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于活动 TRD 锚点")
    if not has_selection_success(run_dir, state):
        raise RuntimeError("第 13 步没有当前活动需求的完整成功结果")

    workspace = _workspace_from_state(state)
    requirement_id = state.get("active_requirement")
    registry = state.get("requirement_registry")
    cycle = state.get("requirement_cycle")
    if (
        not isinstance(requirement_id, str)
        or not isinstance(registry, dict)
        or not isinstance(registry.get("requirements"), list)
        or not isinstance(cycle, dict)
        or cycle.get("requirement_id") != requirement_id
    ):
        raise RuntimeError("活动需求上下文不符合约定")
    active = [
        item
        for item in registry["requirements"]
        if isinstance(item, dict) and item.get("status") == "active"
    ]
    if len(active) != 1 or active[0].get("id") != requirement_id:
        raise RuntimeError("活动需求与需求注册表不一致")
    requirement = active[0]
    title = requirement.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError("活动需求标题不符合约定")

    branch = cycle.get("branch")
    recorded = cycle.get("repositories")
    names = state.get("applicable_repositories")
    descriptors = state.get("repositories")
    if (
        branch != f"req/{requirement_id.lower()}"
        or not isinstance(recorded, dict)
        or not isinstance(names, list)
        or not names
        or names[0] != "root"
        or not isinstance(descriptors, list)
        or len(descriptors) != len(names)
    ):
        raise RuntimeError("活动需求分支或仓库状态不符合约定")

    repositories: list[dict[str, Any]] = []
    bases: dict[str, str] = {}
    for name, descriptor in zip(names, descriptors, strict=True):
        expected_path = workspace if name == "root" else workspace / name
        base = recorded.get(name)
        if (
            not isinstance(name, str)
            or not isinstance(descriptor, dict)
            or descriptor.get("name") != name
            or descriptor.get("path") != str(expected_path)
            or not isinstance(base, dict)
            or set(base) != {"base_sha"}
            or not isinstance(base.get("base_sha"), str)
            or not _HEX_SHA.fullmatch(base["base_sha"])
        ):
            raise RuntimeError("活动需求仓库基线不符合约定")
        repositories.append({"name": name, "path": expected_path})
        bases[name] = base["base_sha"]

    requirement_step_result_path(run_dir, requirement_id, STEP)
    return {
        "workspace": workspace,
        "requirement": requirement,
        "requirement_id": requirement_id,
        "title": title,
        "branch": branch,
        "repositories": repositories,
        "bases": bases,
        "cycle": cycle,
        "key": f"trd_design_{requirement_id}",
    }


def _git_run(
    path: Path,
    *args: str,
    allowed_returncodes: tuple[int, ...] = (0,),
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=path,
            text=text,
            capture_output=True,
            timeout=120,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if completed.returncode not in allowed_returncodes:
        raise RuntimeError("无法读取 Git 仓库状态")
    return completed


def _git_read(path: Path, *args: str) -> str:
    completed = _git_run(path, *args)
    return completed.stdout.rstrip("\n")


def _ref(path: Path, reference: str) -> str | None:
    completed = _git_run(
        path,
        "show-ref",
        "--verify",
        "--quiet",
        reference,
        allowed_returncodes=(0, 1),
    )
    if completed.returncode == 1:
        return None
    return _git_read(path, "show-ref", "--verify", "--hash", reference)


def _has_in_progress_operation(path: Path) -> bool:
    for reference in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        completed = _git_run(
            path,
            "rev-parse",
            "-q",
            "--verify",
            reference,
            allowed_returncodes=(0, 1),
        )
        if completed.returncode == 0:
            return True
    for path_name in ("rebase-merge", "rebase-apply", "BISECT_START"):
        value = _git_read(path, "rev-parse", "--git-path", path_name)
        progress = Path(value)
        if not progress.is_absolute():
            progress = path / progress
        if progress.exists():
            return True
    return False


def _status_entries(path: Path) -> list[tuple[str, str]]:
    completed = _git_run(
        path,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        text=False,
    )
    try:
        raw = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError("Git 工作树状态不是 UTF-8") from error
    entries: list[tuple[str, str]] = []
    for record in raw.split("\0"):
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            raise RuntimeError("Git 工作树状态不符合约定")
        status = record[:2]
        if "R" in status or "C" in status:
            raise RuntimeError("活动 TRD 期间不允许重命名或复制文件")
        entries.append((status, record[3:]))
    return entries


def _repository_facts(repository: dict[str, Any], branch: str) -> dict[str, Any]:
    raw_path = repository["path"]
    if raw_path.is_symlink() or not raw_path.is_dir():
        raise RuntimeError("权威 Git 仓库路径不存在或是符号链接")
    path = raw_path.resolve()
    top_level = _git_read(path, "rev-parse", "--show-toplevel")
    if Path(top_level).resolve() != path:
        raise RuntimeError("Git 仓库顶层目录与权威仓库路径不一致")
    if _has_in_progress_operation(path):
        raise RuntimeError("Git 仓库存在未完成的合并、变基、拣选或还原操作")
    head = _git_read(path, "rev-parse", "HEAD")
    main = _ref(path, "refs/heads/main")
    target = _ref(path, f"refs/heads/{branch}")
    current = _git_read(path, "branch", "--show-current")
    entries = _status_entries(path)
    cached = _git_run(path, "diff", "--cached", "--quiet", allowed_returncodes=(0, 1))
    if any(not isinstance(value, str) or not _HEX_SHA.fullmatch(value) for value in (head, main, target)):
        raise RuntimeError("Git 仓库引用不符合约定")
    return {
        "path": path,
        "head": head,
        "main": main,
        "target": target,
        "current": current,
        "entries": entries,
        "index_clean": cached.returncode == 0,
    }


def _verify_refs(context: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for repository in context["repositories"]:
        current = _repository_facts(repository, context["branch"])
        base = context["bases"][repository["name"]]
        if (
            current["current"] != context["branch"]
            or current["head"] != base
            or current["main"] != base
            or current["target"] != base
            or not current["index_clean"]
        ):
            raise RuntimeError("Git 仓库不在活动需求记录的未提交基线")
        current["name"] = repository["name"]
        facts.append(current)
    return facts


def _safe_trd_path(workspace: Path, relative_value: str) -> Path:
    relative = Path(relative_value)
    if relative.is_absolute() or relative.parts[:2] != ("docs", "trd") or len(relative.parts) != 3:
        raise RuntimeError("活动 TRD 路径不符合约定")
    current = workspace
    for index, part in enumerate(relative.parts):
        current /= part
        if current.is_symlink():
            raise RuntimeError("活动 TRD 路径不能包含符号链接")
        if index < len(relative.parts) - 1 and current.exists() and not current.is_dir():
            raise RuntimeError("活动 TRD 父路径与预期目录冲突")
    try:
        return resolve_workspace_output(workspace, relative.as_posix())
    except ValueError as error:
        raise RuntimeError("活动 TRD 路径不符合约定") from error


def _trd_agent_hooks(context: dict[str, Any], trd_path: str) -> dict[str, list[HookMatcher]]:
    workspace = context["workspace"].resolve()
    target = _safe_trd_path(context["workspace"], trd_path).resolve()

    async def restrict_write(
        hook_input: Any,
        _tool_use_id: str | None,
        _hook_context: Any,
    ) -> dict[str, Any]:
        tool_name = hook_input.get("tool_name") if isinstance(hook_input, dict) else None
        tool_input = hook_input.get("tool_input") if isinstance(hook_input, dict) else None
        path_value = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        allowed = False
        if tool_name in {"Write", "Edit"} and isinstance(path_value, str):
            candidate = Path(path_value)
            if not candidate.is_absolute():
                candidate = workspace / candidate
            allowed = candidate.resolve() == target
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if allowed else "deny",
                "permissionDecisionReason": (
                    "只允许写入当前活动 TRD。"
                    if not allowed
                    else "当前写入路径是唯一活动 TRD。"
                ),
            }
        }

    return {
        "PreToolUse": [
            HookMatcher(matcher="Write|Edit", hooks=[restrict_write])
        ]
    }


def _validate_title(title: str) -> None:
    if (
        title != title.strip()
        or title in {"", ".", ".."}
        or any(character in _FORBIDDEN_TITLE_CHARACTERS or ord(character) < 32 or ord(character) == 127 for character in title)
    ):
        raise RuntimeError("活动需求标题不能安全用于 TRD 文件名")


def _new_trd_path(context: dict[str, Any], today_provider: Callable[[], date]) -> str:
    title = context["title"]
    _validate_title(title)
    filename = f"{today_provider().isoformat()}-{context['requirement_id']}-{title}.md"
    if len(filename.encode("utf-8")) > 240:
        raise RuntimeError("活动 TRD 文件名过长")
    relative = Path("docs/trd") / filename
    target = _safe_trd_path(context["workspace"], relative.as_posix())
    if target.exists() or target.is_symlink():
        raise RuntimeError("新鲜活动 TRD 目标路径已经存在")
    return relative.as_posix()


def _validate_saved_trd_path(context: dict[str, Any], value: Any) -> str:
    if not isinstance(value, str):
        raise RuntimeError("活动 TRD 路径状态不符合约定")
    _validate_title(context["title"])
    relative = Path(value)
    expected_suffix = f"-{context['requirement_id']}-{context['title']}.md"
    if (
        relative.is_absolute()
        or relative.parts[:2] != ("docs", "trd")
        or len(relative.parts) != 3
        or not relative.name.endswith(expected_suffix)
    ):
        raise RuntimeError("活动 TRD 路径状态不符合约定")
    date_value = relative.name[: -len(expected_suffix)]
    try:
        date.fromisoformat(date_value)
    except ValueError as error:
        raise RuntimeError("活动 TRD 首次创建日期不符合约定") from error
    _safe_trd_path(context["workspace"], value)
    return value


def _verify_boundary(
    context: dict[str, Any],
    trd_path: str,
    *,
    fresh: bool = False,
) -> list[dict[str, Any]]:
    facts = _verify_refs(context)
    for repository in facts:
        if repository["name"] != "root" and repository["entries"]:
            raise RuntimeError("活动 TRD 期间非 root 仓库必须保持 clean")
    root = facts[0]
    target = _safe_trd_path(context["workspace"], trd_path)
    if fresh:
        if root["entries"] or target.exists() or target.is_symlink():
            raise RuntimeError("新鲜活动 TRD 入口要求全部仓库 clean 且目标不存在")
        return facts
    if any(entry != ("??", trd_path) for entry in root["entries"]):
        raise RuntimeError("产品 root 存在活动 TRD 路径外或已暂存的修改")
    if len(root["entries"]) > 1:
        raise RuntimeError("产品 root 存在多个活动 TRD 修改")
    return facts


def _document_state(context: dict[str, Any], trd_path: str) -> str:
    target = _safe_trd_path(context["workspace"], trd_path)
    if not target.exists():
        return "missing"
    if target.is_symlink() or not target.is_file():
        raise RuntimeError("活动 TRD 必须是非符号链接普通文件")
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError("活动 TRD 不可读取") from error
    return "ready" if content.strip() else "empty"


def _repair_prompt(trd_path: str) -> str:
    return (
        f"指定活动 TRD 缺失或为空。请仅创建或补全 `{trd_path}`；"
        "不得修改任何其他文件，不得执行 Git 写操作，然后报告结果。"
    )


def _conversation_reference(state: dict[str, Any], key: str) -> Path | None:
    references = state.get("decision_conversations")
    if references is None:
        return None
    if not isinstance(references, dict):
        raise RuntimeError("活动 TRD 决策历史引用不符合约定")
    reference = references.get(key)
    if reference is None:
        return None
    expected = Path("conversations") / f"{key}.json"
    if not isinstance(reference, dict) or reference.get("path") != expected.as_posix():
        raise RuntimeError("活动 TRD 决策历史引用不符合约定")
    return expected


def _session(state: dict[str, Any], key: str) -> str | None:
    sessions = state.get("claude_sessions")
    if sessions is None:
        return None
    if not isinstance(sessions, dict):
        raise RuntimeError("活动 TRD Claude session 状态不符合约定")
    value = sessions.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeError("活动 TRD Claude session ID 不符合约定")
    return value


def _safe_conversation_path(run_dir: Path, key: str) -> Path:
    resolved_run_dir = run_dir.resolve()
    conversations = run_dir / "conversations"
    if conversations.exists() or conversations.is_symlink():
        if conversations.is_symlink() or not conversations.is_dir():
            raise RuntimeError("活动 TRD conversations 路径必须是非符号链接目录")
        if conversations.resolve().parent != resolved_run_dir:
            raise RuntimeError("活动 TRD conversations 路径越出运行目录")
    path = conversations / f"{key}.json"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("活动 TRD 决策历史必须是非符号链接普通文件")
        if path.resolve().parent != (resolved_run_dir / "conversations"):
            raise RuntimeError("活动 TRD 决策历史路径越出运行目录")
    return path


def _conversation_messages(path: Path) -> list[dict[str, str]]:
    conversation = _read_json(path, "活动 TRD 决策历史不可读取")
    if set(conversation) != {"messages"} or not isinstance(conversation.get("messages"), list):
        raise RuntimeError("活动 TRD 决策历史内容不符合约定")
    messages: list[dict[str, str]] = []
    for message in conversation["messages"]:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message.get("role") not in {"system", "assistant", "user"}
            or not isinstance(message.get("content"), str)
        ):
            raise RuntimeError("活动 TRD 决策历史消息不符合约定")
        messages.append({"role": message["role"], "content": message["content"]})
    if not messages or messages[0]["role"] != "system":
        raise RuntimeError("活动 TRD 决策历史首条消息必须是 system")
    return messages


def _has_structured_decision(messages: list[dict[str, str]]) -> bool:
    for message in messages:
        if message["role"] != "assistant":
            continue
        try:
            parse_agent_decision(message["content"])
        except ValueError:
            continue
        return True
    return False


def _execution_artifacts_present(run_dir: Path, state: dict[str, Any], key: str) -> bool:
    sessions = state.get("claude_sessions")
    references = state.get("decision_conversations")
    path = _safe_conversation_path(run_dir, key)
    return (
        isinstance(sessions, dict)
        and key in sessions
        or isinstance(references, dict)
        and key in references
        or path.exists()
        or path.is_symlink()
        or key in state
    )


def _validate_execution_anchor(
    run_dir: Path,
    state: dict[str, Any],
    context: dict[str, Any],
    initial_agent_prompt: str,
    *,
    fresh: bool,
) -> bool:
    key = context["key"]
    if fresh and _execution_artifacts_present(run_dir, state, key):
        raise RuntimeError("新鲜活动 TRD 入口不得包含既有执行产物")
    session = _session(state, key)
    reference = _conversation_reference(state, key)
    path = _safe_conversation_path(run_dir, key)
    present = path.exists() or path.is_symlink()
    if present and reference is None:
        raise RuntimeError("活动 TRD 恢复存在未引用的决策历史")
    if reference is not None and not present:
        raise RuntimeError("活动 TRD 恢复缺少原决策历史")
    messages = _conversation_messages(path) if present else []
    section = state.get(key)
    if section is not None and not isinstance(section, dict):
        raise RuntimeError("活动 TRD 执行状态不符合约定")
    execution_facts = (
        session is not None
        or isinstance(section, dict)
        and bool(section)
        or any(message["role"] == "user" for message in messages)
        or _has_structured_decision(messages)
    )
    if execution_facts and session is None:
        raise RuntimeError("活动 TRD 恢复缺少原 Claude session")
    if session is not None and reference is None:
        raise RuntimeError("活动 TRD 恢复缺少原决策历史引用")
    if session is None and messages:
        allowed = [
            messages[:1],
            [messages[0], {"role": "assistant", "content": initial_agent_prompt}],
        ]
        if messages not in allowed:
            raise RuntimeError("活动 TRD 无 session 历史包含 Agent 执行事实")
    if state.get("status") == "blocked":
        try:
            decision = parse_agent_decision(messages[-1]["content"])
        except (IndexError, KeyError, ValueError):
            raise RuntimeError("活动 TRD 恢复缺少有效 blocked 决策历史") from None
        if messages[-1]["role"] != "assistant" or decision.verdict != "blocked":
            raise RuntimeError("活动 TRD 恢复历史尾部不是 blocked 决策")
    return execution_facts


def _strict_output_result(run_dir: Path, step: int, name: str, output: Path) -> Path:
    saved = _read_json(run_dir / "steps" / f"{step:02d}.json", f"第 {step} 步成功结果不可读取")
    expected = {"step", "name", "status", "summary", "applicable", "outputs", "blocked", "error"}
    if (
        set(saved) != expected
        or saved.get("step") != step
        or saved.get("name") != name
        or saved.get("status") != "success"
        or not isinstance(saved.get("summary"), str)
        or not saved["summary"].strip()
        or saved.get("applicable") is not True
        or saved.get("outputs") != [output.as_posix()]
        or saved.get("blocked") is not None
        or saved.get("error") is not None
    ):
        raise RuntimeError(f"第 {step} 步成功结果不符合约定")
    return output


def _document_contents(workspace: Path, relative: Path, label: str) -> str:
    target = _safe_workspace_document(workspace, relative, label)
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"{label}不可读取") from error
    if not content.strip():
        raise RuntimeError(f"{label}不能为空")
    tracked = _git_run(
        workspace,
        "ls-files",
        "--error-unmatch",
        "--",
        relative.as_posix(),
        allowed_returncodes=(0, 1),
    )
    if tracked.returncode != 0:
        raise RuntimeError(f"{label}必须已被产品 root 跟踪")
    return content


def _safe_workspace_document(workspace: Path, relative: Path, label: str) -> Path:
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError(f"{label}路径不能包含符号链接")
    try:
        target = resolve_workspace_output(workspace, relative.as_posix())
    except ValueError as error:
        raise RuntimeError(f"{label}路径不符合约定") from error
    if not target.is_file():
        raise RuntimeError(f"{label}不是普通文件")
    return target


def _ui_ux_input(run_dir: Path, workspace: Path) -> tuple[str | None, str | None]:
    saved = _read_json(run_dir / "steps" / "10.json", "第 10 步成功结果不可读取")
    expected = {"step", "name", "status", "summary", "applicable", "outputs", "blocked", "error"}
    if (
        set(saved) != expected
        or saved.get("step") != 10
        or saved.get("name") != "产品级 UI/UX 框架"
        or saved.get("status") != "success"
        or not isinstance(saved.get("summary"), str)
        or not saved["summary"].strip()
        or saved.get("blocked") is not None
        or saved.get("error") is not None
    ):
        raise RuntimeError("第 10 步成功结果不符合约定")
    if saved.get("applicable") is False and saved.get("outputs") == []:
        return None, None
    if saved.get("applicable") is not True or saved.get("outputs") != [UI_UX_FRAMEWORK_PATH.as_posix()]:
        raise RuntimeError("第 10 步适用性结果不符合约定")
    return UI_UX_FRAMEWORK_PATH.as_posix(), _document_contents(
        workspace, UI_UX_FRAMEWORK_PATH, "产品级 UI/UX 框架"
    )


def _inputs(run_dir: Path, context: dict[str, Any]) -> dict[str, Any]:
    workspace = context["workspace"]
    product_outputs = load_product_outputs(run_dir, workspace)
    if product_outputs != [path.as_posix() for path in PRODUCT_OUTPUT_PATHS]:
        raise RuntimeError("第 2 步产品定义输出不符合约定")
    for output in product_outputs:
        _document_contents(workspace, Path(output), "产品定义")
    verify_existing_readiness_success(run_dir)
    checklist = checklist_contents(workspace)
    if checklist is None:
        raise RuntimeError("第 5 步项目准备清单不存在或不可读取")
    _document_contents(workspace, CHECKLIST, "项目准备清单")
    verify_existing_solution_success(run_dir)
    design = _document_contents(workspace, DESIGN_PATH, "总体技术方案")
    _strict_output_result(run_dir, 9, "工程架构设计", ARCHITECTURE_PATH)
    architecture = _document_contents(workspace, ARCHITECTURE_PATH, "工程架构设计")
    ui_path, ui_contents = _ui_ux_input(run_dir, workspace)
    _strict_output_result(run_dir, 11, "拆分 Backlog", BACKLOG_PATH)
    backlog = _document_contents(workspace, BACKLOG_PATH, "正式 Backlog")
    source = context["requirement"].get("id")
    if f"#### {source} {context['title']}" not in backlog:
        raise RuntimeError("正式 Backlog 缺少当前活动需求详情卡")
    return {
        "product_outputs": product_outputs,
        "checklist": checklist,
        "design": design,
        "architecture": architecture,
        "ui_path": ui_path,
        "ui_contents": ui_contents,
        "backlog": backlog,
    }


def initial_prompt(context: dict[str, Any], inputs: dict[str, Any], trd_path: str) -> str:
    product_references = "\n".join(f"- @./{path}" for path in inputs["product_outputs"])
    engineering_references = "\n".join(
        "- 产品根工程：@./"
        if repository["name"] == "root"
        else f"- {repository['name']} 工程：@./{repository['name']}"
        for repository in context["repositories"]
    )
    experience_reference = (
        f"- @./{inputs['ui_path']}"
        if inputs["ui_path"] is not None
        else "- 当前产品没有适用的产品级 UI/UX 框架文档。"
    )
    return f"""/trd-design
请为正式需求 `{context['requirement_id']} {context['title']}` 形成可直接指导实现和验证的活动 TRD，并只写入：

`{trd_path}`

权威需求：
- 当前需求：`{context['requirement_id']} {context['title']}`
- 完整需求详情：@./{BACKLOG_PATH.as_posix()} 中标题为 `#### {context['requirement_id']} {context['title']}` 的详情卡

权威产品与工程资料：
{product_references}
- @./{CHECKLIST.as_posix()}
- @./{DESIGN_PATH.as_posix()}
- @./{ARCHITECTURE_PATH.as_posix()}
{experience_reference}
- @./{BACKLOG_PATH.as_posix()}

当前实际工程：
{engineering_references}
- 全部适用仓库当前统一位于 `{context['branch']}`。

请核验与该需求直接相关的实际代码、测试、接口、数据、权限、配置和当前运行约定。明确使用方、范围、非目标、关键行为、状态与恢复、技术职责、数据与接口语义、安全边界、实现约束和可执行验证场景；区分已确认事实、现有惯例、合理默认、设计假设和仍需决定的事项。

需求与产品资料、技术方案、工程架构、产品级体验框架或当前代码存在冲突时，明确冲突、影响和建议边界。会改变产品结果、权限、安全、兼容性、数据语义或实现成本的决定不得静默假定。

只允许创建或更新 `{trd_path}`。不得实现业务功能，不得修改代码、测试、配置、依赖、项目规则、Backlog 或其它文档，不得执行 Git 写操作，不得暂存、提交、合并、推送、切换或创建分支，不得处理或展示秘密。

最终完整回复须说明 TRD 路径、主要产品与技术决定、与当前代码或既有资料的差异、仍待确认事项和未核验范围。"""


def _saved_result(run_dir: Path, requirement_id: str) -> dict[str, Any] | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    if not path.exists() and not path.is_symlink():
        return None
    return _read_json(path, "活动 TRD 结果不可读取")


def _validate_success(saved: Any, context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    trd_path = _validate_saved_trd_path(context, context["cycle"].get("trd_path"))
    session_id = _session(state, context["key"])
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
        "requirement_id",
        "branch",
        "trd_path",
        "trd_session_id",
    }
    if (
        not isinstance(saved, dict)
        or set(saved) != expected_keys
        or saved.get("step") != STEP
        or saved.get("name") != NAME
        or saved.get("status") != "success"
        or not isinstance(saved.get("summary"), str)
        or not saved["summary"].strip()
        or saved.get("applicable") is not True
        or saved.get("outputs") != [trd_path]
        or saved.get("blocked") is not None
        or saved.get("error") is not None
        or saved.get("requirement_id") != context["requirement_id"]
        or saved.get("branch") != context["branch"]
        or saved.get("trd_path") != trd_path
        or not isinstance(session_id, str)
        or saved.get("trd_session_id") != session_id
    ):
        raise RuntimeError("活动 TRD 完整成功结果不符合约定")
    return saved


def _completion_ready(
    run_dir: Path,
    state: dict[str, Any],
    context: dict[str, Any],
    trd_path: str,
) -> bool:
    _validate_execution_anchor(
        run_dir,
        state,
        context,
        initial_prompt(context, _inputs(run_dir, context), trd_path),
        fresh=False,
    )
    _verify_boundary(context, trd_path)
    return (
        _session(state, context["key"]) is not None
        and _document_state(context, trd_path) == "ready"
        and _status_entries(context["workspace"]) == [("??", trd_path)]
    )


def _advance(run_dir: Path, state: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    state.update(
        {
            "status": "success",
            "phase": PHASE,
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return saved


def has_complete_success(run_dir: Path, state: dict[str, Any]) -> bool:
    try:
        context = _context(run_dir, state)
        saved = _saved_result(run_dir, context["requirement_id"])
        _validate_success(saved, context, state)
    except (RuntimeError, ValueError, TypeError):
        return False
    return True


def failure_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, str | None] | None:
    try:
        context = _context(run_dir, state)
        trd_path_value = context["cycle"].get("trd_path")
        if trd_path_value is None:
            return None
        trd_path = _validate_saved_trd_path(context, trd_path_value)
        session_id = _session(state, context["key"])
    except (RuntimeError, ValueError, TypeError):
        return None
    return {
        "requirement_id": context["requirement_id"],
        "branch": context["branch"],
        "trd_path": trd_path,
        "trd_session_id": session_id,
    }


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=None,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
    today_provider: Callable[[], date] = date.today,
) -> dict[str, Any]:
    context = _context(run_dir, state)
    position = _position(state)
    saved = _saved_result(run_dir, context["requirement_id"])

    if position == (STEP + 1, STEP + 1, NEXT_NODE):
        if state.get("status") != "success" or state.get("blocked") is not None or state.get("error") is not None:
            raise RuntimeError("活动 TRD 成功状态不符合约定")
        return _validate_success(saved, context, state)

    trd_path_value = context["cycle"].get("trd_path")
    path_is_new = trd_path_value is None
    if path_is_new:
        inputs = _inputs(run_dir, context)
        candidate = _new_trd_path(context, today_provider)
        _verify_boundary(context, candidate, fresh=True)
        if _execution_artifacts_present(run_dir, state, context["key"]):
            raise RuntimeError("新鲜活动 TRD 入口不得包含既有执行产物")
        context["cycle"]["trd_path"] = candidate
        state.update(
            {
                "status": "running",
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": None,
                "error": None,
            }
        )
        write_state(run_dir, state)
        trd_path = candidate
    else:
        trd_path = _validate_saved_trd_path(context, trd_path_value)
        inputs = _inputs(run_dir, context)

    agent_prompt = initial_prompt(context, inputs, trd_path)
    started = _validate_execution_anchor(
        run_dir,
        state,
        context,
        agent_prompt,
        fresh=path_is_new,
    )

    if saved is not None:
        try:
            complete = _validate_success(saved, context, state)
        except RuntimeError:
            pass
        else:
            if not _completion_ready(run_dir, state, context, trd_path):
                raise RuntimeError("活动 TRD 既有成功缺少有效完成现场")
            return _advance(run_dir, state, complete)

    if not started:
        _verify_boundary(context, trd_path, fresh=path_is_new)
    else:
        _verify_boundary(context, trd_path)
    target = _safe_trd_path(context["workspace"], trd_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _safe_trd_path(context["workspace"], trd_path)

    if state.get("status") != "blocked":
        state.update(
            {
                "status": "running",
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": None,
                "error": None,
            }
        )
        write_state(run_dir, state)

    decision_spec = replace(
        BASE_DECISION_LOOP_SPEC,
        key=context["key"],
        state_key=context["key"],
        decision_system_prompt=render_decision_system_prompt(
            TRD_DESIGN_DECISION_RULES,
            {
                "当前正式需求": {
                    key: context["requirement"][key]
                    for key in ("id", "title", "order", "depends_on")
                },
                "产品定义": product_output_contents(context["workspace"], inputs["product_outputs"]),
                "项目准备清单": inputs["checklist"],
                "总体技术方案": inputs["design"],
                "工程架构设计": inputs["architecture"],
                "产品级体验框架": inputs["ui_contents"]
                if inputs["ui_contents"] is not None
                else "当前产品没有适用的产品级 UI/UX 框架文档。",
                "正式 Backlog": inputs["backlog"],
                "统一需求分支": context["branch"],
                "权威工程": [repository["name"] for repository in context["repositories"]],
                "唯一活动 TRD": trd_path,
            },
        ),
    )

    def completion_verifier() -> str | None:
        verified_context = _context(run_dir, state)
        verified_path = _validate_saved_trd_path(
            verified_context, verified_context["cycle"].get("trd_path")
        )
        _verify_boundary(verified_context, verified_path)
        document_state = _document_state(verified_context, verified_path)
        if document_state != "ready":
            return _repair_prompt(verified_path)
        if _status_entries(verified_context["workspace"]) != [("??", verified_path)]:
            raise RuntimeError("活动 TRD 完成现场不符合约定")
        return None

    async def _verified_decision_runner(
        messages: list[dict[str, str]],
        config: Any,
        *,
        system_prompt: str,
    ) -> Any:
        _verify_boundary(context, trd_path)
        return await decision_runner(messages, config, system_prompt=system_prompt)

    effective_agent_runner = agent_runner
    if agent_runner is None:
        async def restricted_agent_runner(prompt: str, **kwargs: Any) -> Any:
            return await run_claude(
                prompt,
                tools=TRD_AGENT_TOOLS,
                hooks=_trd_agent_hooks(context, trd_path),
                **kwargs,
            )

        effective_agent_runner = restricted_agent_runner

    decision = await run_agent_decision_loop(
        run_dir,
        state,
        context["workspace"],
        decision_spec,
        agent_prompt,
        completion_verifier,
        agent_runner=effective_agent_runner,
        decision_runner=_verified_decision_runner,
        config_loader=config_loader,
    )

    if decision.verdict == "blocked":
        _verify_boundary(context, trd_path)
        outputs = [trd_path] if _document_state(context, trd_path) == "ready" else []
        blocked = {
            "reason": decision.reason,
            "required_inputs": decision.required_inputs,
            "resume_phase": PHASE,
            "resume_node": CURRENT_NODE,
            "resume_step": STEP,
        }
        blocked_result = result(
            "blocked",
            decision.reason,
            requirement_id=context["requirement_id"],
            branch=context["branch"],
            trd_path=trd_path,
            trd_session_id=_session(state, context["key"]),
            outputs=outputs,
            blocked=blocked,
        )
        write_requirement_step_result(run_dir, context["requirement_id"], STEP, blocked_result)
        state.update(
            {
                "status": "blocked",
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": blocked,
                "error": None,
            }
        )
        write_state(run_dir, state)
        raise TRDDesignBlocked(
            decision.reason,
            decision.required_inputs,
            requirement_id=context["requirement_id"],
            branch=context["branch"],
            trd_path=trd_path,
            trd_session_id=_session(state, context["key"]),
            outputs=outputs,
        )

    if not _completion_ready(run_dir, state, context, trd_path):
        raise RuntimeError("活动 TRD 完成核验后现场不符合约定")
    success = result(
        "success",
        "trd-design 已形成当前活动需求的技术设计。",
        requirement_id=context["requirement_id"],
        branch=context["branch"],
        trd_path=trd_path,
        trd_session_id=_session(state, context["key"]),
        outputs=[trd_path],
    )
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, success)
