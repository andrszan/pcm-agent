from __future__ import annotations

import copy
import inspect
import json
from functools import partial
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from common.agent_decision_loop import (
    AgentDecisionLoopSpec, ResumeMessage, agent_conversation_report, run_agent_decision_loop,
)
from common.decision import render_decision_system_prompt, request_decision
from common.error_diagnostics import redact_text
from common.files import resolve_workspace_output, write_json
from common.openai_responses import parse_response
from common.state import write_state
from common.timing import beijing_now
from config import LLMConfig
from feedback.models import (
    DESIGN_TASKS, ExtractionInput, FeedbackInput, PoolPlan, RoutingReport, TriageReport,
    validate_pool_plan, validate_routing,
)
from quality.git import (
    ancestor, branch_tip, clean_repository, git, main_versions, repositories,
    validate_document_path, workspace,
)
# 这些 helper 只操作传入的目录、注册表和分支 intent，不依赖质量节点或轮次。
from quality.workflow import (
    _backlog, _catalog, _pool_boundary, _validate_increment,
    is_completed as quality_completed,
)

WORKFLOW = "product_feedback"
PHASE = "product_feedback_iteration"
NODES = ("prepare", "triage", "route", "pool", "register", "select_requirement", "complete", "completed")


class FeedbackBlocked(RuntimeError):
    def __init__(self, reason: str, required_inputs: list[str]):
        self.required_inputs = required_inputs
        super().__init__(reason)


def _path(run_dir: Path, name: str) -> Path:
    path = run_dir / "feedback" / f"{name}.json"
    if Path(name).name != name or name in {".", ".."}:
        raise RuntimeError("反馈结果路径越界")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise RuntimeError("反馈运行记录路径不能是符号链接")
    return path


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"反馈交接文件不存在或类型不合法：{path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("反馈交接文件必须是对象")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, value)


def _node(state: dict[str, Any]) -> str:
    if state.get("workflow") != WORKFLOW or state.get("phase") != PHASE:
        raise RuntimeError("当前不是产品反馈工作流")
    value = state.get("current_node")
    if value not in {f"feedback:{name}" for name in NODES}:
        raise RuntimeError("当前不是可执行反馈节点")
    return str(value).split(":", 1)[1]


def node_result_path(run_dir: Path, state: dict[str, Any]) -> Path:
    node = _node(state)
    return _path(run_dir, "complete" if node == "completed" else node)


def _prior(run_dir: Path, name: str) -> dict[str, Any]:
    saved = _read(_path(run_dir, name))
    if saved.get("status") != "success" or saved.get("node") != f"feedback:{name}" or saved.get("phase") != PHASE:
        raise RuntimeError(f"缺少成功的 {name} 反馈交接")
    return saved["data"]


def _handoff(run_dir: Path, state: dict[str, Any], name: str) -> dict[str, Any]:
    """结构化结果保持权威；旧 report 的任务包装只在请求中替换，不改保存记录。"""
    saved = _prior(run_dir, name)
    key = f"feedback_{name}"
    spec = AgentDecisionLoopSpec(
        key=key, state_key=key, skill_name=None, max_decision_rounds=32, max_turns=9999,
        task=key, decision_system_prompt="读取本步已保存的实质交接",
    )
    report = agent_conversation_report(run_dir, state, spec, include_initial_context=False)
    return {**saved, "report": report}


def _batch_context(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    return {"本批输入": _input(run_dir).model_dump(),
            "运行条件": _handoff(run_dir, state, "prepare")["report"]}


def is_completed(state: dict[str, Any]) -> bool:
    registry = state.get("requirement_registry", {}).get("requirements", [])
    return (
        state.get("workflow") == WORKFLOW and state.get("phase") == PHASE
        and state.get("current_node") == "feedback:completed" and state.get("status") == "success"
        and state.get("active_requirement") is None and state.get("requirement_cycle") is None
        and state.get("blocked") is None and state.get("error") is None
        and bool(registry) and all(row.get("status") == "completed" for row in registry)
    )


def new_state(source_state: dict[str, Any], source_run_id: str, run_id: str) -> dict[str, Any]:
    if not (quality_completed(source_state) or is_completed(source_state)):
        raise RuntimeError("来源必须是成功完成且没有活动或待开发需求的质量或反馈运行")
    if source_run_id == run_id or any(not value or Path(value).name != value or value in {".", ".."} for value in (source_run_id, run_id)):
        raise ValueError("来源与新的运行标识必须是不同的安全名称")
    repositories(source_state)
    try:
        git(workspace(source_state), "check-ref-format", "--branch", f"feedback/{run_id}/documents")
    except RuntimeError as error:
        raise ValueError("运行标识不能形成合法的反馈文档分支") from error
    copied = {key: copy.deepcopy(source_state[key]) for key in (
        "workspace", "applicable_repositories", "repositories", "requirement_registry",
    )}
    return {
        **copied, "run_id": run_id, "source_run_id": source_run_id, "workflow": WORKFLOW,
        "phase": PHASE, "current_node": "feedback:prepare", "step": None, "current_step": None,
        "status": "success", "blocked": None, "error": None, "active_requirement": None, "requirement_cycle": None,
        "feedback": {"entry_versions": {}, "baseline_requirement_ids": [
            row["id"] for row in source_state["requirement_registry"]["requirements"]
        ], "batch_requirement_ids": []},
    }


def node_resume_keys(state: dict[str, Any]) -> tuple[str, ...]:
    node = _node(state)
    if node in {"prepare", "triage", "route"}:
        return (f"feedback_{node}",)
    if node == "pool":
        return tuple(f"feedback_{task}" for task in (*DESIGN_TASKS, "pool", "document", "commit"))
    return ()


def _replace_state(run_dir: Path, state: dict[str, Any], updated: dict[str, Any]) -> None:
    write_state(run_dir, updated)
    state.clear()
    state.update(updated)


def _advance(run_dir: Path, state: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    node = saved["node"].split(":", 1)[1]
    following = {"prepare": "triage", "triage": "route", "route": "pool", "pool": "register", "register": "select_requirement", "complete": "completed"}
    data = saved["data"]
    updated = copy.deepcopy(state)
    if node == "prepare":
        updated["requirement_registry"] = data["registry"]
        updated["feedback"]["entry_versions"] = data["versions"]
    elif node == "pool" and not data["plan"]:
        following[node] = "complete"
    elif node == "register":
        updated["requirement_registry"] = data["registry"]
        updated["feedback"]["batch_requirement_ids"] = data["new_ids"]
    elif node == "select_requirement":
        following[node] = data["next_node"]
    updated.update(status="success", blocked=None, error=None, current_node=f"feedback:{following[node]}", step=None, current_step=None)
    if node == "select_requirement" and data["next_node"] == "select_requirement":
        updated.update(step=13, current_step=13)
    _replace_state(run_dir, state, updated)
    return saved


def _success(run_dir: Path, state: dict[str, Any], data: dict[str, Any], summary: str) -> dict[str, Any]:
    saved = {"phase": PHASE, "node": state["current_node"], "status": "success", "summary": summary,
             "outputs": [], "blocked": None, "error": None, "data": data}
    _write(node_result_path(run_dir, state), saved)
    return _advance(run_dir, state, saved)


def record_failure(run_dir: Path, state: dict[str, Any], error: Exception) -> dict[str, Any]:
    path = node_result_path(run_dir, state)
    if path.exists():
        previous = _read(path)
        if previous.get("status") == "success" and _node(state) != "select_requirement":
            return previous
    message = redact_text(str(error))
    blocked = {"reason": message, "required_inputs": [redact_text(value) for value in error.required_inputs]} if isinstance(error, FeedbackBlocked) else None
    saved = {"phase": PHASE, "node": state["current_node"], "status": "blocked" if blocked else "failed",
             "summary": message, "outputs": [], "blocked": blocked,
             "error": None if blocked else (error.as_error() if hasattr(error, "as_error") else {"type": type(error).__name__, "message": message})}
    _write(path, saved)
    updated = copy.deepcopy(state)
    updated.update({key: saved[key] for key in ("status", "blocked", "error")})
    _replace_state(run_dir, state, updated)
    return saved


async def _task(
    run_dir: Path, state: dict[str, Any], key: str, task: str, prompt: str, responsibility: str,
    *, skill: str | None = None, output_model: type[BaseModel] | None = None,
    validate: Callable[[Any], Awaitable[None] | None] | None = None, resume_message: ResumeMessage | None = None,
    completion_verifier: Callable[[], str | None] | None = None,
    completion_repair: str | None = None,
    extraction_context: Callable[[], str] | None = None,
) -> tuple[str, Any]:
    spec = AgentDecisionLoopSpec(
        key=key, state_key=key, skill_name=skill, max_decision_rounds=32, max_turns=9999, task=task,
        decision_system_prompt=render_decision_system_prompt(responsibility, {"当前任务": prompt}),
    )
    raw, parsed = "", None

    async def verify() -> str | None:
        nonlocal raw, parsed, completion_repair
        if completion_verifier:
            repair = completion_verifier()
            if repair:
                return repair
        raw = agent_conversation_report(run_dir, state, spec, include_initial_context=False)
        if completion_repair:
            repair, completion_repair = completion_repair, None
            # 公共循环会保存修正并投递原 session；中断恢复复用这条消息，不重复纠正。
            if json.dumps(repair, ensure_ascii=False) not in raw:
                return repair
        if output_model:
            try:
                parsed = await parse_response(
                    LLMConfig.load(),
                    system_prompt=("依据完整有序对话提取当前有效成果，返回严格 JSON，不补造事实或代替负责人决定。"
                                   "report保留本步Agent回复、负责人决定与后续补充纠正，初始任务及当前资料见context。"
                                   "report中user是执行Agent，assistant是负责人决定或补充纠正。"
                                   "后续明确纠正替代对应旧事实；局部补证不删除其它有效问题、目标和限制。"
                                   "候选包含全部原始反馈的归属，包括已满足、待补证、待决和不采用项，不假装全产品审计。"
                                   "mandatory仅依据调用方本批明确必达目标，不能自行降级；证据不足保留事实及限制。"),
                    input_model=ExtractionInput(report=raw, context=extraction_context() if extraction_context else prompt),
                    output_model=output_model,
                )
                if validate:
                    checked = validate(parsed)
                    if inspect.isawaitable(checked):
                        await checked
            except (ValueError, ValidationError) as error:
                return f"本步交接存在具体缺口：{redact_text(str(error))}。只补齐或纠正本步产物，保留其它有效成果，不重做上游。"
        return None

    decision = await run_agent_decision_loop(
        run_dir, state, workspace(state), spec, prompt, verify, resume_message=resume_message,
        decision_runner=partial(request_decision, include_initial_context=False),
    )
    if decision.verdict == "blocked":
        raise FeedbackBlocked(decision.reason, decision.required_inputs)
    if decision.verdict != "completed":
        raise RuntimeError("领域任务未完成")
    return raw, parsed


def _input(run_dir: Path) -> FeedbackInput:
    supplied = FeedbackInput.model_validate(_read(_path(run_dir, "input")))
    if any(not Path(path).is_file() for path in supplied.attachments):
        raise ValueError("本批附件不可访问，请恢复原附件路径")
    return supplied


def _document_path(state: dict[str, Any], relative: str) -> Path:
    root = workspace(state)
    path = resolve_workspace_output(root, validate_document_path(relative))
    for current in (path, *path.parents):
        if current == root:
            break
        if current.is_symlink():
            raise ValueError("反馈文档路径不能是符号链接")
    return path


def _protect_inputs(run_dir: Path, state: dict[str, Any], paths: set[str]) -> None:
    supplied = _input(run_dir)
    originals = {Path(path).resolve() for path in (supplied.source, supplied.intent_source, *supplied.attachments) if path is not None}
    if any(_document_path(state, path).resolve() in originals for path in paths):
        raise ValueError("文档写入范围与原反馈、意图原件或附件重合，不能修改原始材料")


def _boundary(state: dict[str, Any], intent: dict[str, Any], *, clean: bool = False) -> None:
    _pool_boundary(state, intent, clean=clean)
    for relative in intent["allowed_paths"]:
        _document_path(state, relative)


def _commit_check(state: dict[str, Any], intent: dict[str, Any]) -> str | None:
    missing = _document_check(state, intent)
    if missing:
        return missing
    if git(workspace(state), "status", "--porcelain=v1", "--untracked-files=all"):
        return "本批文档仍有未提交变化，请仅按授权文件精确提交。"
    return None


async def _prepare(run_dir: Path, state: dict[str, Any], message: ResumeMessage | None) -> dict[str, Any]:
    supplied = _input(run_dir)
    if not state["feedback"]["entry_versions"]:
        versions = main_versions(state)
        source, catalog = await _catalog(state)
        historical = {row["id"]: row for row in state["requirement_registry"]["requirements"]}
        if {row["id"] for row in catalog} != set(historical):
            raise RuntimeError("当前正式 ID 与来源完成记录不一致")
        updated = copy.deepcopy(state)
        updated["requirement_registry"] = {"schema_version": 1, "source": source, "requirements": [
            {**row, "status": historical[row["id"]]["status"], "completion": historical[row["id"]]["completion"]} for row in catalog
        ]}
        updated["feedback"]["entry_versions"] = versions
        _replace_state(run_dir, state, updated)
    prompt = (
        "只为本批反馈准备必要现场，不执行全产品审计，不重跑初始化或资源选型。"
        "读取当前产品定义、Backlog、必要设计、工程、运行说明及 .pcm/runtime.json，复用既有 endpoint、资源与授权。"
        "可运行现有工程、安装依赖、启动归属清楚的既有服务，在授权范围内准备可复位数据、迁移或初始化。"
        "不得修改受跟踪代码、配置、文档或Git；不可逆操作、生产数据、付款与真实外发不能由反馈自动授权。"
        "原材料保持不变，不复制附件，不输出秘密。交接可访问入口、身份使用方法、运行条件与允许操作边界。"
        "本地执行错误如实报告失败，不当成外部阻塞。\n"
        + json.dumps({"本批输入": supplied.model_dump(), "Backlog": state["requirement_registry"]["source"]["path"]}, ensure_ascii=False)
    )
    raw, _ = await _task(run_dir, state, "feedback_prepare", "feedback_prepare", prompt,
                         "仅补必要现场缺口，依据当前意图与已有授权自主安排。条件可用即完成，不索取重复完成声明。只有不可替代外部条件缺失才blocked。",
                         resume_message=message)
    if main_versions(state) != state["feedback"]["entry_versions"]:
        raise RuntimeError("准备期间改变了产品版本，保留现场")
    return _success(run_dir, state, {"report": raw, "versions": state["feedback"]["entry_versions"],
                                    "registry": state["requirement_registry"]}, "本批反馈现场已准备")


def _intent(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    intent = state["feedback"].get("document_intent")
    if intent is None:
        versions = main_versions(state)
        if versions != state["feedback"]["entry_versions"]:
            raise RuntimeError("分诊开始版本偏离准备版本")
        branch = f"feedback/{run_dir.name}/documents"
        if branch_tip(workspace(state), branch) is not None:
            raise RuntimeError("反馈分支已存在但没有归属记录")
        document = f"docs/feedback/{beijing_now()[:10]}-{run_dir.name}-核验反馈.md"
        path = _document_path(state, document)
        if path.exists():
            raise RuntimeError("本批反馈文档已存在但没有归属记录")
        intent = {"branch": branch, "base": versions["root"], "versions": versions,
                  "allowed_paths": [document], "tip": None}
        updated = copy.deepcopy(state)
        updated["feedback"].update(document_path=document, document_intent=intent)
        _replace_state(run_dir, state, updated)
    return copy.deepcopy(intent)


def _open_branch(state: dict[str, Any], intent: dict[str, Any]) -> None:
    root = workspace(state)
    if branch_tip(root, intent["branch"]) is None:
        if clean_repository(root, "main") != intent["base"]:
            raise RuntimeError("恢复文档分支时 main 已偏离基线")
        git(root, "switch", "-c", intent["branch"], intent["base"])
    _boundary(state, intent)


def _document_check(state: dict[str, Any], intent: dict[str, Any]) -> str | None:
    _boundary(state, intent)
    path = _document_path(state, state["feedback"]["document_path"])
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        return "请在已指定的唯一反馈文档中写入本批核验结果与全部原始反馈的处置归属。"
    return None


def _triage_check(state: dict[str, Any], intent: dict[str, Any]) -> str | None:
    if git(workspace(state), "rev-parse", "HEAD") != intent["base"]:
        raise RuntimeError("分诊不能创建 Git 提交，保留现场")
    return _document_check(state, intent)


async def _triage(run_dir: Path, state: dict[str, Any], message: ResumeMessage | None) -> dict[str, Any]:
    context = _batch_context(run_dir, state)
    intent = _intent(run_dir, state)
    _open_branch(state, intent)
    prompt = (
        "/product-feedback-triage\n只核验本批反馈及直接关联问题，区分事实主张、用户痛点、建议方案和已授权产品决定。"
        "不因符合旧设计或属于主观感受而拒绝有依据改进；认可目标不等于认可根因或方案。"
        "在当前授权内自行补证和决定普通取舍，不向人逐项索取批准；独立问题继续核验，不能因个别未知放弃整批。"
        "原始材料保持不变、不复制附件；唯一可写文件为指定反馈文档，不改产品定义、Backlog、TRD、代码、配置或Git。"
        "文档精简记录问题、影响、核验事实、期望结果、来源，以及待补证、待决、已有覆盖和不采用的必要理由。"
        "所有原始问题均有归属，明确本批必达事项；缺少必要信息如实保留，不伪造完整产品审计。"
        "不把秘密或非必要个人数据写入文档和输出，候选不自动变成正式需求。\n"
        + json.dumps({**context, "唯一反馈文档": state["feedback"]["document_path"],
                      "版本": intent["versions"]}, ensure_ascii=False)
    )
    raw, report = await _task(run_dir, state, "feedback_triage", "feedback_triage", prompt,
                              "依据完整对话收敛本批核验及文档交接，普通语义决定由负责人自主处理。局部补证不撤销其它有效结论。只补本步具体缺口，不重做上游。调查完成不代表所有问题已解决；本地错误不作为外部blocked。",
                              skill="product-feedback-triage", output_model=TriageReport, resume_message=message,
                              completion_verifier=lambda: _triage_check(state, intent),
                              extraction_context=lambda: prompt + "\n本步已生成的反馈文档正文：\n" + _document_path(
                                  state, state["feedback"]["document_path"],
                              ).read_text(encoding="utf-8"))
    if _triage_check(state, intent):
        raise RuntimeError("分诊没有生成反馈文档")
    data = {**report.model_dump(exclude={"findings"}), "report": raw, "versions": intent["versions"],
            "document_path": state["feedback"]["document_path"],
            "candidates": [{"id": f"F-C{index + 1:03d}", **row.model_dump()} for index, row in enumerate(report.findings)]}
    return _success(run_dir, state, data, "本批反馈已核验，候选尚未进入正式范围")


async def _route(run_dir: Path, state: dict[str, Any], message: ResumeMessage | None) -> dict[str, Any]:
    triage = _handoff(run_dir, state, "triage")
    intent = state["feedback"]["document_intent"]
    _boundary(state, intent)
    document = _document_path(state, triage["document_path"])
    document_before = document.read_bytes()

    def check_read_only() -> str | None:
        _triage_check(state, intent)
        if document.read_bytes() != document_before:
            raise RuntimeError("分流不能改写反馈文档，保留现场")
        return None

    def check_report(report: RoutingReport) -> None:
        if report.required_inputs:
            raise ValueError("本批仍有必需外部条件，不能作为完成结果交接。请准确说明已尝试动作、缺少的资源或授权、"
                             "影响及解除条件，交由负责人按当前事实作出 blocked 裁决；若是可自行解决的普通取舍或本地错误，"
                             "应准确纠正，不把它们作为外部阻塞。所需输入：" + "；".join(report.required_inputs))
        validate_routing(report, triage, state["requirement_registry"]["requirements"])
        for change in report.document_changes:
            if change.path == state["requirement_registry"]["source"]["path"]:
                raise ValueError("设计调整不能修改正式 Backlog")
            _document_path(state, change.path)
        _protect_inputs(run_dir, state, {change.path for change in report.document_changes})

    completion = (
        "本节点只完成候选采用决定和逐文件调整计划，全程只读，包括反馈文档在内的任何文件及Git均不得写入。"
        "候选处置、必要决定与逐文件计划足够时即AgentDecision.completed；"
        "有include且尚待文档调整、开发或验证，同样可以completed，不把整批实现或文档落地当成本步完成条件。"
        "RoutingReport.ready_to_complete只表示整批无纳入需求且可直接收尾，不是本节点完成开关；"
        "有include时应为false，不妨碍本节点completed。"
        "事实与建议充分且可接受时，负责人直接在completed.reason记录采纳决定，供完整对话提取，"
        "无需先continue批准或要求Agent再作完成声明。"
        "continue只补具体范围决策或候选、逐文件计划的交接缺口，仅在回复中补充，"
        "不得授权写文件、调用设计能力或执行任何后续阶段动作。"
        "实际文档调整留给后续入池节点，开发与验证留给正式需求流程，不要求本节点补交开发证据。"
    )
    error = state.get("error") or {}
    error_message = error.get("message", "").removeprefix("完成核验失败：")
    completion_repair = None
    if state.get("status") == "failed" and error.get("type") == "RuntimeError" and error_message in {
        "入池存在范围外变更，保留现场",
        "分流不能改写反馈文档，保留现场",
        "分诊不能创建 Git 提交，保留现场",
        "入池改变了代码仓库",
    }:
        # 旧 completed 未通过只读核验，不能在现场恢复后直接提取旧的越界成果。
        completion_repair = (
            "此前completed未通过只读边界核验，不能作为有效交接。现明确纠正原会话中的后续执行指令："
            + completion
            + "保留已决定的采用范围和原核验事实，不重做分诊、不新增候选。"
            "旧回复中‘文档已修改’及相关落地声明不再作为当前成果；"
            "请仅在回复中重新交接候选处置、逐文件路径、任务与理由，文档调整均作为待执行计划。"
        )
    prompt = (
        completion
        + "只依据已提供的完整核验交接和本批原意图整理采用选项、事实依据、影响与推荐，交由负责人决定本批范围。"
        "不调用领域能力、不重复调查、不写产品文件或Git。每个候选恰好一个include、covered、exclude、defer或satisfied，不新增候选。"
        "当前承诺内缺陷、有依据改进和当前授权内明确的新能力均可纳入；反馈提交不产生外部授权。"
        "区分建议与有决定权者已明确目标；普通取舍由负责人自主决定，不向人逐项审批。"
        "covered只指同批候选或未完成正式项，不能用历史完成记录掩盖仍存在的缺陷。"
        "satisfied只用于有核验事实证明目标当前已满足；defer用于独立非必达的待补证或待决项，写明依据及follow_up解除条件。"
        "本批明确必达事项不能延期后success。必要外部资源或授权缺失用required_inputs说明，并准确交接负责人判断blocked；"
        "本地执行错误或交接矛盾不能伪装外部blocked，没有可推进工作时ready_to_complete=false并说明原因。"
        "无纳入且本批职责已处理完才ready_to_complete=true，暂不纳入不等于已解决，不要求全产品coverage。"
        "必要的权威产品定义调整指定project_intake；其它设计按实际影响指定solution_design、engineering_architecture或ui_ux_framework。"
        "document_changes逐文件列出docs内Markdown路径、任务与理由，不修改历史TRD、反馈文档、Backlog或原始输入文件，不默认重跑全部设计。\n"
        + json.dumps({**_batch_context(run_dir, state), "完整分诊交接": triage,
                      "已有需求": state["requirement_registry"]["requirements"]}, ensure_ascii=False)
    )
    raw, report = await _task(
        run_dir, state, "feedback_route", "feedback_route", prompt,
        completion + "依据完整核验和原意图自主决定普通产品取舍，收敛采用范围与必要设计影响，不重新调查，不向人逐项索取批准。"
        "本批必达事项不能被延期。缺少不可替代的必要外部资源或授权时，准确给出blocked及required_inputs，"
        "不能先completed再留下必要外部缺口；非必达独立事项可据实暂不纳入，本地错误不当作外部阻塞。"
        "恢复澄清仅用于解除本批条件或纠正原判断，不把新的独立诉求加入本批。",
        output_model=RoutingReport, validate=check_report, resume_message=message, completion_verifier=check_read_only,
        completion_repair=completion_repair,
    )
    check_report(report)
    check_read_only()
    return _success(run_dir, state, {**report.model_dump(), "report": raw}, "本批范围已决定")


async def _pool(run_dir: Path, state: dict[str, Any], message: ResumeMessage | None) -> dict[str, Any]:
    root = workspace(state)
    routed, triage = (_handoff(run_dir, state, name) for name in ("route", "triage"))
    context = _batch_context(run_dir, state)
    included = any(row["action"] == "include" for row in routed["decisions"])
    intent = copy.deepcopy(state["feedback"]["document_intent"])
    allowed = {state["feedback"]["document_path"]}
    if included:
        allowed.add(validate_document_path(state["requirement_registry"]["source"]["path"]))
        allowed.update(validate_document_path(row["path"]) for row in routed["document_changes"])
    intent["allowed_paths"] = sorted(allowed)
    _protect_inputs(run_dir, state, allowed)
    plan_path = _path(run_dir, "pool-plan")
    if intent["tip"] is None:
        _open_branch(state, intent)
        # 先调整权威定义，再按实际能力范围设计，最后增量拆分；每个 session 的成功由公共会话机制恢复。
        for task in (() if plan_path.exists() else DESIGN_TASKS):
            changes = [row for row in routed["document_changes"] if row["task"] == task]
            if changes:
                skill = task.replace("_", "-")
                prompt = (f"/{skill}\n按已采纳目标局部调整指定文件，只处理本次实际影响，不重跑其它设计。"
                          "保留既有无关范围与历史条目，不改Backlog、TRD、代码、配置或Git，不以文档调整消除必达承诺。\n"
                          + json.dumps({**context, "文件范围": changes, "采纳决定": routed, "核验反馈": triage}, ensure_ascii=False))
                await _task(run_dir, state, f"feedback_{task}", task, prompt,
                            "本次授权的局部调整已完成或现有内容已满足即可交接，不扩张范围。",
                            skill=skill, resume_message=message, completion_verifier=lambda: _document_check(state, intent))
        if included and not plan_path.exists():
            parsed_source, parsed_catalog = None, None

            async def check_plan(plan: PoolPlan) -> None:
                nonlocal parsed_source, parsed_catalog
                validate_pool_plan(plan, routed, set(state["feedback"]["baseline_requirement_ids"]))
                parsed_source, parsed_catalog = await _catalog(state)
                _validate_increment(state, parsed_catalog, plan)

            prompt = (
                "/requirement-breakdown\n按充分资料直接形成已纳入目标的增量正式需求，不等待普通草案审批。"
                f"只更新 {state['requirement_registry']['source']['path']}，保留全部历史ID、标题、顺序、依赖和正文，新增项追加。"
                "候选允许合并或拆分，所有纳入目标与适用条件必须承接；不纳入项仅作上下文，不能自动开发。"
                "缺陷回归原复现任务；改进和新能力验证采纳的可观察结果。拆分后指定负责完整回归的最后需求，"
                "设置对其它必要承接项的真实前置依赖。返回正式ID到candidate_ids的多对多关联及regression_owners。"
                "不创建TRD、代码或Git变更，不采用反馈者方案作为唯一实现。\n"
                + json.dumps({**context, "核验": triage, "已采用范围": routed,
                              "历史需求": state["requirement_registry"]["requirements"]}, ensure_ascii=False)
            )
            raw, plan = await _task(run_dir, state, "feedback_pool", "feedback_pool", prompt,
                                    "已纳入目标完整承接且静态条目、回归归属和依赖有效时完成；只修本步产物缺口。",
                                    skill="requirement-breakdown", output_model=PoolPlan, validate=check_plan,
                                    resume_message=message, completion_verifier=lambda: _document_check(state, intent))
            if parsed_source is None or parsed_catalog is None:
                raise RuntimeError("入池缺少已核验需求目录")
            _write(plan_path, {"plan": plan.model_dump(), "report": raw, "source": parsed_source, "catalog": parsed_catalog})
        if not included and not plan_path.exists():
            _write(plan_path, {"plan": None, "source": state["requirement_registry"]["source"], "catalog": []})
        planned = _read(plan_path)
        if _backlog(state)[2] != planned["source"]:
            raise RuntimeError("计划形成后 Backlog 指纹变化，不能提交未知需求")
        if _document_check(state, intent):
            raise RuntimeError("缺少实际反馈文档")
        if git(root, "status", "--porcelain=v1", "--untracked-files=all") or "feedback_commit" in state:
            prompt = ("只把负责人已经确定的本批处置准确整理到指定的唯一反馈文档，不重新核验、不改变采用范围。"
                      "保留原问题、来源、核验事实与限制，说明已纳入目标及正式需求归属、合并处理、"
                      "未纳入、待补证、待决的理由与后续条件。纳入项此时尚待开发，不能声称已经解决。"
                      "如已有对应内容则局部校正，不重复追加。只改反馈文档，不改其它文档、代码、配置或Git。\n"
                      + json.dumps({**context, "唯一反馈文档": state["feedback"]["document_path"], "已确定处置": routed,
                                    "正式需求归属": planned["plan"], "核验反馈": triage}, ensure_ascii=False))
            await _task(run_dir, state, "feedback_document", "feedback_pool", prompt,
                        "本批既定处置已准确写回唯一文档即完成，不重做上游语义决定或调查。",
                        resume_message=message, completion_verifier=lambda: _document_check(state, intent))
            if _backlog(state)[2] != planned["source"]:
                raise RuntimeError("反馈文档收尾改变了正式 Backlog")
            prompt = ("/commit-changes\n只在当前根文档分支精确提交已授权文件，不改业务语义，不切分支、不合并、不push、不处理代码仓。"
                      "不改写已有反馈处置正文，不创建空提交；不修改历史需求和TRD。\n"
                      + json.dumps({"分支": intent["branch"], "文件范围": intent["allowed_paths"], "最终处置": routed,
                                    "反馈文档": state["feedback"]["document_path"]}, ensure_ascii=False))
            await _task(run_dir, state, "feedback_commit", "requirement_commit", prompt,
                        "实际反馈文档、授权设计和新增Backlog已精确提交，工作树干净时完成，不重新验收产品。",
                        skill="commit-changes", resume_message=message,
                        completion_verifier=lambda: _commit_check(state, intent))
        _boundary(state, intent, clean=True)
        if _backlog(state)[2] != planned["source"]:
            raise RuntimeError("提交期间 Backlog 发生变化")
        intent["tip"] = git(root, "rev-parse", "HEAD")
        if intent["tip"] == intent["base"]:
            raise RuntimeError("反馈文档未产生实际提交")
        updated = copy.deepcopy(state)
        updated["feedback"]["document_intent"] = intent
        _replace_state(run_dir, state, updated)
    planned = _read(plan_path)
    main, tip = branch_tip(root, "main"), intent["tip"]
    target = branch_tip(root, intent["branch"])
    if not main or not ancestor(root, intent["base"], main) or not ancestor(root, main, tip):
        raise RuntimeError("文档合并 main 与已保存提交冲突")
    if target not in (None, tip) or (target is None and main != tip):
        raise RuntimeError("文档分支引用与已保存提交冲突")
    current = git(root, "branch", "--show-current")
    if current not in ("main", intent["branch"]):
        raise RuntimeError("文档合并处于未知分支")
    clean_repository(root, str(current))
    for name, path in repositories(state)[1:]:
        if clean_repository(path, "main") != intent["versions"][name]:
            raise RuntimeError("文档处理改变了代码仓库")
    if current != "main":
        git(root, "switch", "main")
    if main != tip:
        git(root, "merge", "--ff-only", tip)
    if target is not None:
        git(root, "branch", "-d", intent["branch"])
    if clean_repository(root, "main") != tip:
        raise RuntimeError("文档最终版本与保存提交不一致")
    return _success(run_dir, state, {**planned, **intent}, "本批反馈文档与正式范围已提交并合并")


def _register(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    pooled = _prior(run_dir, "pool")
    if _backlog(state)[2] != pooled["source"]:
        raise RuntimeError("入池后 Backlog 指纹发生变化")
    from common.requirement_registry import validate_catalog
    catalog = validate_catalog(pooled["catalog"])
    plan = PoolPlan.model_validate(pooled["plan"])
    validate_pool_plan(plan, _prior(run_dir, "route"), set(state["feedback"]["baseline_requirement_ids"]))
    _validate_increment(state, catalog, plan)
    previous = {row["id"]: row for row in state["requirement_registry"]["requirements"]}
    registry = {"schema_version": 1, "source": pooled["source"], "requirements": [
        {**row, "status": previous[row["id"]]["status"] if row["id"] in previous else "pending",
         "completion": previous[row["id"]]["completion"] if row["id"] in previous else None} for row in catalog
    ]}
    return _success(run_dir, state, {"registry": registry, "new_ids": [row.requirement_id for row in plan.requirements]}, "新增需求已登记，历史完成事实不变")


def _select(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("active_requirement") is not None or state.get("requirement_cycle") is not None:
        raise RuntimeError("本批仍有活动需求，不能重新选择")
    requirements = state["requirement_registry"]["requirements"]
    pending = [row for row in requirements if row["status"] == "pending"]
    batch = set(state["feedback"]["batch_requirement_ids"])
    if any(row["status"] == "active" for row in requirements) or any(row["id"] not in batch for row in pending):
        raise RuntimeError("反馈批次需求生命周期不一致")
    completed = {row["id"] for row in requirements if row["status"] == "completed"}
    if pending:
        if not any(set(row["depends_on"]) <= completed for row in pending):
            raise RuntimeError("本批没有依赖完成的可开发需求")
        return _success(run_dir, state, {"next_node": "select_requirement"}, "继续选择本批需求")
    if not batch or not batch <= completed:
        raise RuntimeError("本批没有完整需求完成事实")
    return _success(run_dir, state, {"next_node": "complete"}, "本批纳入需求已全部完成")


def _complete(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    triage, routed, pooled = (_prior(run_dir, name) for name in ("triage", "route", "pool"))
    report = RoutingReport.model_validate({key: routed[key] for key in RoutingReport.model_fields})
    validate_routing(report, triage, state["requirement_registry"]["requirements"])
    if report.required_inputs:
        raise FeedbackBlocked(report.summary, report.required_inputs)
    if state.get("active_requirement") is not None or state.get("requirement_cycle") is not None or any(
        row["status"] != "completed" for row in state["requirement_registry"]["requirements"]
    ):
        raise RuntimeError("本批仍有未完成正式需求")
    versions = main_versions(state)
    document = _document_path(state, triage["document_path"])
    if not document.is_file() or not document.read_text(encoding="utf-8").strip():
        raise RuntimeError("最终版本缺少本批反馈文档")
    git(workspace(state), "ls-files", "--error-unmatch", "--", triage["document_path"])
    batch = state["feedback"]["batch_requirement_ids"]
    if pooled["plan"]:
        plan = PoolPlan.model_validate(pooled["plan"])
        validate_pool_plan(plan, routed, set(state["feedback"]["baseline_requirement_ids"]))
        if set(batch) != {row.requirement_id for row in plan.requirements} or batch != _prior(run_dir, "register")["new_ids"]:
            raise RuntimeError("本批完成需求与登记不一致")
        tips: dict[str, set[str]] = {name: set() for name in versions}
        for identifier in batch:
            path = run_dir / "steps" / "requirements" / identifier / "18.json"
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                raise RuntimeError("需求合并结果不能是符号链接")
            merged = _read(path)
            if merged.get("status") != "success" or merged.get("requirement_id") != identifier:
                raise RuntimeError("需求缺少成功合并结果")
            records = {row["name"]: row["tip_sha"] for row in merged["repositories"]}
            if set(records) != set(versions):
                raise RuntimeError("需求合并仓库与当前仓库不一致")
            for name, tip in records.items():
                tips[name].add(tip)
        for name, path in repositories(state):
            if versions[name] not in tips[name] or any(not ancestor(path, tip, versions[name]) for tip in tips[name]):
                raise RuntimeError("最终版本与本批需求合并结果不一致")
        if not ancestor(workspace(state), pooled["tip"], versions["root"]):
            raise RuntimeError("最终版本没有承接本批文档提交")
    elif not report.ready_to_complete or batch or versions != {**triage["versions"], "root": pooled["tip"]}:
        raise RuntimeError("无纳入批次的完成条件或最终版本不一致")
    return _success(run_dir, state, {"versions": versions, "completed_requirement_ids": batch,
                                    "document_path": triage["document_path"], "summary": routed["summary"],
                                    "candidates": triage["candidates"], "dispositions": routed["decisions"],
                                    "requirement_bindings": pooled["plan"], "limitations": triage["limitations"]},
                    "本批处理完成；未纳入与待补充事项按实际处置保留，不代表全部反馈已解决")


async def run_node(run_dir: Path, state: dict[str, Any], *, resume_message: ResumeMessage | None = None) -> dict[str, Any]:
    node = _node(state)
    if node == "completed":
        if not is_completed(state):
            raise RuntimeError("反馈完成状态不一致")
        return _read(node_result_path(run_dir, state))
    if state.get("step") is not None or state.get("current_step") is not None:
        raise RuntimeError("当前是数值需求步骤，请使用需求执行入口")
    path = node_result_path(run_dir, state)
    if path.exists() and node != "select_requirement":
        saved = _read(path)
        if saved.get("status") == "success":
            if saved.get("node") != state["current_node"] or saved.get("phase") != PHASE:
                raise RuntimeError("反馈成功结果与当前节点不一致")
            if resume_message:
                raise RuntimeError("已完成节点不能投递恢复消息")
            return _advance(run_dir, state, saved)
    if state.get("status") == "success":
        updated = copy.deepcopy(state)
        updated["status"] = "running"
        _replace_state(run_dir, state, updated)
    # 保留失败/阻塞状态供公共会话恢复判断，直到实际成功才清除。
    if node in {"prepare", "triage", "route", "pool"}:
        return await {"prepare": _prepare, "triage": _triage, "route": _route, "pool": _pool}[node](run_dir, state, resume_message)
    if resume_message:
        raise RuntimeError("当前节点没有 Agent 会话，不能投递恢复消息")
    return {"register": _register, "select_requirement": _select, "complete": _complete}[node](run_dir, state)


def requirement_evidence(run_dir: Path, state: dict[str, Any]) -> str:
    if state.get("workflow") != WORKFLOW:
        return ""
    identifier = state.get("active_requirement")
    plan = PoolPlan.model_validate(_prior(run_dir, "pool")["plan"])
    binding = next((row for row in plan.requirements if row.requirement_id == identifier), None)
    if binding is None:
        raise RuntimeError("活动反馈需求缺少原反馈归属")
    triage, routed = _prior(run_dir, "triage"), _prior(run_dir, "route")
    owners = {row.candidate_id: row.requirement_id for row in plan.regression_owners}
    decisions = {row["candidate_id"]: row for row in routed["decisions"]}
    related = {}
    for candidate in triage["candidates"]:
        target, seen = candidate["id"], set()
        while target in decisions and decisions[target]["action"] == "covered":
            if target in seen:
                raise RuntimeError("候选归属存在循环")
            seen.add(target)
            target = decisions[target]["covered_by"]
        if target in binding.candidate_ids or target == identifier:
            related[candidate["id"]] = owners.get(target, str(identifier))
    return (
        "以下仅为当前正式需求相关反馈、核验事实与采纳决定，反馈者方案不是唯一实现。"
        "缺陷实际回归原触发任务、状态及受影响路径；改进或新能力验证已采纳的可观察结果与相邻路径。"
        "本需求负责完整回归的候选须在必要依赖完成后证明整体结果，其它项验证自身承接结果。"
        "必要验证失败在当前需求内修复，不先完成合并；不机械重做全产品审计。证据保留在活动TRD及正常交接。\n"
        + json.dumps({"反馈文档": triage["document_path"], "原反馈": [row for row in triage["candidates"] if row["id"] in related],
                      "采纳决定": [row for row in routed["decisions"] if row["candidate_id"] in related],
                      "完整回归归属": related}, ensure_ascii=False)
    )
