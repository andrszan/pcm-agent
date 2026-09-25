from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from common.agent_decision_loop import (
    AgentDecisionLoopSpec, ResumeMessage, agent_conversation_report, run_agent_decision_loop,
)
from common.decision import render_decision_system_prompt
from common.error_diagnostics import redact_text
from common.files import resolve_workspace_output, write_json
from common.openai_responses import parse_response
from common.state import write_state
from config import LLMConfig
from quality.git import (
    ancestor, branch_tip, changed_paths, check_operations, clean_repository, git,
    main_versions, repositories, validate_document_path, workspace,
)
from quality.models import (
    AuditReport, ExtractionInput, PoolPlan, RoutingReport, validate_audit, validate_pool_plan, validate_routing,
)

WORKFLOW = "product_quality"
PHASE = "product_quality_iteration"
NODES = ("prepare", "audit", "route", "pool", "register", "select_requirement", "complete", "completed")
_ROUND_NODES = {"audit", "route", "pool", "register", "select_requirement"}


class IterationLimit(RuntimeError):
    pass


class QualityBlocked(RuntimeError):
    def __init__(self, reason: str, required_inputs: list[str]):
        self.required_inputs = required_inputs
        super().__init__(reason)


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, value)


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"质量交接文件不存在或类型不合法：{path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("质量交接文件必须是对象")
    return value


def _path(run_dir: Path, relative: str) -> Path:
    path = run_dir / relative
    if not path.is_relative_to(run_dir) or ".." in Path(relative).parts:
        raise RuntimeError("质量结果路径越界")
    for current in (path, *path.parents):
        if current == run_dir.parent:
            break
        if current.is_symlink():
            raise RuntimeError("质量运行记录路径不能是符号链接")
    return path


def _round(state: dict[str, Any]) -> int:
    value = state.get("quality", {}).get("round")
    if type(value) is not int or value < 1:
        raise RuntimeError("质量审计轮次无效")
    return value


def _node(state: dict[str, Any]) -> str:
    if state.get("workflow") != WORKFLOW or state.get("phase") != PHASE:
        raise RuntimeError("当前不是产品质量工作流")
    value = state.get("current_node")
    if value not in {f"quality:{name}" for name in NODES}:
        raise RuntimeError("当前不是可执行质量节点")
    return str(value).split(":", 1)[1]


def node_result_path(run_dir: Path, state: dict[str, Any]) -> Path:
    name = _node(state)
    if name == "completed":
        name = "complete"
    relative = f"quality/rounds/{_round(state):04d}/{name}.json" if name in _ROUND_NODES else f"quality/{name}.json"
    return _path(run_dir, relative)


def _round_path(run_dir: Path, state: dict[str, Any], name: str) -> Path:
    if name not in {"audit", "route", "pool", "register", "pool-intent", "pool-plan", "audit-intent"}:
        raise RuntimeError("未知质量产物")
    return _path(run_dir, f"quality/rounds/{_round(state):04d}/{name}.json")


def _prior(run_dir: Path, state: dict[str, Any], name: str) -> dict[str, Any]:
    value = _read(_round_path(run_dir, state, name))
    if value.get("status") != "success" or value.get("node") != f"quality:{name}" or value.get("round") != _round(state):
        raise RuntimeError(f"缺少当前轮次成功的 {name} 交接")
    return value["data"]


def is_completed(state: dict[str, Any]) -> bool:
    registry = state.get("requirement_registry", {}).get("requirements", [])
    return (
        state.get("workflow") == WORKFLOW and state.get("phase") == PHASE
        and state.get("current_node") == "quality:completed" and state.get("status") == "success"
        and state.get("active_requirement") is None and state.get("requirement_cycle") is None
        and state.get("blocked") is None and state.get("error") is None
        and bool(registry) and all(row.get("status") == "completed" for row in registry)
    )


def new_state(source_state: dict[str, Any], source_run_id: str, run_id: str, max_rounds: int = 3) -> dict[str, Any]:
    from run_all import phase_one_completed
    if not (phase_one_completed(source_state) or is_completed(source_state)):
        raise RuntimeError("来源运行尚未完成或仍有活动需求")
    if source_run_id == run_id or any(not value or Path(value).name != value or value in {".", ".."} for value in (source_run_id, run_id)):
        raise ValueError("来源与新的运行标识必须是不同的安全名称")
    if type(max_rounds) is not int or max_rounds < 1:
        raise ValueError("max-rounds 必须是正整数")
    repositories(source_state)
    return {
        "run_id": run_id, "workflow": WORKFLOW, "source_run_id": source_run_id,
        "phase": PHASE, "current_node": "quality:prepare", "step": None, "current_step": None,
        "status": "success", "blocked": None, "error": None,
        "workspace": copy.deepcopy(source_state["workspace"]),
        "applicable_repositories": copy.deepcopy(source_state["applicable_repositories"]),
        "repositories": copy.deepcopy(source_state["repositories"]),
        "requirement_registry": copy.deepcopy(source_state["requirement_registry"]),
        "active_requirement": None, "requirement_cycle": None,
        "quality": {
            "round": 1, "max_rounds": max_rounds, "entry_versions": {},
            "baseline_requirement_ids": [row["id"] for row in source_state["requirement_registry"]["requirements"]],
            "batch_requirement_ids": [],
        },
    }


def increase_round_limit(state: dict[str, Any], new_limit: int) -> None:
    if (
        _node(state) != "audit" or state.get("status") != "failed"
        or state.get("error", {}).get("type") != "iteration_limit"
        or type(new_limit) is not int or new_limit <= state["quality"]["max_rounds"]
    ):
        raise ValueError("只能在轮次预算耗尽的失败位置显式提高 max-rounds")
    state["quality"]["max_rounds"] = new_limit


def node_resume_keys(state: dict[str, Any]) -> tuple[str, ...]:
    node = _node(state)
    if node == "prepare":
        return ("quality_prepare",)
    suffix = f"r{_round(state):04d}"
    if node == "audit":
        return (f"quality_{node}_{suffix}",)
    if node == "pool":
        return (f"quality_pool_{suffix}", f"quality_pool_design_{suffix}", f"quality_pool_commit_{suffix}")
    return ()


def _replace_state(run_dir: Path, state: dict[str, Any], replacement: dict[str, Any]) -> None:
    write_state(run_dir, replacement)
    state.clear()
    state.update(replacement)


def _advance(run_dir: Path, state: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    node = saved["node"].split(":", 1)[1]
    following = {"prepare": "audit", "audit": "route", "pool": "register", "register": "select_requirement", "complete": "completed"}
    data = saved["data"]
    updated = copy.deepcopy(state)
    if node == "prepare":
        updated["requirement_registry"] = data["registry"]
        updated["quality"]["entry_versions"] = data["versions"]
    elif node == "route":
        following[node] = "pool" if any(row["action"] == "include" for row in data["decisions"]) else "complete"
    elif node == "register":
        updated["requirement_registry"] = data["registry"]
        updated["quality"]["batch_requirement_ids"] = data["new_ids"]
    elif node == "select_requirement":
        following[node] = data["next_node"]
        if data["next_node"] == "audit":
            updated["quality"]["round"] = data["next_round"]
            updated["quality"]["batch_requirement_ids"] = []
    updated.update({"status": "success", "blocked": None, "error": None,
                    "current_node": f"quality:{following[node]}", "step": None, "current_step": None})
    if node == "select_requirement" and data["next_node"] == "select_requirement":
        updated.update({"step": 13, "current_step": 13})
    _replace_state(run_dir, state, updated)
    return saved


def _success(run_dir: Path, state: dict[str, Any], data: dict[str, Any], summary: str) -> dict[str, Any]:
    value = {"phase": PHASE, "node": state["current_node"], "round": _round(state),
             "status": "success", "summary": summary, "outputs": [], "blocked": None, "error": None, "data": data}
    _write(node_result_path(run_dir, state), value)
    return _advance(run_dir, state, value)


def record_failure(run_dir: Path, state: dict[str, Any], error: Exception) -> dict[str, Any]:
    path = node_result_path(run_dir, state)
    if path.exists():
        previous = _read(path)
        if previous.get("status") == "success" and _node(state) != "select_requirement":
            return previous
    message = redact_text(str(error))
    blocked = {"reason": message, "required_inputs": error.required_inputs} if isinstance(error, QualityBlocked) else None
    details = error.as_error() if hasattr(error, "as_error") else {"type": "iteration_limit" if isinstance(error, IterationLimit) else type(error).__name__, "message": message}
    status = "blocked" if blocked else "failed"
    value = {"phase": PHASE, "node": state["current_node"], "round": _round(state), "status": status,
             "summary": message, "outputs": [], "blocked": blocked, "error": None if blocked else details}
    _write(path, value)
    updated = copy.deepcopy(state)
    updated.update({key: value[key] for key in ("status", "blocked", "error")})
    _replace_state(run_dir, state, updated)
    return value


def _backlog(state: dict[str, Any]) -> tuple[Path, str, dict[str, str]]:
    relative = state["requirement_registry"]["source"]["path"]
    path = resolve_workspace_output(workspace(state), relative)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("当前正式 Backlog 不可读取")
    data = path.read_bytes()
    text = data.decode("utf-8")
    if not text.strip():
        raise RuntimeError("当前正式 Backlog 为空")
    return path, text, {"path": relative, "sha256": hashlib.sha256(data).hexdigest()}


async def _catalog(state: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    from common.requirement_registry import extract_requirements, validate_catalog
    path, text, source = _backlog(state)
    parsed = await extract_requirements(text, LLMConfig.load())
    try:
        catalog = validate_catalog(parsed)
    except RuntimeError as error:
        raise ValueError(str(error)) from error
    if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise RuntimeError("Backlog 在提取期间发生变化")
    return source, catalog


async def _task(
    run_dir: Path, state: dict[str, Any], key: str, task: str, prompt: str, responsibility: str,
    *, skill: str | None = None, output_model: type[BaseModel] | None = None,
    validate: Callable[[Any], Awaitable[None] | None] | None = None, resume_message: ResumeMessage | None = None,
    completion_verifier: Callable[[], str | None] | None = None,
) -> tuple[str, Any]:
    spec = AgentDecisionLoopSpec(
        key=key, state_key=key, skill_name=skill, max_decision_rounds=32, max_turns=9999, task=task,
        decision_system_prompt=render_decision_system_prompt(responsibility, {"当前任务": prompt}),
    )
    raw = ""
    parsed = None

    async def verify() -> str | None:
        nonlocal raw, parsed
        if completion_verifier:
            repair = completion_verifier()
            if repair:
                return repair
        raw = agent_conversation_report(run_dir, state, spec)
        if output_model:
            try:
                parsed = await parse_response(
                    LLMConfig.load(),
                    system_prompt=("依据完整有序对话提取当前有效的完整成果，返回严格 JSON。不得补造事实或替执行者决策。"
                                   "report 是对话消息：user 是执行 Agent，assistant 是负责人指令或决定，system 是任务约束。"
                                   "后续明确纠正替代对应旧事实；局部补充不删除其它有效发现、覆盖和限制。"
                                   "不要把最后一条补证当成整份报告，也不要把历史已撤销的误判重新纳入。"
                                   "任务明确要求但完整对话中没有执行证据的主要任务记 gap；运行版本核验不代替业务任务覆盖。"
                                   "保留明确的证据、限制和归属。coverage.blocking_findings 使用本次 findings 数组的从零开始索引。"
                                   "coverage只记录当前正式范围内的主要用户任务；明确不适用的能力与非阻断观察限制分别保留，不要升级为必要gap。"
                                   "只有明确尚未完成的必要任务或必要证据才记gap，不得为满足结构而补造覆盖或证据。"),
                    input_model=ExtractionInput(report=raw, context=prompt), output_model=output_model,
                )
                if validate:
                    checked = validate(parsed)
                    if inspect.isawaitable(checked):
                        await checked
            except (ValueError, ValidationError) as error:
                return f"当前结果交接存在具体缺口：{redact_text(str(error))}。请只补齐或纠正该缺口，保留已完成工作，不重做无关验收。"
        return None

    decision = await run_agent_decision_loop(
        run_dir, state, workspace(state), spec, prompt, verify, resume_message=resume_message,
    )
    if decision.verdict == "blocked":
        raise QualityBlocked(decision.reason, decision.required_inputs)
    if decision.verdict != "completed":
        raise RuntimeError("领域任务未完成")
    return raw, parsed


async def _prepare(run_dir: Path, state: dict[str, Any], message: ResumeMessage | None) -> dict[str, Any]:
    if not state["quality"]["entry_versions"]:
        versions = main_versions(state)
        source, catalog = await _catalog(state)
        historical = {row["id"]: row for row in state["requirement_registry"]["requirements"]}
        if {row["id"] for row in catalog} != set(historical):
            raise RuntimeError("当前正式 ID 与来源完成记录不一致，不能猜测未知需求的完成状态")
        registry = {"schema_version": 1, "source": source, "requirements": [
            {**row, "status": historical[row["id"]]["status"], "completion": historical[row["id"]]["completion"]}
            for row in catalog
        ]}
        updated = copy.deepcopy(state)
        updated["requirement_registry"] = registry
        updated["quality"]["entry_versions"] = versions
        _replace_state(run_dir, state, updated)
    prompt = (
        "为当前完整产品准备真实用户任务审计。读取当前产品定义、正式 Backlog、相关设计、代码、运行说明与 .pcm/runtime.json，"
        "明确主要用户任务、角色、目标视口、可访问环境、可复位非敏感数据和允许的操作边界。"
        "区分当前承诺与历史文件标题，不从旧标题恢复已取消功能，也不以当前实现静默缩减承诺。"
        "在授权范围内启动归属清楚的既有服务、准备必要测试数据；复用资源和端口，不重置环境、真实外发或执行高影响删除。"
        "不改业务代码、受跟踪配置、产品文档或 Git；如必须修代码才能准备现场，准确报告失败和具体解除条件。"
        "完成后直接返回完整审计范围与运行条件，包含适用性、允许操作、入口、角色使用方法和限制，不输出密码或外部凭据。"
        f"\n当前正式 Backlog：{state['requirement_registry']['source']['path']}"
    )
    raw, _ = await _task(run_dir, state, "quality_prepare", "quality_prepare", prompt,
                         "运行条件可用、当前主要任务和操作边界清楚时完成。信任已完成的核实，不要求逐项复述。不可替代外部条件缺失才 blocked。",
                         resume_message=message)
    if main_versions(state) != state["quality"]["entry_versions"]:
        raise RuntimeError("准备任务改变了受跟踪产品版本，保留现场")
    return _success(run_dir, state, {"report": raw, "versions": state["quality"]["entry_versions"],
                                    "registry": state["requirement_registry"]}, "已接入当前产品并准备审计范围")


def _history(run_dir: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    history = []
    for number in range(1, _round(state)):
        route = _read(_path(run_dir, f"quality/rounds/{number:04d}/route.json"))
        audit = _read(_path(run_dir, f"quality/rounds/{number:04d}/audit.json"))
        history.append({"round": number, "candidates": audit["data"]["candidates"], "routing": route["data"]})
    return history


async def _audit(run_dir: Path, state: dict[str, Any], message: ResumeMessage | None) -> dict[str, Any]:
    if _round(state) > state["quality"]["max_rounds"]:
        raise IterationLimit("完整审计轮次预算耗尽；已完成修复不等于质量收口，可提高 max-rounds 后恢复本轮")
    intent_path = _round_path(run_dir, state, "audit-intent")
    versions = main_versions(state)
    if intent_path.exists():
        if _read(intent_path)["versions"] != versions:
            raise RuntimeError("本轮审计版本发生变化，不能复用旧证据")
    else:
        _write(intent_path, {"versions": versions})
    prepared = _read(_path(run_dir, "quality/prepare.json"))["data"]
    context = {"运行条件和任务": prepared["report"], "版本": versions, "以前处置": _history(run_dir, state)}
    prompt = (
        "/product-experience-audit\n对当前完整产品执行全部主要用户任务的独立审计，按真实交付面完成动态验证。"
        "具有图形界面时实际读取代表性截图；纯CLI使用实际命令、输出、退出码和持久化结果，不能机械要求桌面截图或屏幕采集权限。"
        "不改产品代码、配置、文档、Backlog 或 Git，不直接修复。当前定义与历史标题不同时查明当前承诺。"
        "已复现缺陷阻断后续任务时，保留具体受阻任务与阻断发现的对应关系，完成其余可执行覆盖后交接修复；"
        "环境、身份或必要证据缺口先在授权内补齐，无法补齐如实报告，不假装覆盖。"
        "以前不纳入项只在新证据或前提变化时重议；历史需求 completed 不能证明当前缺陷已解决。"
        "最终直接返回完整任务覆盖（包括实际证据、不适用与缺陷阻断）、每个经核验发现的用户任务、触发条件、当前事实、"
        "预期结果及依据、影响、证据、优先级、信心，以及重复项、高影响事项和限制。不给正式需求 ID。\n"
        + json.dumps(context, ensure_ascii=False)
    )
    raw, report = await _task(run_dir, state, f"quality_audit_r{_round(state):04d}", "quality_audit", prompt,
                             "基于完整多轮对话判断调查与交接是否完成，局部补证不撤销原报告。可在现有授权内补齐的必要任务，明确具体任务后继续；不可替代外部资源缺失且无法推进时如实 blocked。已核验产品缺陷可以带覆盖限制交接修复，调查完成不等于产品通过，不索取重复完成声明。",
                             skill="product-experience-audit", output_model=AuditReport, validate=validate_audit, resume_message=message)
    if main_versions(state) != versions:
        raise RuntimeError("审计期间产品版本或 Git 状态发生变化")
    candidates = [{"id": f"Q{_round(state):03d}-C{index + 1:03d}", **finding.model_dump()} for index, finding in enumerate(report.findings)]
    coverage = []
    for row in report.coverage:
        value = row.model_dump()
        value["blocking_candidates"] = [candidates[i]["id"] for i in value.pop("blocking_findings")]
        coverage.append(value)
    data = {**report.model_dump(exclude={"findings", "coverage"}), "candidates": candidates,
            "coverage": coverage, "versions": versions, "report": raw}
    return _success(run_dir, state, data, "完整产品审计已交接，尚不代表产品通过")


async def _route(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    audit = _prior(run_dir, state, "audit")
    requirements = state["requirement_registry"]["requirements"]
    prompt = (
        "你是产品质量负责人，只依据已完成的完整审计材料决定处理范围，不执行新的产品调查。"
        "审计 report 是多轮交接：后续明确纠正覆盖对应旧事实，局部补证不删除其它有效发现。"
        "对 candidates 中每个 ID 恰好给出一个 include、covered 或 exclude；不得新增候选或伪造补证。"
        "include 用于当前值得修复的真实障碍；covered 只指同轮候选或未完成正式需求，不能指已完成历史；"
        "exclude 必须说明误判、非阻断偏好或范围外机会的具体依据，不得掩盖已复现阻断缺陷。"
        "优先合并、删除、调整默认值或复用，不将优化机会自动变成新产品目标。"
        "证据存在无法据此决定的矛盾时不要猜测；summary 说明缺失事实，不能宣称完成调查。"
        "确需校正当前设计时仅列 docs 内 Markdown 路径及理由，不修改历史 TRD。"
        "有 include 时继续正式修复；必要覆盖缺口仍须保留并在复审处理，不能最终收口。"
        "没有 include 且主要任务覆盖充分、没有必要缺口或活动需求时 ready_to_complete 才为 true。"
        "无可推进修复且必要缺口确需不可替代的外部资源时，required_inputs 列出具体资源和解除条件；"
        "不得把普通取舍、本地错误、范围外观察或没有自述完成当成外部阻塞。"
        "材料不足而又不属于外部资源缺失时令 ready_to_complete=false，并在 summary 准确说明原因。"
    )
    report = await parse_response(
        LLMConfig.load(), system_prompt=prompt,
        input_model=ExtractionInput(
            report=audit["report"],
            context=json.dumps({"审计": {k: v for k, v in audit.items() if k != "report"},
                                "已有需求": requirements, "以前处置": _history(run_dir, state)}, ensure_ascii=False),
        ),
        output_model=RoutingReport,
    )
    validate_routing(report, audit, requirements)
    for change in report.document_changes:
        validate_document_path(change.path)
    if not any(row.action == "include" for row in report.decisions) and report.required_inputs:
        raise QualityBlocked(report.summary, report.required_inputs)
    raw = report.model_dump_json()

    if main_versions(state) != audit["versions"]:
        raise RuntimeError("分流期间产品版本发生变化")
    return _success(run_dir, state, {**report.model_dump(), "report": raw}, "候选分流完成")


def _pool_boundary(state: dict[str, Any], intent: dict[str, Any], *, clean: bool = False) -> None:
    root = workspace(state)
    check_operations(root)
    if git(root, "branch", "--show-current") != intent["branch"]:
        raise RuntimeError("入池不在已记录分支")
    if branch_tip(root, "main") != intent["base"] or not ancestor(root, intent["base"], str(git(root, "rev-parse", "HEAD"))):
        raise RuntimeError("入池分支或 main 与本轮基线冲突")
    if not changed_paths(root, intent["base"]) <= set(intent["allowed_paths"]):
        raise RuntimeError("入池存在范围外变更，保留现场")
    for name, path in repositories(state)[1:]:
        if clean_repository(path, "main") != intent["versions"][name]:
            raise RuntimeError("入池改变了代码仓库")
    if clean:
        clean_repository(root, intent["branch"])


def _validate_increment(state: dict[str, Any], catalog: list[dict[str, Any]], plan: PoolPlan) -> None:
    historical = state["requirement_registry"]["requirements"]
    previous = {row["id"]: {key: row[key] for key in ("id", "title", "order", "depends_on")} for row in historical}
    current = {row["id"]: row for row in catalog}
    new_ids = {row.requirement_id for row in plan.requirements}
    if set(current) != set(previous) | new_ids or any(current.get(key) != value for key, value in previous.items()):
        raise ValueError("入池静态需求与本批新增集合不一致，或修改了既有需求")
    bindings = {row.requirement_id: set(row.candidate_ids) for row in plan.requirements}
    for ownership in plan.regression_owners:
        needed = {identifier for identifier, candidates in bindings.items() if ownership.candidate_id in candidates} - {ownership.requirement_id}
        reachable: set[str] = set()
        pending = list(current[ownership.requirement_id]["depends_on"])
        while pending:
            identifier = pending.pop()
            if identifier not in reachable:
                reachable.add(identifier)
                pending.extend(current[identifier]["depends_on"])
        if not needed <= reachable:
            raise ValueError("完整原场景回归需求缺少其它承接项的必要依赖")


async def _pool(run_dir: Path, state: dict[str, Any], message: ResumeMessage | None) -> dict[str, Any]:
    root = workspace(state)
    routing = _prior(run_dir, state, "route")
    audit = _prior(run_dir, state, "audit")
    included = [row for row in routing["decisions"] if row["action"] == "include"]
    if not included:
        raise RuntimeError("没有纳入项，不应进入入池节点")
    intent_path = _round_path(run_dir, state, "pool-intent")
    plan_path = _round_path(run_dir, state, "pool-plan")
    if not intent_path.exists():
        versions = main_versions(state)
        if versions != audit["versions"]:
            raise RuntimeError("入池开始版本与审计不一致")
        branch = f"quality/{run_dir.name}/r{_round(state):03d}-pool"
        if branch_tip(root, branch) is not None:
            raise RuntimeError("入池目标分支已存在但无本轮归属记录")
        allowed = {state["requirement_registry"]["source"]["path"]}
        allowed.update(validate_document_path(row["path"]) for row in routing["document_changes"])
        for relative in allowed:
            resolve_workspace_output(root, relative)
        intent = {"branch": branch, "base": versions["root"], "versions": versions, "allowed_paths": sorted(allowed), "tip": None}
        _write(intent_path, intent)
    else:
        intent = _read(intent_path)
    if intent["tip"] is None:
        if branch_tip(root, intent["branch"]) is None:
            if clean_repository(root, "main") != intent["base"]:
                raise RuntimeError("无法恢复入池建分支，main 已偏离基线")
            git(root, "switch", "-c", intent["branch"], intent["base"])
        _pool_boundary(state, intent)
        suffix = f"r{_round(state):04d}"
        if not plan_path.exists():
            prompt = (
                "/requirement-breakdown\n依据充分资料直接生成本批正式增量需求，不再逐项等待普通草案批准。"
                f"只更新 {state['requirement_registry']['source']['path']}，保留所有既有ID、标题、顺序、依赖及正文，新增项追加。"
                "每项围绕内聚用户结果，保留原发现、复现与验收方向。不要创建TRD、代码、规则或Git变更。"
                "所有纳入候选都必须承接，ID按既有惯例且不能重用历史ID；候选可合并或拆分，但拆分时明确负责完整原场景回归的最后需求，"
                "并设置对其余必要项的依赖。最终返回每个新增正式ID及candidate_ids，以及每候选的完整回归requirement_id。\n"
                + json.dumps({"审计": audit, "分流": routing, "既有需求": state["requirement_registry"]["requirements"]}, ensure_ascii=False)
            )
            parsed_source = None
            parsed_catalog = None

            async def check_plan(report: PoolPlan) -> None:
                nonlocal parsed_source, parsed_catalog
                validate_pool_plan(report, routing, {row["id"] for row in state["requirement_registry"]["requirements"]})
                parsed_source, parsed_catalog = await _catalog(state)
                _validate_increment(state, parsed_catalog, report)

            raw, plan = await _task(run_dir, state, f"quality_pool_{suffix}", "quality_pool", prompt,
                                    "本批增量已写入正式Backlog，完整承接纳入发现，拆分依赖和原场景回归归属清楚时完成；不重拆既有产品。",
                                    skill="requirement-breakdown", output_model=PoolPlan, validate=check_plan,
                                    resume_message=message, completion_verifier=lambda: _pool_repair(state, intent))
            if parsed_source is None or parsed_catalog is None:
                raise RuntimeError("入池任务没有交接已核验的需求目录")
            _write(plan_path, {"plan": plan.model_dump(), "report": raw, "source": parsed_source, "catalog": parsed_catalog})
        planned = _read(plan_path)
        plan = PoolPlan.model_validate(planned["plan"])
        if routing["document_changes"]:
            prompt = ("按已经确定的当前产品修正，只更新以下明确文档，不改历史TRD、Backlog条目、代码、规则或Git。"
                      "不以修改文档消除尚应兑现的承诺。已有内容满足时无修改结束。\n"
                      + json.dumps({"文档": routing["document_changes"], "决定": routing["report"], "本批需求": planned["plan"]}, ensure_ascii=False))
            await _task(run_dir, state, f"quality_pool_design_{suffix}", "quality_pool", prompt,
                        "授权的当前文档已按既定决定校正，或已满足而无需修改时完成。", resume_message=message,
                        completion_verifier=lambda: _pool_repair(state, intent))
        if _backlog(state)[2] != planned["source"]:
            raise RuntimeError("本批 Backlog 在计划提取后变化，不能提交未知需求")
        _pool_boundary(state, intent)
        if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
            prompt = ("/commit-changes\n只在当前根仓入池分支精确提交已完成的本批文档，不重做设计或开发，不改业务语义，"
                      "不切换分支、不合并、不push，不处理代码仓。\n"
                      + json.dumps({"分支": intent["branch"], "文件范围": intent["allowed_paths"]}, ensure_ascii=False))
            await _task(run_dir, state, f"quality_pool_commit_{suffix}", "requirement_commit", prompt,
                        "本批文档已精确提交且工作树干净时完成，不重新验收产品。", skill="commit-changes", resume_message=message,
                        completion_verifier=lambda: _pool_commit_repair(state, intent))
        _pool_boundary(state, intent, clean=True)
        intent["tip"] = git(root, "rev-parse", "HEAD")
        _write(intent_path, intent)
    else:
        planned = _read(plan_path)
        plan = PoolPlan.model_validate(planned["plan"])
    main = branch_tip(root, "main")
    tip = intent["tip"]
    target = branch_tip(root, intent["branch"])
    if not main or not ancestor(root, intent["base"], main) or not ancestor(root, main, tip):
        raise RuntimeError("入池合并 main 与保存提交冲突")
    if target not in (None, tip) or (target is None and main != tip):
        raise RuntimeError("入池分支引用与保存提交冲突")
    current_branch = git(root, "branch", "--show-current")
    if current_branch not in ("main", intent["branch"]):
        raise RuntimeError("入池合并处于未知分支")
    clean_repository(root, str(current_branch))
    if current_branch != "main":
        git(root, "switch", "main")
    if main != tip:
        git(root, "merge", "--ff-only", tip)
    if target is not None:
        git(root, "branch", "-d", intent["branch"])
    if clean_repository(root, "main") != tip:
        raise RuntimeError("入池最终版本与保存提交不一致")
    return _success(run_dir, state, {**planned, "branch": intent["branch"], "base": intent["base"], "tip": tip,
                                    "allowed_paths": intent["allowed_paths"]}, "本批正式需求已提交并合并到根 main")


def _pool_repair(state: dict[str, Any], intent: dict[str, Any]) -> str | None:
    _pool_boundary(state, intent)
    _backlog(state)
    return None


def _pool_commit_repair(state: dict[str, Any], intent: dict[str, Any]) -> str | None:
    _pool_boundary(state, intent)
    if git(workspace(state), "status", "--porcelain=v1", "--untracked-files=all"):
        return "本批文档仍有未提交变化，请只按授权文件范围补完精确提交。"
    return None


def _register(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    pooled = _prior(run_dir, state, "pool")
    if _backlog(state)[2] != pooled["source"]:
        raise RuntimeError("入池后 Backlog 指纹发生未解释变化")
    from common.requirement_registry import validate_catalog
    catalog = validate_catalog(pooled["catalog"])
    plan = PoolPlan.model_validate(pooled["plan"])
    _validate_increment(state, catalog, plan)
    previous = {row["id"]: row for row in state["requirement_registry"]["requirements"]}
    requirements = []
    for row in catalog:
        old = previous.get(row["id"])
        requirements.append({**row, "status": old["status"] if old else "pending", "completion": old["completion"] if old else None})
    registry = {"schema_version": 1, "source": pooled["source"], "requirements": requirements}
    return _success(run_dir, state, {"registry": registry, "new_ids": [row.requirement_id for row in plan.requirements]}, "新增需求已登记，既有完成事实保持不变")


def _select(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("active_requirement") is not None or state.get("requirement_cycle") is not None:
        raise RuntimeError("质量批次仍有活动需求，不能重新选择")
    requirements = state["requirement_registry"]["requirements"]
    pending = [row for row in requirements if row["status"] == "pending"]
    batch = set(state["quality"]["batch_requirement_ids"])
    if any(row["status"] == "active" for row in requirements) or any(row["id"] not in batch for row in pending):
        raise RuntimeError("质量批次需求生命周期不一致")
    if pending:
        completed = {row["id"] for row in requirements if row["status"] == "completed"}
        if not any(set(row["depends_on"]) <= completed for row in pending):
            raise RuntimeError("质量批次仍有 pending，但没有依赖完成的可开发需求")
        return _success(run_dir, state, {"next_node": "select_requirement"}, "继续确定性选择本批需求")
    if not batch or not batch <= {row["id"] for row in requirements if row["status"] == "completed"}:
        raise RuntimeError("质量批次没有完整的需求完成事实")
    return _success(run_dir, state, {"next_node": "audit", "next_round": _round(state) + 1}, "本批已完成，进入新的完整审计轮")


def _complete(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    audit = _prior(run_dir, state, "audit")
    routed = _prior(run_dir, state, "route")
    report = RoutingReport.model_validate({key: routed[key] for key in RoutingReport.model_fields})
    validate_routing(report, audit, state["requirement_registry"]["requirements"])
    if not report.ready_to_complete or state.get("active_requirement") or state.get("requirement_cycle"):
        raise RuntimeError("质量周期尚未满足收口条件")
    if any(row["status"] != "completed" for row in state["requirement_registry"]["requirements"]):
        raise RuntimeError("仍有正式需求未完成")
    versions = main_versions(state)
    if versions != audit["versions"]:
        raise RuntimeError("最新完整审计未覆盖当前集成版本")
    return _success(run_dir, state, {"versions": versions, "audit_round": _round(state),
                                    "summary": routed["summary"], "limitations": audit["limitations"],
                                    "dispositions": routed["decisions"]}, "产品质量周期已经在当前集成版本收口")


async def run_node(run_dir: Path, state: dict[str, Any], *, resume_message: ResumeMessage | None = None) -> dict[str, Any]:
    node = _node(state)
    if node == "completed":
        if not is_completed(state):
            raise RuntimeError("质量完成状态不一致")
        return _read(node_result_path(run_dir, state))
    if state.get("step") is not None or state.get("current_step") is not None:
        raise RuntimeError("当前是数值需求步骤，请使用需求执行入口")
    path = node_result_path(run_dir, state)
    if path.exists() and node != "select_requirement":
        saved = _read(path)
        if saved.get("status") == "success":
            if saved.get("node") != state["current_node"] or saved.get("round") != _round(state):
                raise RuntimeError("质量成功结果与当前节点不一致")
            if resume_message:
                raise RuntimeError("已完成节点不能投递恢复消息")
            return _advance(run_dir, state, saved)
    if node == "audit" and _round(state) > state["quality"]["max_rounds"]:
        raise IterationLimit("完整审计轮次预算耗尽，可提高 max-rounds 后恢复本轮；当前不能宣称质量收口")
    if state.get("status") != "blocked":
        updated = copy.deepcopy(state)
        updated.update({"status": "running", "error": None, "blocked": None})
        _replace_state(run_dir, state, updated)
    if node in {"prepare", "audit", "pool"}:
        return await {"prepare": _prepare, "audit": _audit, "pool": _pool}[node](run_dir, state, resume_message)
    if resume_message:
        raise RuntimeError("当前节点没有 Agent 会话，不能投递恢复消息")
    if node == "route":
        return await _route(run_dir, state)
    return {"register": _register, "select_requirement": _select, "complete": _complete}[node](run_dir, state)


def requirement_evidence(run_dir: Path, state: dict[str, Any]) -> str:
    if state.get("workflow") != WORKFLOW:
        return ""
    identifier = state.get("active_requirement")
    pooled = _prior(run_dir, state, "pool")
    plan = PoolPlan.model_validate(pooled["plan"])
    binding = next((row for row in plan.requirements if row.requirement_id == identifier), None)
    if binding is None:
        raise RuntimeError("活动质量需求缺少原审计候选归属")
    audit = _prior(run_dir, state, "audit")
    owners = {row.candidate_id: row.requirement_id for row in plan.regression_owners}
    routing = _prior(run_dir, state, "route")
    decisions = {row["candidate_id"]: row for row in routing["decisions"]}
    related: dict[str, str] = {}
    for candidate in audit["candidates"]:
        target = candidate["id"]
        seen: set[str] = set()
        while target in decisions and decisions[target]["action"] == "covered":
            if target in seen:
                raise RuntimeError("候选归属存在循环")
            seen.add(target)
            target = decisions[target]["covered_by"]
        if target in binding.candidate_ids or target == identifier:
            related[candidate["id"]] = owners.get(target, str(identifier))
    candidates = [row for row in audit["candidates"] if row["id"] in related]
    blocked_tasks = [row for row in audit["coverage"] if set(row["blocking_candidates"]) & related.keys()]
    return (
        "以下原发现属于当前正式需求。以真实复现任务、状态和相邻路径验证改动，原场景回归在提交合并前完成。"
        "本需求负责完整回归的候选须在必要前置项完成后证明完整任务；其它候选验证本需求承接的结果，不冒充完整修复。"
        "保留相称证据于活动TRD和正常回复，不重跑无关完整验收。\n"
        + json.dumps({"原发现": candidates, "受阻任务": blocked_tasks,
                      "完整回归归属": related}, ensure_ascii=False)
    )
