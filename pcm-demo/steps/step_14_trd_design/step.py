from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Callable

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.files import resolve_workspace_output
from common.state import (
    is_valid_requirement_id,
    requirement_step_result_path,
    write_requirement_step_result,
    write_state,
)
from config import LLMConfig

STEP = 14
NAME = "形成活动 TRD"
CURRENT_NODE = "requirement:14_trd_design"
NEXT_NODE = "requirement:15_development"
PHASE = "phase_1_requirement_development"
SKILL_NAME = "trd-design"
MAX_DECISION_ROUNDS = 8
TRD_DESIGN_MAX_TURNS = 48
TRD_DESIGN_MAX_BUDGET_USD = 16.0

_FORBIDDEN_TITLE_CHARACTERS = set('<>:"/\\|?*')

TRD_DESIGN_DECISION_RULES = """- completed：Agent 已将当前正式需求的活动 TRD 写入唯一指定路径，范围、关键行为、技术方案、验证场景和需求级体验设计已经收敛，且没有阻碍实现的未决事项。对本需求适用的体验决定已在 TRD 收敛：按需从任意来源发现已确认的 Target 或有依据的默认 Target，并记录来源、适用范围、经核验的 Current、Target 与本需求遵循或改变；默认 Target 已说明依据与重议条件，偏离已说明理由，不得静默偏离；跨需求骨架改变已有负责人决定。不适用时不得虚构或阻塞。
- continue：当前环境仍可继续补全活动 TRD或收敛会影响实现的产品与技术决定时，给出明确的下一步指令。
- blocked：仅当缺少当前环境无法取得的不可替代外部条件时使用。"""


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
    if not root.is_absolute() or not workspace.is_absolute():
        raise RuntimeError("工作区状态路径不符合约定")
    root = root.resolve()
    workspace = workspace.resolve()
    if workspace.parent != root or not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    return workspace


def _context(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("phase") != PHASE or _position(state) not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于活动 TRD 锚点")

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
    return {
        "workspace": workspace,
        "requirement_id": requirement_id,
        "title": active[0]["title"],
        "branch": cycle["branch"],
        "cycle": cycle,
        "key": f"trd_design_{requirement_id}",
    }


def _validate_title(title: str) -> None:
    if (
        title != title.strip()
        or title in {"", ".", ".."}
        or any(
            character in _FORBIDDEN_TITLE_CHARACTERS
            or ord(character) < 32
            or ord(character) == 127
            for character in title
        )
    ):
        raise RuntimeError("活动需求标题不能安全用于 TRD 文件名")


def _trd_target(workspace: Path, value: Any) -> tuple[str, Path]:
    if not isinstance(value, str):
        raise RuntimeError("活动 TRD 路径状态不符合约定")
    relative = Path(value)
    if relative.is_absolute() or relative.parts[:2] != ("docs", "trd") or len(relative.parts) != 3:
        raise RuntimeError("活动 TRD 路径状态不符合约定")
    try:
        target = resolve_workspace_output(workspace, value)
    except ValueError as error:
        raise RuntimeError("活动 TRD 路径状态不符合约定") from error
    return value, target


def _new_trd_path(context: dict[str, Any], today_provider: Callable[[], date]) -> str:
    _validate_title(context["title"])
    filename = f"{today_provider().isoformat()}-{context['requirement_id']}-{context['title']}.md"
    if len(filename.encode("utf-8")) > 240:
        raise RuntimeError("活动 TRD 文件名过长")
    value = (Path("docs/trd") / filename).as_posix()
    _, target = _trd_target(context["workspace"], value)
    if target.exists():
        raise RuntimeError("新鲜活动 TRD 目标路径已经存在")
    return value


def _document_ready(workspace: Path, trd_path: str) -> bool:
    _, target = _trd_target(workspace, trd_path)
    if not target.is_file():
        return False
    try:
        return bool(target.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        return False


def _repair_prompt(trd_path: str) -> str:
    return (
        f"指定活动 TRD 缺失或为空。请仅创建或补全 `{trd_path}`；"
        "不得修改任何其他文件，不得执行 Git 写操作，然后报告结果。"
    )


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


def initial_prompt(context: dict[str, Any], trd_path: str) -> str:
    return f"""/trd-design
请为正式需求 `{context['requirement_id']} {context['title']}` 形成可直接指导实现和验证的活动 TRD，并只写入：

`{trd_path}`

项目资料、正式 Backlog、实际代码、测试、接口、数据、权限、配置和运行约定请按需自行读取。请收敛当前需求的范围、关键行为、状态与恢复、技术职责、数据与接口语义、安全边界、实现约束、需求级体验设计和可执行验证场景。对本需求真正适用的体验决定，按需从任意来源发现已确认的 Target 或有依据的默认 Target，并在 TRD 记录来源、适用范围、经核验的 Current、Target，以及本需求遵循或改变；默认 Target 须写明依据与重议条件，偏离须说明理由，改变跨需求骨架须由负责人决定。没有适用决定时不得虚构或阻塞；不要求固定框架文档、固定资料来源或技术栈。

只允许创建或更新 `{trd_path}`。不得实现业务功能，不得修改代码、测试、配置、依赖、项目规则、Backlog 或其它文档，不得执行 Git 写操作，不得暂存、提交、合并、推送、切换或创建分支，不得处理或展示秘密。"""


def _saved_result(run_dir: Path, requirement_id: str) -> dict[str, Any] | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    if not path.exists() and not path.is_symlink():
        return None
    return _read_json(path, "活动 TRD 结果不可读取")


def _validate_success(saved: Any, context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    trd_path, _ = _trd_target(context["workspace"], context["cycle"].get("trd_path"))
    session_id = _session(state, context["key"])
    if (
        not isinstance(saved, dict)
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
        or session_id is None
        or saved.get("trd_session_id") != session_id
    ):
        raise RuntimeError("活动 TRD 完整成功结果不符合约定")
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
        context = _context(state)
        saved = _saved_result(run_dir, context["requirement_id"])
        _validate_success(saved, context, state)
    except (RuntimeError, ValueError, TypeError):
        return False
    return True


def failure_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, str | None] | None:
    try:
        context = _context(state)
        trd_path, _ = _trd_target(context["workspace"], context["cycle"].get("trd_path"))
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
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
    today_provider: Callable[[], date] = date.today,
) -> dict[str, Any]:
    context = _context(state)
    saved = _saved_result(run_dir, context["requirement_id"])
    position = _position(state)

    if position == (STEP + 1, STEP + 1, NEXT_NODE):
        if (
            state.get("status") != "success"
            or state.get("blocked") is not None
            or state.get("error") is not None
        ):
            raise RuntimeError("活动 TRD 成功状态不符合约定")
        return _validate_success(saved, context, state)

    trd_path_value = context["cycle"].get("trd_path")
    if trd_path_value is None:
        trd_path = _new_trd_path(context, today_provider)
        context["cycle"]["trd_path"] = trd_path
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
    else:
        trd_path, _ = _trd_target(context["workspace"], trd_path_value)

    if saved is not None:
        try:
            complete = _validate_success(saved, context, state)
        except RuntimeError:
            pass
        else:
            if not _document_ready(context["workspace"], trd_path):
                raise RuntimeError("活动 TRD 既有成功缺少非空文档")
            return _advance(run_dir, state, complete)

    _, target = _trd_target(context["workspace"], trd_path)
    target.parent.mkdir(parents=True, exist_ok=True)

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

    decision_spec = AgentDecisionLoopSpec(
        key=context["key"],
        state_key=context["key"],
        skill_name=SKILL_NAME,
        max_decision_rounds=MAX_DECISION_ROUNDS,
        max_turns=TRD_DESIGN_MAX_TURNS,
        max_budget_usd=TRD_DESIGN_MAX_BUDGET_USD,
        decision_system_prompt=render_decision_system_prompt(
            TRD_DESIGN_DECISION_RULES,
            {
                "当前需求": {
                    "id": context["requirement_id"],
                    "title": context["title"],
                    "活动 TRD": trd_path,
                }
            },
        ),
    )

    def completion_verifier() -> str | None:
        if _document_ready(context["workspace"], trd_path):
            return None
        return _repair_prompt(trd_path)

    decision = await run_agent_decision_loop(
        run_dir,
        state,
        context["workspace"],
        decision_spec,
        initial_prompt(context, trd_path),
        completion_verifier,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
    )
    session_id = _session(state, context["key"])
    if session_id is None:
        raise RuntimeError("活动 TRD 缺少 Claude session")

    if decision.verdict == "blocked":
        outputs = [trd_path] if _document_ready(context["workspace"], trd_path) else []
        blocked = {"reason": decision.reason, "required_inputs": decision.required_inputs}
        blocked_result = result(
            "blocked",
            decision.reason,
            requirement_id=context["requirement_id"],
            branch=context["branch"],
            trd_path=trd_path,
            trd_session_id=session_id,
            outputs=outputs,
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
        raise TRDDesignBlocked(
            decision.reason,
            decision.required_inputs,
            requirement_id=context["requirement_id"],
            branch=context["branch"],
            trd_path=trd_path,
            trd_session_id=session_id,
            outputs=outputs,
        )

    if decision.verdict != "completed" or not _document_ready(context["workspace"], trd_path):
        raise RuntimeError("活动 TRD 完成结果不符合约定")
    success = result(
        "success",
        "trd-design 已形成当前活动需求的技术设计。",
        requirement_id=context["requirement_id"],
        branch=context["branch"],
        trd_path=trd_path,
        trd_session_id=session_id,
        outputs=[trd_path],
    )
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, success)
