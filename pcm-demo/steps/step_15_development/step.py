from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, ResumeMessage, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.state import (
    is_valid_requirement_id,
    requirement_step_result_path,
    write_requirement_step_result,
    write_state,
)
from config import LLMConfig, load_dev_resource_list
from steps.step_05_project_readiness.step import resource_list_facts

STEP = 15
NAME = "实现与验证"
CURRENT_NODE = "requirement:15_development"
NEXT_NODE = "requirement:16_rule_retrospective"
PHASE = "phase_1_requirement_development"
SKILL_NAME = "dev-workflow"
MAX_DECISION_ROUNDS = 32
DEVELOPMENT_MAX_TURNS = 9999
READINESS_CHECKLIST = Path("docs/requirements/项目准备清单.md")

DEVELOPMENT_DECISION_RULES = """以当前需求的交付结果判断，而非要求每一种验证方法或观察周期全部完成。信任已报告的实现与有效证据，不重新审计未提出问题的部分，也不因缺少逐项完成声明而补问。
- completed：需求功能已实现，核心路径与适用关键风险已有可信证据，没有已知阻断缺陷或未决重大选择。允许保留非阻断的验证限制，并在 reason 中说明；不得仅因 Agent 自称“未完全验证”而拒绝完成。
- continue：仅针对有依据的必要功能缺失、真实阻断缺陷或关键证据缺口，且当前条件下可以继续时，给出最小必要的下一步；不扩大范围、不重复仍有效的验证。
Agent 自报未完成事项时，先区分必要交付缺口与自行追加的观察或方法要求。业务期限、冻结历史和真实性约束不等于必须在特定开发样本上等满整个业务周期；已由有效的边界测试、真实接口/数据库与适用浏览器证据覆盖的行为，不再因长期自然观察尚未结束而阻塞。不得篡改已有业务历史或冒充做过验证，也不得用非阻断限制掩盖关键失败。此前指令若不必要地收紧了验收方法，应明确纠正，而不是继续坚持。"""


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


def _trd_file(workspace: Path, value: Any) -> tuple[str, str]:
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
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError("活动 TRD 不可读取") from error
    if not content.strip():
        raise RuntimeError("活动 TRD 不能为空")
    return value, content


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
    trd_path, trd_content = _trd_file(workspace, cycle.get("trd_path"))
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
        "trd_content": trd_content,
        "cycle": cycle,
        "key": key,
    }


def _development_resource_facts(resource_loader: Any) -> dict[str, Any]:
    """只返回可信资源清单的位置与可读性事实。"""

    try:
        resource_list, _ = resource_loader()
    except (OSError, ValueError):
        return {"available": False}
    try:
        return resource_list_facts(resource_list)
    except RuntimeError:
        return {"available": False}


def initial_prompt(context: dict[str, Any], resource_facts: dict[str, Any]) -> str:
    if resource_facts.get("readable") is True:
        resource_reference = f"@{resource_facts['path']}"
    else:
        resource_reference = "当前配置不可用。"
    return f"""/dev-workflow
请实现并验证当前需求：`{context['requirement_id']} {context['title']}`。

权威活动 TRD：@./{context['trd_path']}
项目准备清单：@./{READINESS_CHECKLIST.as_posix()}
可信开发资源清单：{resource_reference}
项目资料、工程、代码、配置、测试和运行环境请按需读取。发现活动 TRD 的具体工程或验收方法缺少依据且成本显著时，保留正式结果并按影响同步校正，不机械执行或静默少做。保留待提交变更；不得修改 `.claude/rules/`，不得 stage/commit、创建或切换分支、merge 或 push。"""


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
    resource_loader=load_dev_resource_list,
    resume_message: ResumeMessage | None = None,
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

    resource_facts = _development_resource_facts(resource_loader)

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
        task="development",
        decision_system_prompt=render_decision_system_prompt(
            DEVELOPMENT_DECISION_RULES,
            {
                "当前需求": {
                    "id": context["requirement_id"],
                    "title": context["title"],
                },
                "活动 TRD": {
                    "path": context["trd_path"],
                    "content": context["trd_content"],
                },
                "项目准备清单": {"path": READINESS_CHECKLIST.as_posix()},
                "可信开发资源清单": resource_facts,
            },
        ),
    )
    decision = await run_agent_decision_loop(
        run_dir,
        state,
        context["workspace"],
        decision_spec,
        initial_prompt(context, resource_facts),
        lambda: None,
        agent_runner=synchronized_agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
        resume_message=resume_message,
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
