from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import SYSTEM_PROMPT, request_decision
from common.files import resolve_workspace_output, sha256, write_json
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
PROJECT_INTAKE_MAX_BUDGET_USD = 4.0
COMPLETION_MESSAGE = (
    "已完成 project-intake：两份正式产品定义文档已生成并通过文件事实核验。"
)


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


def trust_project(workspace: Path) -> None:
    claude_json = Path.home() / ".claude.json"
    data: dict[str, Any] = {}
    if claude_json.is_file():
        data = json.loads(claude_json.read_text(encoding="utf-8"))
    projects = data.setdefault("projects", {})
    project = projects.setdefault(str(workspace), {})
    project["hasTrustDialogAccepted"] = True
    write_json(claude_json, data)


def validate_inputs(run_dir: Path, state: dict[str, Any]) -> tuple[Path, Path]:
    if state.get("current_step") not in {1, 2} or state.get("publication_phase") != "git_initialized":
        raise RuntimeError("第 1 步尚未成功发布并初始化根 Git 仓库")
    workspace = Path(state["workspace"]["final_path"]).resolve()
    root = Path(state["workspace"]["root"]).resolve()
    staging = Path(state["workspace"]["staging_path"]).resolve()
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
    previous_result_path = run_dir / "steps" / "01.json"
    try:
        previous_result = json.loads(previous_result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 1 步结果不可读取") from error
    previous_outputs = previous_result.get("outputs")
    if (
        previous_result.get("step") != 1
        or previous_result.get("status") != "success"
        or not isinstance(previous_outputs, list)
        or len(previous_outputs) != 1
        or not isinstance(previous_outputs[0], str)
        or not previous_outputs[0]
    ):
        raise RuntimeError("第 1 步结果缺少可用产物")
    draft = resolve_workspace_output(workspace, previous_outputs[0])
    if draft != workspace.resolve() / "docs/产品初稿.md":
        raise RuntimeError("第 1 步产物与运行状态不一致")
    if not workspace.is_dir() or workspace.is_symlink() or draft.is_symlink() or not draft.is_file():
        raise RuntimeError("第 1 步发布的项目工作区或产品初稿不存在")
    source = Path(state["input"]["source_path"])
    expected_hash = state["input"]["source_sha256"]
    if not source.is_file() or sha256(source) != expected_hash or sha256(draft) != expected_hash:
        raise RuntimeError("源产品初稿或项目内产品初稿与运行记录不一致")
    published_path = state.get("input", {}).get("published_path")
    if (
        not isinstance(published_path, str)
        or Path(published_path).resolve() != draft.resolve()
    ):
        raise RuntimeError("第 1 步 published_path 与产物结果不一致")
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
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    *,
    decision_turn: int | None = None,
) -> None:
    path = run_dir / CONVERSATION_PATH
    path.parent.mkdir(exist_ok=True)
    write_json(path, {"messages": messages})
    if decision_turn is None:
        decision_turn = (
            state.get("decision_conversations", {})
            .get(CONVERSATION_KEY, {})
            .get("turn", 0)
        )
    state.setdefault("decision_conversations", {})[CONVERSATION_KEY] = {
        "path": str(CONVERSATION_PATH),
        "turn": decision_turn,
    }
    write_state(run_dir, state)


def append_initial_agent_prompt(
    run_dir: Path, state: dict[str, Any], prompt: str
) -> None:
    messages = load_conversation(run_dir, state)
    if len(messages) == 1:
        messages.append({"role": "assistant", "content": prompt})
        save_conversation(run_dir, state, messages)


def append_completion(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    agent_text: str,
) -> None:
    messages.append({"role": "user", "content": agent_text})
    messages.append({"role": "assistant", "content": COMPLETION_MESSAGE})
    save_conversation(run_dir, state, messages)


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


def initial_prompt(draft: Path, workspace: Path) -> str:
    return f"/project-intake @./{draft.relative_to(workspace).as_posix()}"


def resume_prompt(draft: Path, workspace: Path) -> str:
    reference = draft.relative_to(workspace).as_posix()
    return f"请重新读取 @./{reference}，核验当前事实并继续完成本步骤。"


def decision_prompt(decision: dict[str, Any]) -> str:
    return decision["answer"]


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
) -> dict[str, Any]:
    workspace, draft = validate_inputs(run_dir, state)
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
            outputs=[relative.as_posix() for relative in OUTPUTS],
        )
    trust_project(workspace)
    state.update({"current_step": STEP, "status": "running", "blocked": None, "error": None})
    write_state(run_dir, state)
    existing_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    pending = state.get("project_intake", {}).pop("pending_agent_prompt", None)
    if pending:
        prompt = pending
    else:
        prompt = (
            initial_prompt(draft, workspace)
            if not existing_session
            else resume_prompt(draft, workspace)
        )
    if not existing_session:
        append_initial_agent_prompt(run_dir, state, prompt)

    for _ in range(MAX_DECISION_ROUNDS + 1):
        pending = state.get("project_intake", {}).pop("pending_agent_prompt", None)
        if pending:
            prompt = pending
            write_state(run_dir, state)
        run_result = await agent_runner(
            prompt,
            cwd=workspace,
            skill=SKILL_NAME,
            resume_session_id=state.get("claude_sessions", {}).get(CONVERSATION_KEY),
            max_budget_usd=PROJECT_INTAKE_MAX_BUDGET_USD,
            on_update=lambda update: save_agent_update(run_dir, state, update),
        )
        save_agent_update(run_dir, state, run_result)
        if not run_result.result_subtype:
            raise RuntimeError(run_result.exception or "Agent SDK 未返回 ResultMessage")
        recoverable_subtypes = {"error_max_turns", "error_max_budget_usd"}
        if (
            run_result.exception
            and run_result.result_subtype not in recoverable_subtypes
        ):
            raise RuntimeError(run_result.exception)
        if (
            run_result.is_error
            and run_result.result_subtype not in recoverable_subtypes
        ):
            raise RuntimeError(f"Agent SDK 执行失败：{run_result.result_subtype}")
        init = run_result.init or {}
        if SKILL_NAME not in {str(item) for item in init.get("skills") or []}:
            raise RuntimeError("Agent SDK 未加载 project-intake Skill")
        if SKILL_NAME not in {
            str(item) for item in init.get("slash_commands") or []
        }:
            raise RuntimeError("Agent SDK 未加载 project-intake slash command")
        outputs = output_contents(workspace)
        messages = load_conversation(run_dir, state)
        if (
            run_result.result_subtype == "success"
            and not run_result.is_error
            and outputs is not None
        ):
            validate_inputs(run_dir, state)
            paths = [relative.as_posix() for relative in OUTPUTS]
            append_completion(run_dir, state, messages, run_result.text)
            state.setdefault("project_intake", {}).pop("pending_agent_prompt", None)
            state.update({"status": "success", "blocked": None, "error": None})
            write_state(run_dir, state)
            return result("success", "project-intake 已生成产品定义文档。", outputs=paths)

        session_id = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
        if not session_id:
            raise RuntimeError("Agent 未完成且没有可恢复的 session ID")
        messages.append(
            {
                "role": "user",
                "content": decision_context(workspace, draft, run_result.text, outputs),
            }
        )
        decision, _, raw = await decision_runner(messages, LLMConfig.load())
        prompt = decision_prompt(decision)
        messages.append(
            {
                "role": "assistant",
                "content": raw,
            }
        )
        current_turn = (
            state.get("decision_conversations", {})
            .get(CONVERSATION_KEY, {})
            .get("turn", 0)
        )
        save_conversation(run_dir, state, messages, decision_turn=current_turn + 1)
        if decision["action"] == "blocked":
            raise ProjectIntakeBlocked(decision["reason"], decision["required_inputs"])
        state.setdefault("project_intake", {})["pending_agent_prompt"] = prompt
        write_state(run_dir, state)

    raise RuntimeError("project-intake 决策循环达到上限仍未产生产物")
