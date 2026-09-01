from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.state import (
    is_valid_requirement_id,
    requirement_step_result_path,
    write_requirement_step_result,
    write_state,
)
from config import LLMConfig

STEP = 15
NAME = "实现与验证"
CURRENT_NODE = "requirement:15_development"
NEXT_NODE = "requirement:16_rule_retrospective"
PHASE = "phase_1_requirement_development"
SKILL_NAME = "dev-workflow"
MAX_DECISION_ROUNDS = 16
DEVELOPMENT_MAX_TURNS = 100

DEVELOPMENT_DECISION_RULES = """- completed：Agent 已明确表示当前需求的全部实现完成，所有适用测试、真实验证和审查均已完成，且没有剩余工作、验证缺口或阻断项。存在适用的已确认 Target 或有依据的默认 Target 时，完成报告必须建立决定（默认 Target 含依据与重议条件）→可观察结果→实现位置→真实浏览器和实际读取截图证据→实际结果映射；不得静默偏离，稳定偏差已同步活动 TRD。截图不替代动态交互、权限、失败恢复和持久化的真实验证。
- continue：当前环境仍可继续完成实现、测试、真实验证或审查时，给出明确的下一步指令。
- blocked：仅当缺少当前环境无法取得的不可替代外部条件时使用。"""


class DevelopmentBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        *,
        requirement_id: str,
        trd_path: str,
        development_session_id: str,
    ) -> None:
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.requirement_id = requirement_id
        self.trd_path = trd_path
        self.development_session_id = development_session_id


def result(
    status: str,
    summary: str,
    *,
    requirement_id: str | None = None,
    trd_path: str | None = None,
    development_session_id: str | None = None,
    blocked: dict[str, Any] | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": [],
        "blocked": blocked,
        "error": error,
        "requirement_id": requirement_id,
        "trd_path": trd_path,
        "development_session_id": development_session_id,
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


def _trd_file(workspace: Path, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError("活动 TRD 路径不符合约定")
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise RuntimeError("活动 TRD 路径不符合约定")
    target = workspace
    for part in relative.parts:
        target /= part
        if target.is_symlink():
            raise RuntimeError("活动 TRD 路径不能包含符号链接")
    try:
        target.resolve().relative_to(workspace)
    except ValueError as error:
        raise RuntimeError("活动 TRD 路径不符合约定") from error
    if not target.is_file() or target.is_symlink():
        raise RuntimeError("活动 TRD 必须是产品工作区内的普通文件")
    try:
        if not target.read_text(encoding="utf-8").strip():
            raise RuntimeError("活动 TRD 不能为空")
    except (OSError, UnicodeError) as error:
        raise RuntimeError("活动 TRD 不可读取") from error
    return value


def _session(state: dict[str, Any], key: str) -> str | None:
    sessions = state.get("claude_sessions")
    if sessions is None:
        return None
    if not isinstance(sessions, dict):
        raise RuntimeError("Claude session 状态不符合约定")
    value = sessions.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeError("Claude session ID 不符合约定")
    return value


def _context(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("phase") != PHASE or _position(state) not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于实现与验证锚点")

    workspace = _workspace_from_state(state)
    requirement_id = state.get("active_requirement")
    registry = state.get("requirement_registry")
    cycle = state.get("requirement_cycle")
    if (
        not is_valid_requirement_id(requirement_id)
        or not isinstance(registry, dict)
        or not isinstance(registry.get("requirements"), list)
        or not isinstance(cycle, dict)
        or cycle.get("requirement_id") != requirement_id
        or not isinstance(cycle.get("branch"), str)
        or not cycle["branch"]
    ):
        raise RuntimeError("活动需求上下文不符合约定")
    active = [
        item
        for item in registry["requirements"]
        if isinstance(item, dict) and item.get("status") == "active"
    ]
    if (
        len(active) != 1
        or active[0].get("id") != requirement_id
        or active[0].get("completion") is not None
        or not isinstance(active[0].get("title"), str)
        or not active[0]["title"].strip()
    ):
        raise RuntimeError("活动需求与需求注册表不一致")
    trd_path = _trd_file(workspace, cycle.get("trd_path"))
    saved = _read_json(
        requirement_step_result_path(run_dir, requirement_id, 14), "活动 TRD 结果不可读取"
    )
    if (
        saved.get("step") != 14
        or saved.get("status") != "success"
        or saved.get("requirement_id") != requirement_id
        or saved.get("branch") != cycle["branch"]
        or saved.get("trd_path") != trd_path
    ):
        raise RuntimeError("第 14 步没有当前活动需求的一致成功结果")

    key = f"development_{requirement_id}"
    recorded_session = cycle.get("development_session_id")
    if recorded_session is not None and (
        not isinstance(recorded_session, str)
        or not recorded_session
        or recorded_session != _session(state, key)
    ):
        raise RuntimeError("开发 session 与活动需求 cycle 不一致")
    return {
        "workspace": workspace,
        "requirement_id": requirement_id,
        "title": active[0]["title"],
        "trd_path": trd_path,
        "cycle": cycle,
        "key": key,
    }


def initial_prompt(context: dict[str, Any]) -> str:
    return f"""/dev-workflow
请实现并验证当前需求：`{context['requirement_id']} {context['title']}`。

活动 TRD：`{context['trd_path']}`

项目资料、代码、配置、测试和运行环境请按需自行读取。按活动 TRD 中适用的体验决定执行；不要求固定上游资料。必要的稳定设计偏差请同步至该 TRD。保留待提交变更；不得修改 `.claude/rules/`，不得 stage/commit、创建或切换分支、merge 或 push。"""


def _saved_result(run_dir: Path, requirement_id: str) -> dict[str, Any] | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    if not path.exists() and not path.is_symlink():
        return None
    return _read_json(path, "实现与验证结果不可读取")


def _sync_development_session(
    run_dir: Path, state: dict[str, Any], context: dict[str, Any]
) -> str | None:
    session_id = _session(state, context["key"])
    if session_id is None:
        return None
    recorded = context["cycle"].get("development_session_id")
    if recorded is None:
        context["cycle"]["development_session_id"] = session_id
        write_state(run_dir, state)
    elif recorded != session_id:
        raise RuntimeError("开发 session 与活动需求 cycle 不一致")
    return session_id


def _validate_success(
    saved: Any, state: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    session_id = _session(state, context["key"])
    if session_id is None or context["cycle"].get("development_session_id") != session_id:
        raise RuntimeError("实现与验证完整成功结果缺少一致的开发 session")
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
        "trd_path",
        "development_session_id",
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
        or saved.get("outputs") != []
        or saved.get("blocked") is not None
        or saved.get("error") is not None
        or saved.get("requirement_id") != context["requirement_id"]
        or saved.get("trd_path") != context["trd_path"]
        or saved.get("development_session_id") != session_id
    ):
        raise RuntimeError("实现与验证完整成功结果不符合约定")
    return saved


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
        _validate_success(saved, state, context)
    except (RuntimeError, ValueError, TypeError):
        return False
    return True


def failure_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, str | None] | None:
    try:
        context = _context(run_dir, state)
        session_id = _session(state, context["key"])
    except (RuntimeError, ValueError, TypeError):
        return None
    return {
        "requirement_id": context["requirement_id"],
        "trd_path": context["trd_path"],
        "development_session_id": session_id,
    }


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    context = _context(run_dir, state)
    saved = _saved_result(run_dir, context["requirement_id"])
    position = _position(state)

    if position == (STEP + 1, STEP + 1, NEXT_NODE):
        if (
            state.get("status") != "success"
            or state.get("blocked") is not None
            or state.get("error") is not None
        ):
            raise RuntimeError("实现与验证成功状态不符合约定")
        return _validate_success(saved, state, context)

    if saved is not None:
        try:
            complete = _validate_success(saved, state, context)
        except RuntimeError:
            pass
        else:
            return _advance(run_dir, state, complete)

    if state.get("status") != "blocked":
        state.update(
            {
                "status": "running",
                "phase": PHASE,
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": None,
                "error": None,
            }
        )
        write_state(run_dir, state)

    def synchronized_agent_runner(prompt: str, **kwargs: Any) -> Any:
        on_update = kwargs["on_update"]

        def synchronized_update(value: Any) -> None:
            on_update(value)
            _sync_development_session(run_dir, state, context)

        kwargs["on_update"] = synchronized_update
        return agent_runner(prompt, **kwargs)

    decision_spec = AgentDecisionLoopSpec(
        key=context["key"],
        state_key=context["key"],
        skill_name=SKILL_NAME,
        max_decision_rounds=MAX_DECISION_ROUNDS,
        max_turns=DEVELOPMENT_MAX_TURNS,
        decision_system_prompt=render_decision_system_prompt(
            DEVELOPMENT_DECISION_RULES,
            {
                "当前需求": {
                    "id": context["requirement_id"],
                    "title": context["title"],
                    "活动 TRD": context["trd_path"],
                }
            },
        ),
    )
    decision = await run_agent_decision_loop(
        run_dir,
        state,
        context["workspace"],
        decision_spec,
        initial_prompt(context),
        lambda: None,
        agent_runner=synchronized_agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
    )
    session_id = _sync_development_session(run_dir, state, context)
    if session_id is None:
        raise RuntimeError("实现与验证缺少开发 session")

    if decision.verdict == "blocked":
        blocked = {"reason": decision.reason, "required_inputs": decision.required_inputs}
        blocked_result = result(
            "blocked",
            decision.reason,
            requirement_id=context["requirement_id"],
            trd_path=context["trd_path"],
            development_session_id=session_id,
            blocked=blocked,
        )
        write_requirement_step_result(run_dir, context["requirement_id"], STEP, blocked_result)
        state.update(
            {
                "status": "blocked",
                "phase": PHASE,
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": blocked,
                "error": None,
            }
        )
        write_state(run_dir, state)
        raise DevelopmentBlocked(
            decision.reason,
            decision.required_inputs,
            requirement_id=context["requirement_id"],
            trd_path=context["trd_path"],
            development_session_id=session_id,
        )

    if decision.verdict != "completed":
        raise RuntimeError("实现与验证决策不符合约定")
    success = result(
        "success",
        "dev-workflow 已完成当前需求的实现与验证。",
        requirement_id=context["requirement_id"],
        trd_path=context["trd_path"],
        development_session_id=session_id,
    )
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, success)
