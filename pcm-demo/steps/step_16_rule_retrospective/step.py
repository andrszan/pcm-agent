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

STEP = 16
NAME = "规则复盘"
CURRENT_NODE = "requirement:16_rule_retrospective"
NEXT_NODE = "requirement:17_commit"
PHASE = "phase_1_requirement_development"
SKILL_NAME = "session-rule-retrospective"

RULE_RETROSPECTIVE_DECISION_RULES = """- completed：Agent 已明确完成规则复盘，允许有规则修改或 no-change，且没有剩余复盘工作。
- continue：当前环境仍可完成复盘时，给出明确的下一步指令。
- blocked：仅当缺少当前环境无法取得的不可替代外部资源时使用。"""


class RuleRetrospectiveBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        *,
        requirement_id: str,
        development_session_id: str,
    ) -> None:
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.requirement_id = requirement_id
        self.development_session_id = development_session_id


def result(
    status: str,
    summary: str,
    *,
    requirement_id: str | None = None,
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
        "development_session_id": development_session_id,
    }


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


def _read_json(path: Path, message: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(message) from error
    if not isinstance(value, dict):
        raise RuntimeError(message)
    return value


def _workspace_from_state(state: dict[str, Any], *, require_exists: bool) -> Path:
    try:
        root_value = state["workspace"]["root"]
        workspace_value = state["workspace"]["final_path"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    if not isinstance(root_value, str) or not isinstance(workspace_value, str):
        raise RuntimeError("工作区状态记录不完整")
    root = Path(root_value)
    workspace = Path(workspace_value)
    if not root.is_absolute() or not workspace.is_absolute() or workspace.parent != root:
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    if require_exists and not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    return workspace


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


def _context(state: dict[str, Any], *, require_workspace: bool = True) -> dict[str, Any]:
    if state.get("phase") != PHASE or _position(state) not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于规则复盘锚点")

    workspace = _workspace_from_state(state, require_exists=require_workspace)
    requirement_id = state.get("active_requirement")
    registry = state.get("requirement_registry")
    cycle = state.get("requirement_cycle")
    if (
        not is_valid_requirement_id(requirement_id)
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
    if (
        len(active) != 1
        or active[0].get("id") != requirement_id
        or active[0].get("completion") is not None
    ):
        raise RuntimeError("活动需求与需求注册表不一致")

    development_key = f"development_{requirement_id}"
    development_session_id = cycle.get("development_session_id")
    if (
        not isinstance(development_session_id, str)
        or not development_session_id
        or development_session_id != _session(state, development_key)
    ):
        raise RuntimeError("开发 session 与活动需求 cycle 不一致")
    return {
        "workspace": workspace,
        "requirement_id": requirement_id,
        "development_session_id": development_session_id,
        "key": f"rule_retrospective_{requirement_id}",
    }


def initial_prompt() -> str:
    return "/session-rule-retrospective 本次开发会话\n请基于本会话真实发生的开发、验证、修复和审查事实完成复盘；如无满足沉淀门槛的候选，不修改文件并明确报告。"


def _saved_result(run_dir: Path, requirement_id: str) -> dict[str, Any] | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    if not path.exists():
        return None
    return _read_json(path, "规则复盘结果不可读取")


def _validate_success(saved: Any, state: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if _session(state, context["key"]) != context["development_session_id"]:
        raise RuntimeError("规则复盘没有复用原开发 session")
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
        or saved.get("development_session_id") != context["development_session_id"]
    ):
        raise RuntimeError("规则复盘完整成功结果不符合约定")
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
        context = _context(state, require_workspace=False)
        saved = _saved_result(run_dir, context["requirement_id"])
        _validate_success(saved, state, context)
    except (RuntimeError, ValueError, TypeError):
        return False
    return True


def failure_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, str] | None:
    try:
        context = _context(state, require_workspace=False)
    except (RuntimeError, ValueError, TypeError):
        return None
    return {
        "requirement_id": context["requirement_id"],
        "development_session_id": context["development_session_id"],
    }


def _prepare_session(run_dir: Path, state: dict[str, Any], context: dict[str, Any]) -> None:
    sessions = state.get("claude_sessions")
    if not isinstance(sessions, dict):
        raise RuntimeError("Claude session 状态不符合约定")
    alias = sessions.get(context["key"])
    if alias not in {None, context["development_session_id"]}:
        raise RuntimeError("规则复盘恢复没有原开发 session 别名")
    if alias is None:
        sessions[context["key"]] = context["development_session_id"]
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


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    advanced = _position(state) == (STEP + 1, STEP + 1, NEXT_NODE)
    context = _context(state, require_workspace=not advanced)
    saved = _saved_result(run_dir, context["requirement_id"])

    if advanced:
        if (
            state.get("status") != "success"
            or state.get("blocked") is not None
            or state.get("error") is not None
        ):
            raise RuntimeError("规则复盘成功状态不符合约定")
        return _validate_success(saved, state, context)

    if saved is not None:
        try:
            complete = _validate_success(saved, state, context)
        except RuntimeError:
            pass
        else:
            return _advance(run_dir, state, complete)

    _prepare_session(run_dir, state, context)
    decision_spec = AgentDecisionLoopSpec(
        key=context["key"],
        state_key=context["key"],
        skill_name=SKILL_NAME,
        max_decision_rounds=8,
        max_turns=48,
        decision_system_prompt=render_decision_system_prompt(
            RULE_RETROSPECTIVE_DECISION_RULES, {}
        ),
    )
    decision = await run_agent_decision_loop(
        run_dir,
        state,
        context["workspace"],
        decision_spec,
        initial_prompt(),
        lambda: None,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
    )

    if decision.verdict == "blocked":
        blocked = {"reason": decision.reason, "required_inputs": decision.required_inputs}
        blocked_result = result(
            "blocked",
            decision.reason,
            requirement_id=context["requirement_id"],
            development_session_id=context["development_session_id"],
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
        raise RuleRetrospectiveBlocked(
            decision.reason,
            decision.required_inputs,
            requirement_id=context["requirement_id"],
            development_session_id=context["development_session_id"],
        )
    if decision.verdict != "completed":
        raise RuntimeError("规则复盘决策不符合约定")
    success = result(
        "success",
        "session-rule-retrospective 已完成本次开发会话的规则复盘。",
        requirement_id=context["requirement_id"],
        development_session_id=context["development_session_id"],
    )
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, success)
