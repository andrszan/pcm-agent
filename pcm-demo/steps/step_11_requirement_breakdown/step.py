from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import parse_agent_decision, render_decision_system_prompt, request_decision
from common.files import resolve_workspace_output
from common.state import step_result_status, write_state, write_step_result
from config import LLMConfig
from steps.step_02_project_intake.step import OUTPUTS as PRODUCT_OUTPUT_PATHS
from steps.step_05_project_readiness.step import (
    CHECKLIST,
    checklist_contents,
    load_product_outputs,
    product_output_contents,
    verify_existing_readiness_success,
)
from steps.step_07_solution_design.step import (
    DESIGN_PATH,
    verify_existing_solution_success,
)

STEP = 11
NAME = "拆分 Backlog"
CURRENT_NODE = "project:11_requirement_breakdown"
NEXT_NODE = "phase_1:select_requirement"
CONVERSATION_KEY = "requirement_breakdown"
SKILL_NAME = "requirement-breakdown"
BACKLOG_PATH = Path("docs/backlog/backlog.md")
ARCHITECTURE_OUTPUT_PATH = Path("docs/design/工程架构设计.md")
UI_UX_FRAMEWORK_PATH = Path("docs/ui-ux/framework.md")
MAX_DECISION_ROUNDS = 8
REQUIREMENT_BREAKDOWN_MAX_TURNS = 48
REQUIREMENT_BREAKDOWN_MAX_BUDGET_USD = 16.0

BACKLOG_REPAIR_PROMPT = (
    "固定 Backlog 文档缺失或为空。请仅创建或补全 docs/backlog/backlog.md；"
    "不得修改任何其他文件，不得执行 Git 写操作，然后报告结果。"
)
COMMIT_REPAIR_PROMPT = """/commit-changes
只授权处理产品根 Git 仓库中的固定文档 `docs/backlog/backlog.md`。请核验该文档；仅当它存在未提交变更时，暂存并提交这一个文件，然后确认产品根仓库工作区干净。不得暂存、提交或修改任何其他路径，不得处理子仓库，不得建分支、改写历史或 push。若固定文档相对当前提交没有变化，直接报告无变更，不得制造变更。"""

REQUIREMENT_BREAKDOWN_DECISION_RULES = """- completed：固定 Backlog 文档已生成，基于权威产品定义、项目准备清单、总体技术方案、工程架构设计、产品级体验框架（如适用）和实际工程，形成可独立交付、可验证、顺序合理的正式需求条目，说明范围、目标、验收要点、依赖和风险；不把需求开发状态写入 Backlog，不越界实施需求。
- continue：Backlog、工程事实核验或需求拆分仍可在当前项目中补全。
- blocked：只能用于缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务或线下动作。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key=CONVERSATION_KEY,
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=REQUIREMENT_BREAKDOWN_MAX_TURNS,
    max_budget_usd=REQUIREMENT_BREAKDOWN_MAX_BUDGET_USD,
    decision_system_prompt=render_decision_system_prompt(REQUIREMENT_BREAKDOWN_DECISION_RULES, {}),
)


class RequirementBreakdownBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        outputs: list[str] | None = None,
    ) -> None:
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.outputs = outputs or []


def result(
    status: str,
    summary: str,
    *,
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
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
    }


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


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
    if not root.is_absolute() or not workspace.is_absolute():
        raise RuntimeError("工作区状态路径必须为绝对路径")
    if workspace.is_symlink():
        raise RuntimeError("产品工作区不得是符号链接")
    root = root.resolve()
    workspace = workspace.resolve()
    if workspace.parent != root or not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    return workspace


def _read_json(path: Path, message: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(message) from error
    if not isinstance(value, dict):
        raise RuntimeError(message)
    return value


def _repository_path(workspace: Path, name: str) -> Path:
    return workspace if name == "root" else workspace / name


def _validate_repository_entry(entry: Any, *, name: str, path: str) -> None:
    if entry != {
        "name": name,
        "path": path,
        "branch": "main",
        "worktree_clean": True,
    }:
        raise RuntimeError("第 8 步仓库 clean 交接事实不符合约定")


def _step_eight_handoff(run_dir: Path, state: dict[str, Any]) -> tuple[Path, list[str]]:
    workspace = _workspace_from_state(state)
    previous = _read_json(run_dir / "steps" / "08.json", "第 8 步成功结果不可读取")
    names = previous.get("applicable_repositories")
    result_repositories = previous.get("repositories")
    expected_result_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
        "applicable_repositories",
        "repositories",
    }
    if (
        set(previous) != expected_result_keys
        or previous.get("step") != 8
        or previous.get("name") != "首次提交适用仓库"
        or previous.get("status") != "success"
        or not isinstance(previous.get("summary"), str)
        or not previous["summary"].strip()
        or previous.get("applicable") is not True
        or previous.get("outputs") != []
        or previous.get("blocked") is not None
        or previous.get("error") is not None
        or not isinstance(names, list)
        or not names
        or names[0] != "root"
        or any(name not in {"root", "frontend", "backend"} for name in names)
        or len(set(names)) != len(names)
        or not isinstance(result_repositories, list)
        or len(result_repositories) != len(names)
    ):
        raise RuntimeError("第 8 步仓库 clean 交接结果不符合约定")

    state_names = state.get("applicable_repositories")
    state_repositories = state.get("repositories")
    if (
        state_names != names
        or not isinstance(state_repositories, list)
        or len(state_repositories) != len(names)
    ):
        raise RuntimeError("第 8 步仓库 clean 交接状态不符合约定")

    for index, name in enumerate(names):
        _validate_repository_entry(
            result_repositories[index], name=name, path="." if name == "root" else name
        )
        _validate_repository_entry(
            state_repositories[index],
            name=name,
            path=str(_repository_path(workspace, name).resolve()),
        )
    return workspace, names


def _document_contents(workspace: Path, relative: Path, label: str) -> str:
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError(f"{label}路径不能包含符号链接")
    try:
        path = resolve_workspace_output(workspace, relative.as_posix())
    except ValueError as error:
        raise RuntimeError(f"{label}路径不符合约定") from error
    if not path.is_file():
        raise RuntimeError(f"{label}不是普通文件")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"{label}不可读取") from error
    if not content.strip():
        raise RuntimeError(f"{label}不能为空")
    return content


def _architecture_output(run_dir: Path) -> Path:
    previous = _read_json(run_dir / "steps" / "09.json", "第 9 步成功结果不可读取")
    outputs = previous.get("outputs")
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
    }
    if (
        set(previous) != expected_keys
        or previous.get("step") != 9
        or previous.get("name") != "工程架构设计"
        or previous.get("status") != "success"
        or not isinstance(previous.get("summary"), str)
        or not previous["summary"].strip()
        or previous.get("applicable") is not True
        or previous.get("outputs") != [ARCHITECTURE_OUTPUT_PATH.as_posix()]
        or previous.get("blocked") is not None
        or previous.get("error") is not None
    ):
        raise RuntimeError("第 9 步工程架构设计结果不可复用")
    output = outputs[0]
    relative = Path(output)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RuntimeError("第 9 步工程架构设计产物路径不符合约定")
    return relative


def _requirement_breakdown_input(run_dir: Path, workspace: Path) -> str | None:
    previous = _read_json(run_dir / "steps" / "10.json", "第 10 步成功结果不可读取")
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
    }
    if (
        set(previous) != expected_keys
        or previous.get("step") != 10
        or previous.get("name") != "产品级 UI/UX 框架"
        or previous.get("status") != "success"
        or not isinstance(previous.get("summary"), str)
        or not previous["summary"].strip()
        or previous.get("blocked") is not None
        or previous.get("error") is not None
    ):
        raise RuntimeError("第 10 步产品级 UI/UX 框架结果不可复用")
    if previous.get("applicable") is True:
        if previous.get("outputs") != [UI_UX_FRAMEWORK_PATH.as_posix()]:
            raise RuntimeError("第 10 步适用产品级 UI/UX 框架结果不可复用")
        return _document_contents(workspace, UI_UX_FRAMEWORK_PATH, "拆分 Backlog")
    if previous.get("applicable") is False and previous.get("outputs") == []:
        return None
    raise RuntimeError("第 10 步产品级 UI/UX 框架适用性结果不可复用")


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], list[str], str, str, Path, str, str | None]:
    if _position(state) not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于拆分 Backlog 锚点")
    workspace, names = _step_eight_handoff(run_dir, state)
    product_outputs = load_product_outputs(run_dir, workspace)
    if product_outputs != [path.as_posix() for path in PRODUCT_OUTPUT_PATHS]:
        raise RuntimeError("第 2 步产品定义输出不符合约定")
    verify_existing_readiness_success(run_dir)
    checklist = checklist_contents(workspace)
    if checklist is None:
        raise RuntimeError("第 5 步项目准备清单不存在或不可读取")
    verify_existing_solution_success(run_dir)
    design = _document_contents(workspace, DESIGN_PATH, "总体技术方案")
    architecture_path = _architecture_output(run_dir)
    architecture = _document_contents(workspace, architecture_path, "工程架构设计")
    requirement_breakdown = _requirement_breakdown_input(run_dir, workspace)
    return (
        workspace,
        names,
        product_outputs,
        checklist,
        design,
        architecture_path,
        architecture,
        requirement_breakdown,
    )


def _git_run(
    path: Path,
    *args: str,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=path,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if completed.returncode not in allowed_returncodes:
        raise RuntimeError("无法读取 Git 仓库状态")
    return completed


def _git_read(path: Path, *args: str) -> str:
    return _git_run(path, *args).stdout.rstrip("\n")


def _repository_facts(workspace: Path, names: list[str]) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    for name in names:
        repository = _repository_path(workspace, name)
        if repository.is_symlink() or not repository.is_dir():
            raise RuntimeError("权威 Git 仓库路径不存在或是符号链接")
        path = repository.resolve()
        top_level = Path(_git_read(path, "rev-parse", "--show-toplevel")).resolve()
        if top_level != path:
            raise RuntimeError("Git 仓库顶层目录与权威仓库路径不一致")
        if _git_read(path, "branch", "--show-current") != "main":
            raise RuntimeError("Git 仓库分支不是 main")
        status = _git_read(path, "status", "--porcelain=v1", "--untracked-files=all")
        repositories.append(
            {
                "name": name,
                "path": str(path),
                "branch": "main",
                "worktree_clean": status == "",
                "status": status,
            }
        )
    return repositories


def _document_status(workspace: Path) -> str:
    return _git_read(
        workspace,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        BACKLOG_PATH.as_posix(),
    )


def _document_tracked(workspace: Path) -> bool:
    completed = _git_run(
        workspace,
        "ls-files",
        "--error-unmatch",
        "--",
        BACKLOG_PATH.as_posix(),
        allowed_returncodes=(0, 1),
    )
    return completed.returncode == 0


def _verify_worktree_boundary(
    workspace: Path, names: list[str]
) -> tuple[list[dict[str, Any]], str]:
    repositories = _repository_facts(workspace, names)
    for repository in repositories[1:]:
        if not repository["worktree_clean"]:
            raise RuntimeError("Backlog期间子仓库必须保持 clean")
    root_status = repositories[0]["status"]
    document_status = _document_status(workspace)
    if " -> " in root_status or root_status != document_status:
        raise RuntimeError("产品根仓库存在固定Backlog文档范围外的修改")
    return repositories, root_status


def backlog_repair(workspace: Path) -> str | None:
    current = workspace
    for part in BACKLOG_PATH.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError("Backlog文档路径不能包含符号链接")
    try:
        path = resolve_workspace_output(workspace, BACKLOG_PATH.as_posix())
    except ValueError as error:
        raise RuntimeError("Backlog文档路径不符合约定") from error
    if not path.exists():
        return BACKLOG_REPAIR_PROMPT
    if not path.is_file():
        raise RuntimeError("Backlog文档必须是普通文件")
    try:
        if not path.read_text(encoding="utf-8").strip():
            return BACKLOG_REPAIR_PROMPT
    except (OSError, UnicodeError) as error:
        raise RuntimeError("Backlog文档不可读取") from error
    return None


def _conversation_reference(state: dict[str, Any]) -> Path | None:
    references = state.get("decision_conversations")
    if references is None:
        return None
    if not isinstance(references, dict):
        raise RuntimeError("Backlog决策历史引用不符合约定")
    reference = references.get(CONVERSATION_KEY)
    if reference is None:
        return None
    expected = Path("conversations") / f"{CONVERSATION_KEY}.json"
    if not isinstance(reference, dict) or reference.get("path") != expected.as_posix():
        raise RuntimeError("Backlog决策历史引用不符合约定")
    return expected


def _session(state: dict[str, Any]) -> str | None:
    sessions = state.get("claude_sessions")
    if sessions is None:
        return None
    if not isinstance(sessions, dict):
        raise RuntimeError("Backlog Claude session 状态不符合约定")
    value = sessions.get(CONVERSATION_KEY)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeError("Backlog Claude session ID 不符合约定")
    return value


def _safe_conversation_path(run_dir: Path) -> Path:
    resolved_run_dir = run_dir.resolve()
    conversations = run_dir / "conversations"
    conversations_present = conversations.exists() or conversations.is_symlink()
    if conversations_present:
        if conversations.is_symlink() or not conversations.is_dir():
            raise RuntimeError("Backlog conversations 路径必须是非符号链接目录")
        resolved_conversations = conversations.resolve()
        if resolved_conversations.parent != resolved_run_dir:
            raise RuntimeError("Backlog conversations 路径越出运行目录")
    else:
        resolved_conversations = resolved_run_dir / "conversations"

    path = conversations / f"{CONVERSATION_KEY}.json"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Backlog决策历史必须是非符号链接普通文件")
        if path.resolve().parent != resolved_conversations:
            raise RuntimeError("Backlog决策历史路径越出 conversations 目录")
    return path


def _conversation_messages(path: Path) -> list[dict[str, str]]:
    conversation = _read_json(path, "Backlog决策历史不可读取")
    if set(conversation) != {"messages"}:
        raise RuntimeError("Backlog决策历史内容不符合约定")
    messages = conversation.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("Backlog决策历史内容不符合约定")
    normalized: list[dict[str, str]] = []
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message.get("role") not in {"system", "assistant", "user"}
            or not isinstance(message.get("content"), str)
        ):
            raise RuntimeError("Backlog决策历史消息不符合约定")
        normalized.append({"role": message["role"], "content": message["content"]})
    if normalized[0]["role"] != "system":
        raise RuntimeError("Backlog决策历史首条消息必须是 system")
    return normalized


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


def _execution_artifacts_present(run_dir: Path, state: dict[str, Any]) -> bool:
    sessions = state.get("claude_sessions")
    references = state.get("decision_conversations")
    conversation_path = _safe_conversation_path(run_dir)
    return (
        isinstance(sessions, dict)
        and CONVERSATION_KEY in sessions
        or isinstance(references, dict)
        and CONVERSATION_KEY in references
        or conversation_path.exists()
        or conversation_path.is_symlink()
        or CONVERSATION_KEY in state
    )


def _validate_execution_anchor(
    run_dir: Path,
    state: dict[str, Any],
    *,
    fresh: bool,
    initial_agent_prompt: str,
) -> bool:
    if fresh and _execution_artifacts_present(run_dir, state):
        raise RuntimeError("新鲜Backlog入口不得包含既有执行产物")

    session = _session(state)
    reference = _conversation_reference(state)
    path = _safe_conversation_path(run_dir)
    path_present = path.exists() or path.is_symlink()
    if path_present and reference is None:
        raise RuntimeError("Backlog恢复存在未引用的决策历史")
    if reference is not None and not path_present:
        raise RuntimeError("Backlog恢复缺少原决策历史")
    if path_present and (path.is_symlink() or not path.is_file()):
        raise RuntimeError("Backlog恢复决策历史必须是非符号链接普通文件")

    messages = _conversation_messages(path) if path_present else []
    section = state.get(CONVERSATION_KEY)
    if section is not None and not isinstance(section, dict):
        raise RuntimeError("Backlog执行状态不符合约定")
    section_has_facts = isinstance(section, dict) and bool(section)
    history_has_agent_reply = any(message["role"] == "user" for message in messages)
    history_has_decision = _has_structured_decision(messages)
    history_has_commit_prompt = any(
        message == {"role": "assistant", "content": COMMIT_REPAIR_PROMPT}
        for message in messages
    )
    execution_facts = (
        session is not None
        or section_has_facts
        or history_has_agent_reply
        or history_has_decision
        or history_has_commit_prompt
    )
    if execution_facts and session is None:
        raise RuntimeError("Backlog恢复缺少原 Claude session")
    if session is not None and reference is None:
        raise RuntimeError("Backlog恢复缺少原决策历史引用")

    if session is None and messages:
        allowed = [
            messages[:1],
            [
                messages[0],
                {"role": "assistant", "content": initial_agent_prompt},
            ],
        ]
        if messages not in allowed:
            raise RuntimeError("Backlog无 session 历史包含 Agent 执行事实")

    if state.get("status") == "blocked":
        try:
            tail = messages[-1]
            if tail["role"] != "assistant":
                raise ValueError
            decision = parse_agent_decision(tail["content"])
        except (IndexError, KeyError, ValueError):
            raise RuntimeError("Backlog恢复缺少有效的 blocked 决策历史") from None
        if decision.verdict != "blocked":
            raise RuntimeError("Backlog恢复历史尾部不是 blocked 决策")
    return execution_facts


def _commit_requested(run_dir: Path, state: dict[str, Any]) -> bool:
    path = _safe_conversation_path(run_dir)
    if _session(state) is None:
        return False
    relative = _conversation_reference(state)
    if relative is None:
        return False
    if path != run_dir / relative:
        raise RuntimeError("Backlog决策历史引用路径不符合约定")
    if not path.is_file():
        raise RuntimeError("Backlog决策历史不存在")
    messages = _conversation_messages(path)
    for index, message in enumerate(messages[:-1]):
        reply = messages[index + 1]
        if (
            message == {"role": "assistant", "content": COMMIT_REPAIR_PROMPT}
            and reply["role"] == "user"
            and bool(reply["content"].strip())
        ):
            return True
    return False


def _completion_ready(
    run_dir: Path,
    state: dict[str, Any],
    workspace: Path,
    names: list[str],
) -> tuple[bool, list[dict[str, Any]]]:
    repositories, root_status = _verify_worktree_boundary(workspace, names)
    ready = (
        backlog_repair(workspace) is None
        and _commit_requested(run_dir, state)
        and root_status == ""
        and _document_tracked(workspace)
    )
    return ready, repositories


def verify_existing_success(run_dir: Path) -> dict[str, Any]:
    existing = _read_json(run_dir / "steps" / "11.json", "第 11 步成功结果不可读取")
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
    }
    if (
        set(existing) != expected_keys
        or existing.get("step") != STEP
        or existing.get("name") != NAME
        or existing.get("status") != "success"
        or not isinstance(existing.get("summary"), str)
        or not existing["summary"].strip()
        or existing.get("applicable") is not True
        or existing.get("outputs") != [BACKLOG_PATH.as_posix()]
        or existing.get("blocked") is not None
        or existing.get("error") is not None
    ):
        raise RuntimeError("第 11 步成功结果不可复用")
    return existing


def advance_success(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    saved = result(
        "success",
        "requirement-breakdown 已生成固定 Backlog 文档并完成提交核验。",
        outputs=[BACKLOG_PATH.as_posix()],
    )
    write_step_result(run_dir, STEP, saved)
    state.update(
        {
            "status": "success",
            "phase": "phase_1_requirement_development",
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return saved


def initial_prompt(
    product_outputs: list[str],
    architecture_path: Path,
    ui_ux_framework: bool,
    names: list[str],
) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    engineering_references = "\n".join(
        "- 产品根工程：@./" if name == "root" else f"- {name} 工程：@./{name}"
        for name in names
    )
    experience_framework = (
        f"- @./{UI_UX_FRAMEWORK_PATH.as_posix()}"
        if ui_ux_framework
        else "- 当前产品没有适用的产品级体验框架文档。"
    )
    return f"""/requirement-breakdown
调用方已充分授权你直接生成正式 Backlog。请基于全部权威输入创建或更新唯一固定产物 `docs/backlog/backlog.md`。

权威产品定义：
{product_references}

项目准备事实：
- @./{CHECKLIST.as_posix()}

总体技术方案：
- @./{DESIGN_PATH.as_posix()}

工程架构设计：
- @./{architecture_path.as_posix()}

产品级体验框架：
{experience_framework}

权威实际工程：
{engineering_references}

Backlog 必须形成可独立交付、可验证、顺序合理的正式需求条目，说明每项需求的范围、目标、验收要点、依赖和风险，保持与产品、设计和工程事实一致。不得在 Backlog 中写入“待开发”“开发中”“已完成”“阻塞”等需求开发状态；业务对象或业务流程自身的状态可作为需求内容。不得猜测缺失事实或将未确认事项当作已确认决定。

只允许创建或更新固定 Backlog 文档。不得修改或新增其他文档、业务代码、测试、迁移、工程配置或项目规则；不得执行 Git 写操作，不得处理或披露秘密。最终完整回复须列出文档路径、依据的产品和工程事实、拆分出的主要需求与依赖风险、待确认事项和未验证范围。"""


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    (
        workspace,
        names,
        product_outputs,
        checklist,
        design,
        architecture_path,
        architecture,
        ui_ux_framework,
    ) = validate_inputs(run_dir, state)
    position = _position(state)
    existing_step_status = step_result_status(run_dir, STEP)
    initial_agent_prompt = initial_prompt(
        product_outputs, architecture_path, ui_ux_framework is not None, names
    )
    fresh = (
        position == (STEP, STEP, CURRENT_NODE)
        and state.get("status") == "success"
        and existing_step_status != "success"
    )
    started = _validate_execution_anchor(
        run_dir,
        state,
        fresh=fresh,
        initial_agent_prompt=initial_agent_prompt,
    )
    repositories, root_status = _verify_worktree_boundary(workspace, names)

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        verify_existing_success(run_dir)
        ready, _ = _completion_ready(run_dir, state, workspace, names)
        if not ready:
            raise RuntimeError("第 11 步成功后固定文档或仓库状态发生漂移")
        return result(
            "success",
            "requirement-breakdown 已生成固定 Backlog 文档并完成提交核验，确认既有成功。",
            outputs=[BACKLOG_PATH.as_posix()],
        )

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于拆分 Backlog 锚点")

    if existing_step_status == "success":
        verify_existing_success(run_dir)
        ready, _ = _completion_ready(run_dir, state, workspace, names)
        if not ready:
            raise RuntimeError("第 11 步既有成功缺少有效固定文档或 clean 仓库")
        return advance_success(run_dir, state)

    if not started and (
        root_status != "" or any(not item["worktree_clean"] for item in repositories)
    ):
        raise RuntimeError("首次拆分 Backlog Agent 执行前第 8 步权威仓库必须全仓 clean")

    if state.get("status") != "blocked":
        state.update(
            {"current_step": STEP, "status": "running", "blocked": None, "error": None}
        )
        write_state(run_dir, state)

    decision_spec = replace(
        DECISION_LOOP_SPEC,
        decision_system_prompt=render_decision_system_prompt(
            REQUIREMENT_BREAKDOWN_DECISION_RULES,
            {
                "产品定义": product_output_contents(workspace, product_outputs),
                "项目准备清单": checklist,
                "总体技术方案": design,
                "工程架构设计": architecture,
                "产品级体验框架": ui_ux_framework
                if ui_ux_framework is not None
                else "当前产品没有适用的产品级体验框架文档。",
                "权威工程": names,
                "固定输出": BACKLOG_PATH.as_posix(),
            },
        ),
    )

    def completion_verifier() -> str | None:
        verified_workspace, verified_names, *_ = validate_inputs(run_dir, state)
        _, verified_root_status = _verify_worktree_boundary(
            verified_workspace, verified_names
        )
        repair = backlog_repair(verified_workspace)
        if repair is not None:
            return repair
        if not _commit_requested(run_dir, state):
            return COMMIT_REPAIR_PROMPT
        if verified_root_status != "" or not _document_tracked(verified_workspace):
            return COMMIT_REPAIR_PROMPT
        return None

    async def _verified_decision_runner(
        messages: list[dict[str, str]],
        config: Any,
        *,
        system_prompt: str,
    ) -> Any:
        _verify_worktree_boundary(workspace, names)
        return await decision_runner(messages, config, system_prompt=system_prompt)

    decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        decision_spec,
        initial_agent_prompt,
        completion_verifier,
        agent_runner=agent_runner,
        decision_runner=_verified_decision_runner,
        config_loader=config_loader,
    )

    if decision.verdict == "blocked":
        ready, _ = _completion_ready(run_dir, state, workspace, names)
        if ready:
            return advance_success(run_dir, state)
        outputs = [BACKLOG_PATH.as_posix()] if backlog_repair(workspace) is None else []
        blocked = {
            "reason": decision.reason,
            "required_inputs": decision.required_inputs,
            "resume_phase": "project_initialization",
            "resume_node": CURRENT_NODE,
            "resume_step": STEP,
        }
        saved = result("blocked", decision.reason, outputs=outputs, blocked=blocked)
        write_step_result(run_dir, STEP, saved)
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
        raise RequirementBreakdownBlocked(decision.reason, decision.required_inputs, outputs)

    ready, _ = _completion_ready(run_dir, state, workspace, names)
    if not ready:
        raise RuntimeError("拆分 Backlog 完成核验后固定文档或仓库状态不符合约定")
    return advance_success(run_dir, state)
