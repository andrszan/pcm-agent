from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.agent_decision_loop import (
    AgentDecisionLoopSpec,
    ResumeMessage,
    agent_conversation_report,
    run_agent_decision_loop,
)
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.frontend_scope import (
    LegacyFrontendContractError,
    classify_frontend_scope,
    ensure_frontend_capabilities,
    validate_frontend_scope,
)
from common.requirement_context import phase_for
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


FRONTEND_DECISION_RULES = """当前任务只交付本需求的正式前端，不代表整个需求已经完成。信任 Agent 的有效交接，不读取截图重做审美验收，不要求逐项复述已报告的证据。
- completed：前端用户任务、相关状态及适用视口已实现并验证，已完成独立体验评审和必要精修，入口、真实／模拟数据边界及待接入内容已交接，没有阻断前端交付的缺陷。
- continue：仅补当前前端范围内可解决的必要缺口，不扩大到尚待实现的后端、数据库或真实持久化验收；既有有效证据不重复验证。
- blocked：确有无法自行解决的必要输入或重大范围决定；缺少尚待开发的后端不构成前端阻塞。"""


class DevelopmentBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        *,
        requirement_id: str,
        trd_path: str,
        development_session_id: str | None,
        frontend: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.requirement_id = requirement_id
        self.trd_path = trd_path
        self.development_session_id = development_session_id
        self.frontend = frontend


def result(
    status: str,
    summary: str,
    *,
    requirement_id: str | None = None,
    trd_path: str | None = None,
    development_session_id: str | None = None,
    frontend: dict[str, Any] | None = None,
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
        **({"frontend": frontend} if frontend is not None else {}),
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
    if state.get("phase") != phase_for(state) or _position(state) not in {
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
承接已有正式前端及其交接，以实际代码和当前活动 TRD 为准，完成剩余实现、后端规则、权限、数据、接口与真实集成。纯前端需求只完成必要集成和交付核验，不为形式增加后端代码。
保留已确定的设计成果，不为接线方便整页重做。涉及用户可见 UI/UX 调整时，实际调用 /frontend-ui-ux 与 /ui-ux-pro-max:ui-ux-pro-max，专业子任务同样收到实际调用要求；纯接口地址或数据映射修改不重跑设计。
复用仍有效的前端体验证据，只补受影响部分；通过真实接口、数据和适用浏览器任务验证接线、持久化及关键恢复，保留完整需求的环境、账号、审查和 README 交付责任。
原型 @./docs/prototype/index.html（如有）、体验框架 @./docs/ui-ux/framework.md 及项目资料、工程、代码、配置、测试和运行环境请按需读取。发现活动 TRD 的具体工程或验收方法缺少依据且成本显著时，保留正式结果并按影响同步校正，不机械执行或静默少做。保留待提交变更；不得修改 `.claude/rules/`，不得 stage/commit、创建或切换分支、merge 或 push。"""


def frontend_prompt(context: dict[str, Any]) -> str:
    return f"""/frontend-ui-ux
请在现有正式工程中实现当前需求的前端：`{context['requirement_id']} {context['title']}`。
实际调用 /ui-ux-pro-max:ui-ux-pro-max；委派专业子任务时同样传递完整入口及实际调用要求。
权威活动 TRD：@./{context['trd_path']}
按需读取既有原型 @./docs/prototype/index.html（如有）、体验框架 @./docs/ui-ux/framework.md、工程架构和真实前端，继承已有设计；没有早期原型时以当前真实前端为基线。
仅实现本需求所需的正式前端代码、测试、资产及必要开发说明，不创建第二套演示应用或提前展开其它业务页面。首次需要时在本需求范围内建立 Shell、路由、主题和共享组件，后续复用已有实现。
已有真实接口直接使用；缺失部分可集中采用可替换且语义一致的模拟数据访问。完成当前用户任务、相关状态、宽窄屏与实际滚动验证，独立体验评审及必要定向精修；不提前承担尚待开发的后端、数据库或真实持久化验收。
正常交接说明实际入口、实现行为、真实／模拟数据边界、实际验证及仍需接入的内容，不新增前端阶段报告；正式页面不出现模拟或待接入的过程文案。
可同步活动 TRD 的授权内稳定细化；原型只读，不改后端业务、需求生命周期或 `.claude/rules/`。保持当前需求分支及待提交变更，不得 stage/commit、创建或切换分支、merge 或 push。"""


def validate_existing_contract(run_dir: Path, state: dict[str, Any]) -> None:
    """当前旧开发现场只读拒绝；已经越过节点的历史记录不套用新合同。"""
    if state.get("current_node") != CURRENT_NODE:
        return
    requirement_id = state.get("active_requirement")
    if not is_valid_requirement_id(requirement_id):
        return
    key = f"development_{requirement_id}"
    section = state.get(key)
    conversation = run_dir / "conversations" / f"{key}.json"
    cycle = state.get("requirement_cycle")
    started = (
        any(isinstance(state.get(field), dict) and key in state[field]
            for field in ("claude_sessions", "decision_conversations"))
        or conversation.exists() or conversation.is_symlink()
        or (isinstance(cycle, dict) and cycle.get("development_session_id") is not None)
    )
    if started and (not isinstance(section, dict) or "frontend_applicability" not in section):
        raise LegacyFrontendContractError("当前开发现场缺少 frontend_applicability，请用原版本收口；新流程不会修改旧记录。")
    saved = _saved_result(run_dir, requirement_id)
    if saved is not None and saved.get("status") == "success" and "frontend" not in saved:
        raise LegacyFrontendContractError("当前开发 success 缺少 frontend 交接，请用原版本收口；新流程不会修改旧记录。")


def _frontend_result(state: dict[str, Any], requirement_id: str) -> dict[str, Any] | None:
    section = state.get(f"development_{requirement_id}")
    if not isinstance(section, dict) or "frontend_applicability" not in section:
        return None
    scope = validate_frontend_scope(section["frontend_applicability"])
    session_id = _session(state, f"frontend_ui_ux_{requirement_id}")
    if not scope["applicable"] and session_id is not None:
        raise RuntimeError("不适用前端的需求不能包含前端 session")
    return {**scope, "session_id": session_id}


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
    if _position(state) == (STEP, STEP, CURRENT_NODE):
        expected_keys.add("frontend")
        frontend = _frontend_result(state, context["requirement_id"])
        if (
            frontend is None
            or (frontend["applicable"] and not frontend["session_id"])
            or frontend["session_id"] == session_id
            or not isinstance(saved, dict)
            or not isinstance(saved.get("frontend"), dict)
        ):
            raise RuntimeError("实现与验证成功结果缺少一致的前端交接")
        recorded_frontend = saved["frontend"]
        if set(recorded_frontend) != {"applicable", "reason", "session_id"}:
            raise RuntimeError("实现与验证前端交接不符合约定")
        validate_frontend_scope({key: recorded_frontend[key] for key in ("applicable", "reason")})
        if recorded_frontend != frontend:
            raise RuntimeError("实现与验证前端交接与已保存适用性或 session 不一致")
    elif isinstance(saved, dict) and "frontend" in saved:
        expected_keys.add("frontend")
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
            "phase": phase_for(state),
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


def failure_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    try:
        context = _context(run_dir, state)
        session_id = _session(state, context["key"])
    except (RuntimeError, ValueError, TypeError):
        return None
    scope = {
        "requirement_id": context["requirement_id"],
        "trd_path": context["trd_path"],
        "development_session_id": session_id,
    }
    try:
        frontend = _frontend_result(state, context["requirement_id"])
    except (RuntimeError, ValueError, TypeError):
        frontend = None
    if frontend is not None:
        scope["frontend"] = frontend
    return scope


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
    validate_existing_contract(run_dir, state)
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

    section = state.get(context["key"], {})
    if not isinstance(section, dict):
        raise RuntimeError("开发运行状态不符合约定")
    if "frontend_applicability" in section:
        applicability = validate_frontend_scope(section["frontend_applicability"])
    else:
        applicability = validate_frontend_scope(await classify_frontend_scope(
            config_loader(), purpose="requirement",
            context=json.dumps({
                "当前需求": {"id": context["requirement_id"], "title": context["title"]},
                "活动 TRD": {"path": context["trd_path"], "content": context["trd_content"]},
            }, ensure_ascii=False),
        ))
        state.setdefault(context["key"], {})["frontend_applicability"] = applicability
        write_state(run_dir, state)
    if applicability["applicable"]:
        repositories = state.get("applicable_repositories")
        frontend_path = context["workspace"] / "frontend"
        if (
            not isinstance(repositories, list) or "frontend" not in repositories
            or not frontend_path.is_dir() or frontend_path.is_symlink()
        ):
            raise RuntimeError("需求需要前端，但当前权威工程缺少 frontend 交付单元")
        ensure_frontend_capabilities(context["workspace"])

    resource_facts = _development_resource_facts(resource_loader)

    if state.get("status") != "blocked":
        state.update(
            {
                "status": "running",
                "phase": phase_for(state),
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

    quality_input = ""
    if state.get("workflow") == "product_quality":
        from quality.workflow import requirement_evidence

        quality_input = requirement_evidence(run_dir, state)
        if quality_input:
            quality_input += "\n各需求验证自己的交付结果；regression owner 在必要前置项完成后，由开发 Agent 完成完整原场景回归并报告真实证据。"
    feedback_input = ""
    if state.get("workflow") == "product_feedback":
        from feedback.workflow import requirement_evidence

        feedback_input = requirement_evidence(run_dir, state)
    handoff = ""
    domains = (["frontend"] if applicability["applicable"] else []) + ["development"]
    for domain in domains:
        is_frontend = domain == "frontend"
        key = f"frontend_ui_ux_{context['requirement_id']}" if is_frontend else context["key"]
        # 前端可以授权内细化 TRD，进入集成时读取当前有效正文。
        _, context["trd_content"] = _trd_file(context["workspace"], context["trd_path"])
        decision_spec = AgentDecisionLoopSpec(
            key=key,
            state_key=key,
            skill_name="frontend-ui-ux" if is_frontend else SKILL_NAME,
            max_decision_rounds=MAX_DECISION_ROUNDS,
            max_turns=DEVELOPMENT_MAX_TURNS,
            task="development",
            decision_system_prompt=render_decision_system_prompt(
                FRONTEND_DECISION_RULES if is_frontend else DEVELOPMENT_DECISION_RULES,
                {
                    **({"质量原发现与回归归属": quality_input} if quality_input else {}),
                    **({"当前需求相关原反馈与采纳目标": feedback_input} if feedback_input else {}),
                    "当前需求": {"id": context["requirement_id"], "title": context["title"]},
                    "活动 TRD": {"path": context["trd_path"], "content": context["trd_content"]},
                    "项目准备清单": {"path": READINESS_CHECKLIST.as_posix()},
                    "可信开发资源清单": resource_facts,
                    **({"前端有效交接": handoff} if handoff else {}),
                },
            ),
        )
        prompt = frontend_prompt(context) if is_frontend else initial_prompt(context, resource_facts)
        decision = await run_agent_decision_loop(
            run_dir, state, context["workspace"], decision_spec,
            prompt + ("\n\n" + quality_input if quality_input else "")
            + ("\n\n" + feedback_input if feedback_input else "")
            + ("\n\n前端有效交接：\n" + handoff if handoff else ""),
            lambda: None,
            agent_runner=agent_runner if is_frontend else synchronized_agent_runner,
            decision_runner=decision_runner,
            config_loader=config_loader,
            resume_message=resume_message,
        )
        if _session(state, key) is None:
            raise RuntimeError("实现与验证缺少当前领域 session")
        session_id = _session(state, context["key"]) if is_frontend else _sync_development_session(run_dir, state, context)
        frontend = _frontend_result(state, context["requirement_id"])
        if decision.verdict == "blocked":
            blocked = {"reason": decision.reason, "required_inputs": decision.required_inputs}
            blocked_result = result(
                "blocked", decision.reason,
                requirement_id=context["requirement_id"], trd_path=context["trd_path"],
                development_session_id=session_id, frontend=frontend, blocked=blocked,
            )
            write_requirement_step_result(run_dir, context["requirement_id"], STEP, blocked_result)
            state.update({
                "status": "blocked", "phase": phase_for(state), "step": STEP,
                "current_step": STEP, "current_node": CURRENT_NODE,
                "blocked": blocked, "error": None,
            })
            write_state(run_dir, state)
            raise DevelopmentBlocked(
                decision.reason, decision.required_inputs,
                requirement_id=context["requirement_id"], trd_path=context["trd_path"],
                development_session_id=session_id, frontend=frontend,
            )
        if decision.verdict != "completed":
            raise RuntimeError("实现与验证决策不符合约定")
        if is_frontend:
            handoff = agent_conversation_report(
                run_dir, state, decision_spec, include_initial_context=False,
            )
            if state.get("status") == "blocked" and _session(state, context["key"]) is None:
                # 已解决的是前端阻塞，不能让新后端继承；已有后端阻塞仍由原循环恢复。
                state.update({"status": "running", "blocked": None, "error": None})
                write_state(run_dir, state)

    success = result(
        "success",
        "前端已完成或不适用，dev-workflow 已完成当前需求的实现与验证。",
        requirement_id=context["requirement_id"],
        trd_path=context["trd_path"],
        development_session_id=session_id,
        frontend=frontend,
    )
    _validate_success(success, state, context)
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, success)
