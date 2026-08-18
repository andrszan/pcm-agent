from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import SYSTEM_PROMPT, request_decision
from common.files import sha256, write_json
from common.state import write_state
from config import LLMConfig
from steps.step_01_create_workspace import inspect_root_repository

STEP = 2
NAME = "项目需求与产品定义"
CONVERSATION_KEY = "project_intake"
SKILL_NAME = "project-intake"
CONVERSATION_PATH = Path("conversations/project_intake.json")
OUTPUTS = (
    Path("docs/requirements/项目需求说明.md"),
    Path("docs/requirements/产品功能说明.md"),
)
MAX_DECISION_ROUNDS = 6


class ProjectIntakeBlocked(RuntimeError):
    def __init__(self, reason: str, required_inputs: list[str]):
        super().__init__(reason)
        self.required_inputs = required_inputs


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


def trust_project(config_dir_path: Path, workspace: Path) -> None:
    claude_json = config_dir_path / ".claude.json"
    data: dict[str, Any] = {}
    if claude_json.is_file():
        data = json.loads(claude_json.read_text(encoding="utf-8"))
    projects = data.setdefault("projects", {})
    project = projects.setdefault(str(workspace), {})
    project["hasTrustDialogAccepted"] = True
    write_json(claude_json, data)


def validate_inputs(state: dict[str, Any]) -> tuple[Path, Path]:
    if state.get("current_step") not in {1, 2} or state.get("publication_phase") != "git_initialized":
        raise RuntimeError("第 1 步尚未成功发布并初始化根 Git 仓库")
    workspace = Path(state["workspace"]["final_path"])
    root = Path(state["workspace"]["root"])
    staging = Path(state["workspace"]["staging_path"])
    if workspace.parent != root or staging.exists():
        raise RuntimeError("第 1 步发布现场或路径证据不一致")
    checks = state.get("checks", {})
    if not all(
        checks.get(key) is True
        for key in (
            "template_capabilities_present",
            "upstream_git_removed",
            "docs_reinitialized",
            "draft_hash_matches",
            "source_draft_unchanged",
            "renamed_to_final_path",
            "root_git_initialized",
            "root_git_is_final_path",
            "root_git_has_no_commits",
        )
    ):
        raise RuntimeError("第 1 步发布或根 Git 核验记录不完整")
    root_repository = inspect_root_repository(workspace)
    if state.get("root_repository") != root_repository:
        raise RuntimeError("第 1 步根 Git 仓库与运行记录不一致")
    draft = workspace / "docs/产品初稿.md"
    if not workspace.is_dir() or workspace.is_symlink() or not draft.is_file():
        raise RuntimeError("第 1 步发布的项目工作区或产品初稿不存在")
    source = Path(state["input"]["source_path"])
    expected_hash = state["input"]["source_sha256"]
    if not source.is_file() or sha256(source) != expected_hash or sha256(draft) != expected_hash:
        raise RuntimeError("源产品初稿或项目内产品初稿与运行记录不一致")
    return workspace, draft


def output_contents(workspace: Path) -> dict[str, str] | None:
    contents: dict[str, str] = {}
    for relative in OUTPUTS:
        path = workspace / relative
        if path.is_symlink() or not path.is_file():
            return None
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return None
        contents[str(relative)] = content
    return contents


def safe_result(run: ClaudeRunResult) -> dict[str, Any]:
    return {
        "subtype": run.result_subtype,
        "is_error": run.is_error,
        "stop_reason": run.stop_reason,
        "session_id": run.session_id,
        "num_turns": run.num_turns,
        "total_cost_usd": run.total_cost_usd,
        "exception": run.exception,
    }


def save_agent_update(run_dir: Path, state: dict[str, Any], run: ClaudeRunResult) -> None:
    previous_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    if previous_session and run.session_id and previous_session != run.session_id:
        raise RuntimeError(
            f"恢复 session ID 不一致：期望 {previous_session}，实际 {run.session_id}"
        )
    if run.session_id:
        state.setdefault("claude_sessions", {})[CONVERSATION_KEY] = run.session_id
    intake = state.setdefault("project_intake", {})
    if run.init:
        skills = {str(item) for item in run.init.get("skills") or []}
        commands = {str(item) for item in run.init.get("slash_commands") or []}
        intake["skill_loaded"] = SKILL_NAME in skills
        intake["slash_command_loaded"] = SKILL_NAME in commands
        intake["init"] = {
            key: run.init.get(key)
            for key in ("cwd", "model", "permissionMode", "claude_code_version")
        }
    if run.result_subtype:
        intake["last_agent_result"] = safe_result(run)
    write_state(run_dir, state)


def load_conversation(run_dir: Path, state: dict[str, Any]) -> list[dict[str, str]]:
    reference = state.get("decision_conversations", {}).get(CONVERSATION_KEY)
    if reference is None:
        return [{"role": "system", "content": SYSTEM_PROMPT}]
    if set(reference) != {"path", "turn"} or reference["path"] != str(CONVERSATION_PATH):
        raise RuntimeError("决策历史引用不符合约定")
    data = json.loads((run_dir / CONVERSATION_PATH).read_text(encoding="utf-8"))
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("决策历史内容不符合约定")
    return messages


def save_conversation(
    run_dir: Path, state: dict[str, Any], messages: list[dict[str, str]]
) -> None:
    path = run_dir / CONVERSATION_PATH
    path.parent.mkdir(exist_ok=True)
    write_json(path, {"messages": messages})
    turn = sum(message["role"] == "assistant" for message in messages)
    state.setdefault("decision_conversations", {})[CONVERSATION_KEY] = {
        "path": str(CONVERSATION_PATH),
        "turn": turn,
    }
    write_state(run_dir, state)


def decision_context(
    workspace: Path,
    draft: Path,
    agent_text: str,
    outputs: dict[str, str] | None,
) -> str:
    allowed = {
        "docs/产品初稿.md": draft.read_text(encoding="utf-8"),
        "CLAUDE.md": (workspace / "CLAUDE.md").read_text(encoding="utf-8"),
        "AGENTS.md": (workspace / "AGENTS.md").read_text(encoding="utf-8"),
        ".claude/settings.json": (workspace / ".claude/settings.json").read_text(
            encoding="utf-8"
        ),
    }
    if outputs:
        allowed.update(outputs)
    return json.dumps(
        {
            "step": STEP,
            "name": NAME,
            "completion": "project-intake 正常结束且两份默认产物真实存在并可读",
            "allowed_inputs": allowed,
            "agent_result": agent_text,
            "outputs_present": outputs is not None,
        },
        ensure_ascii=False,
    )


def decision_prompt(decision: dict[str, Any]) -> str:
    action = decision["action"]
    if action == "approve":
        return (
            "作为 PCM 的等效开发者授权，我现在明确同意创建或更新 "
            "project-intake 的正式产品定义文档。请按已确认决定完成当前步骤。"
        )
    if action == "continue":
        return "继续使用当前已有事实完成同一个 project-intake 步骤，不扩大输入范围。"
    return f"PCM 决定：{decision['answer']}\n理由：{decision['reason']}\n请据此继续当前步骤。"


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
) -> dict[str, Any]:
    workspace, draft = validate_inputs(state)
    existing_outputs = output_contents(workspace)
    previous_result = state.get("project_intake", {}).get("last_agent_result", {})
    if (
        state.get("status") == "success"
        and previous_result.get("subtype") == "success"
        and previous_result.get("is_error") is False
        and existing_outputs is not None
    ):
        state.setdefault("project_intake", {}).pop("pending_agent_prompt", None)
        write_state(run_dir, state)
        return result(
            "success",
            "project-intake 已生成产品定义文档，确认既有成功。",
            outputs=[str(workspace / relative) for relative in OUTPUTS],
        )
    run_config_dir = run_dir / "claude-config"
    run_config_dir.mkdir(parents=True, exist_ok=True)
    trust_project(run_config_dir, workspace)
    state.update({"current_step": STEP, "status": "running", "blocked": None, "error": None})
    write_state(run_dir, state)
    existing_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    pending = state.get("project_intake", {}).pop("pending_agent_prompt", None)
    if pending:
        prompt = pending
    else:
        prompt = (
        "/project-intake 请阅读 docs/产品初稿.md 和项目规则，通过必要的多轮讨论形成该 Skill "
        "规定的默认产品定义文档。只处理本步骤输入，不读取技术方案、Backlog、TRD 或代码。"
        if not existing_session
        else "重新核验当前产品初稿和 project-intake 产物事实，继续完成当前步骤。"
    )

    for _ in range(MAX_DECISION_ROUNDS + 1):
        pending = state.get("project_intake", {}).pop("pending_agent_prompt", None)
        if pending:
            prompt = pending
            write_state(run_dir, state)
        run_result = await agent_runner(
            prompt,
            cwd=workspace,
            skill=SKILL_NAME,
            config_dir=run_config_dir,
            resume_session_id=state.get("claude_sessions", {}).get(CONVERSATION_KEY),
            on_update=lambda update: save_agent_update(run_dir, state, update),
        )
        save_agent_update(run_dir, state, run_result)
        init = run_result.init or {}
        if SKILL_NAME not in {str(item) for item in init.get("skills") or []}:
            raise RuntimeError("Agent SDK 未加载 project-intake Skill")
        if SKILL_NAME not in {
            str(item) for item in init.get("slash_commands") or []
        }:
            raise RuntimeError("Agent SDK 未加载 project-intake slash command")
        if run_result.exception or not run_result.result_subtype:
            raise RuntimeError(run_result.exception or "Agent SDK 未返回 ResultMessage")
        if run_result.is_error and run_result.result_subtype not in {
            "error_max_turns",
            "error_max_budget_usd",
        }:
            raise RuntimeError(f"Agent SDK 执行失败：{run_result.result_subtype}")

        outputs = output_contents(workspace)
        if (
            run_result.result_subtype == "success"
            and not run_result.is_error
            and outputs is not None
        ):
            validate_inputs(state)
            paths = [str(workspace / relative) for relative in OUTPUTS]
            state.setdefault("project_intake", {}).pop("pending_agent_prompt", None)
            state.update({"status": "success", "blocked": None, "error": None})
            write_state(run_dir, state)
            return result("success", "project-intake 已生成产品定义文档。", outputs=paths)

        session_id = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
        if not session_id:
            raise RuntimeError("Agent 未完成且没有可恢复的 session ID")
        messages = load_conversation(run_dir, state)
        messages.append(
            {
                "role": "user",
                "content": decision_context(workspace, draft, run_result.text, outputs),
            }
        )
        decision, _, raw = await decision_runner(messages, LLMConfig.load())
        messages.append({"role": "assistant", "content": raw})
        save_conversation(run_dir, state, messages)
        if decision["action"] == "blocked":
            raise ProjectIntakeBlocked(decision["reason"], decision["required_inputs"])
        prompt = decision_prompt(decision)
        state.setdefault("project_intake", {})["pending_agent_prompt"] = prompt
        write_state(run_dir, state)

    raise RuntimeError("project-intake 决策循环达到上限仍未产生产物")
