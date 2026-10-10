from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, ResumeMessage, run_agent_decision_loop
from common.claude_agent import run_claude
from common.coordination import acquire_lock
from common.decision import render_decision_system_prompt, request_decision
from common.files import resolve_workspace_output, sha256, write_json
from common.frontend_scope import (
    PROTOTYPE_ENTRY,
    LegacyFrontendContractError,
    classify_frontend_scope,
    ensure_frontend_capabilities,
    validate_frontend_scope,
    validate_prototype,
)
from common.state import write_state, write_step_result
from config import LLMConfig
from steps.step_01_create_workspace import inspect_root_repository

STEP = 2
NAME = "项目需求与产品定义"
PHASE = "project_initialization"
CURRENT_NODE = "project:02_intake"
NEXT_NODE = "project:03_foundation_selection"
CONVERSATION_KEY = "project_intake"
SKILL_NAME = "project-intake"
OUTPUTS = (
    Path("docs/requirements/项目需求说明.md"),
    Path("docs/requirements/产品功能说明.md"),
)
MAX_DECISION_ROUNDS = 32
PROJECT_INTAKE_MAX_TURNS = 9999

PROJECT_INTAKE_DECISION_RULES = """- completed：表示两份正式产品定义文档已经生成，且当前事实足以确认其非空并可用。
- continue：表示还需给出明确指令以澄清产品或完成、修复这两份文档。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key="project_intake",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=PROJECT_INTAKE_MAX_TURNS,
    task="project_intake",
    decision_system_prompt=render_decision_system_prompt(PROJECT_INTAKE_DECISION_RULES, {}),
    legacy_completion_messages=(
        "已完成 project-intake：两份正式产品定义文档已生成并通过文件事实核验。",
    ),
)


PROTOTYPE_DECISION_RULES = """- completed：Agent 已完成可操作 HTML 产品原型、浏览器检查、独立体验评审和必要精修，并交接实际模拟边界；两份产品文档与原型一致。
- continue：仍需完成原型、修复文件或收敛授权内的行为与体验；明确给出可执行指令。
- 负责人处理流程语义、产品取舍和交接，不读取截图重做视觉验收，也不要求真人确认原型。"""

PROTOTYPE_LOOP_SPEC = AgentDecisionLoopSpec(
    key="product_prototype",
    state_key="product_prototype",
    skill_name="frontend-ui-ux",
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=PROJECT_INTAKE_MAX_TURNS,
    task="development",
    decision_system_prompt=render_decision_system_prompt(PROTOTYPE_DECISION_RULES, {}),
)


class ProjectIntakeBlocked(RuntimeError):
    def __init__(
        self, reason: str, required_inputs: list[str],
        prototype: dict[str, Any] | None = None,
    ):
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.prototype = prototype


def result(
    status: str,
    summary: str,
    *,
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
    prototype: dict[str, Any] | None = None,
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
        **({"prototype": validate_prototype(prototype)} if prototype is not None else {}),
    }


def trust_project(workspace: Path) -> None:
    claude_json = Path.home() / ".claude.json"
    lock_path = Path.home() / ".claude" / ".pcm-config.lock"
    with acquire_lock(
        lock_path,
        name="Claude 用户配置锁",
        metadata={"kind": "claude-user-config", "pid": os.getpid()},
    ):
        data: dict[str, Any] = {}
        if claude_json.is_file():
            data = json.loads(claude_json.read_text(encoding="utf-8"))
        projects = data.setdefault("projects", {})
        project = projects.setdefault(str(workspace), {})
        project["hasTrustDialogAccepted"] = True
        write_json(claude_json, data)


def _has_valid_entry_position(state: dict[str, Any]) -> bool:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if state.get("phase") == PHASE and position == (STEP, STEP, CURRENT_NODE):
        return True
    return (
        state.get("phase") is None
        and state.get("step") is None
        and state.get("current_node") is None
        and state.get("current_step") in {1, STEP}
    )


def _is_legacy_completed_position(state: dict[str, Any]) -> bool:
    return (
        state.get("phase") is None
        and state.get("step") is None
        and state.get("current_node") is None
        and state.get("current_step") == STEP
        and state.get("status") == "success"
    )


def validate_inputs(run_dir: Path, state: dict[str, Any]) -> tuple[Path, Path]:
    if not _has_valid_entry_position(state) or state.get("publication_phase") != "git_initialized":
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
    expected_hash = state["input"]["source_sha256"]
    if sha256(draft) != expected_hash:
        raise RuntimeError("项目内产品初稿与运行记录不一致")
    published_path = state.get("input", {}).get("published_path")
    if (
        not isinstance(published_path, str)
        or Path(published_path).resolve() != draft.resolve()
    ):
        raise RuntimeError("第 1 步 published_path 与产物结果不一致")
    return workspace, draft


def draft_contents(draft: Path) -> str:
    """读取已经通过输入核验的产品初稿正文。"""

    try:
        return draft.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError("产品初稿不可读取") from error


def output_contents(
    workspace: Path, paths: tuple[Path, ...] = OUTPUTS
) -> dict[str, str] | None:
    """返回可用产物正文；缺失或空文件可修复，路径异常必须失败。"""

    contents: dict[str, str] = {}
    incomplete = False
    for relative in paths:
        current = workspace
        for index, part in enumerate(relative.parts):
            current /= part
            if current.is_symlink():
                raise RuntimeError("产品定义或原型产物路径不能包含符号链接")
            if index < len(relative.parts) - 1 and current.exists() and not current.is_dir():
                raise RuntimeError("产品定义或原型产物父路径与预期目录冲突")
        if not current.exists():
            incomplete = True
            continue
        if not current.is_file():
            raise RuntimeError("产品定义或原型产物不是普通文件")
        try:
            content = current.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise RuntimeError("产品定义或原型产物不可读取") from error
        if not content.strip():
            incomplete = True
            continue
        contents[relative.as_posix()] = content
    return None if incomplete else contents


def validate_existing_contract(run_dir: Path, state: dict[str, Any]) -> None:
    """CLI 在任何失败回写前调用；只拒绝当前节点的不兼容成功，不迁移历史。"""

    if not _has_valid_entry_position(state):
        return
    path = run_dir / "steps/02.json"
    # 第 1 步成功也会把当前位置推进到本节点；不能把尚无 02.json 当作旧成功。
    current_success = _is_legacy_completed_position(state) or (
        state.get("status") == "success"
        and state.get("current_node") == CURRENT_NODE
        and path.is_file()
    )
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        if current_success:
            raise LegacyFrontendContractError("当前第 2 步成功结果不可读取；请使用原版本收口旧运行") from error
        raise RuntimeError("第 2 步结果不可读取") from error
    if isinstance(existing, dict) and existing.get("status") == "success":
        try:
            validate_prototype(existing.get("prototype"))
        except (ValueError, RuntimeError, TypeError) as error:
            raise LegacyFrontendContractError(
                "当前第 2 步旧 success 缺少有效 prototype 合同；请使用原版本收口旧运行"
            ) from error
    elif current_success:
        raise LegacyFrontendContractError("当前第 2 步成功状态缺少有效 prototype 结果；请使用原版本收口旧运行")


def verify_existing_intake_success(run_dir: Path) -> dict[str, Any]:
    try:
        existing = json.loads((run_dir / "steps" / "02.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 2 步成功结果不可读取") from error
    if (
        existing.get("step") != STEP
        or existing.get("status") != "success"
        or existing.get("outputs") != [path.as_posix() for path in OUTPUTS]
    ):
        raise RuntimeError("第 2 步成功结果不可复用")
    validate_prototype(existing.get("prototype"))
    return existing


def initial_resources_reference(state: dict[str, Any], workspace: Path) -> str | None:
    record = state.get("initial_resources")
    if record is None:
        return None
    if not isinstance(record, dict):
        raise RuntimeError("初始资料运行记录无效")
    basename = record.get("basename")
    published_path = record.get("published_path")
    if (
        not isinstance(basename, str)
        or not basename
        or not isinstance(published_path, str)
    ):
        raise RuntimeError("初始资料运行记录不完整")
    relative = Path("initial-resources") / basename
    expected = workspace.resolve() / relative
    actual = Path(published_path)
    if actual.resolve() != expected or actual.is_symlink() or not actual.exists():
        raise RuntimeError("第 1 步发布的初始资料副本不存在或与运行记录不一致")
    if not (actual.is_file() or actual.is_dir()):
        raise RuntimeError("第 1 步发布的初始资料副本不是普通文件或目录")
    return relative.as_posix()


def initial_prompt(
    draft: Path, workspace: Path, initial_resources: str | None = None
) -> str:
    reference = draft.relative_to(workspace).as_posix()
    outputs = "\n".join(f"- `{path.as_posix()}`" for path in OUTPUTS)
    resource_guidance = ""
    if initial_resources:
        resource_guidance = f"""
已导入补充资料：`./{initial_resources}`。请按需阅读，并依据本 Skill 将对产品定义有影响的结论写入正式文档。"""
    return f"""/project-intake @./{reference}
以产品初稿为当前产品定义的权威输入，持续澄清并形成以下两份非空正式文档：
{outputs}{resource_guidance}
只处理产品定义文档，不要处理后续工程实现。"""


def completion_repair_prompt() -> str:
    paths = "、".join(path.as_posix() for path in OUTPUTS)
    return f"请生成或补全两份非空正式产品定义文档：{paths}。"


def prototype_prompt(initial_resources: str | None = None) -> str:
    resources = f"\n原始补充资料位于 `./{initial_resources}`，按需读取，不改写原件。" if initial_resources else ""
    return f"""/frontend-ui-ux
实际通过 Skill 工具调用 `/ui-ux-pro-max:ui-ux-pro-max`，完成 HTML 产品原型。
读取两份产品定义 `docs/requirements/项目需求说明.md`、`docs/requirements/产品功能说明.md`，以及工作区规则、已有品牌约束和适用资源。{resources}
首次视觉方向选择由 frontend-ui-ux 规则处理：继承已有品牌和已确认方向；没有既定品牌或视觉方向时，结合产品、用户与核心任务比较少量实质不同的方案后自主选定一个，再制作原型。可按需借用已有本地主题参考，不要求多套完整 HTML，不新增方向报告，不等待真人批准。
使用原生 HTML/CSS/JavaScript，不调用依赖 Tailwind 工程的主题 Skill，固定入口 `{PROTOTYPE_ENTRY.as_posix()}`，其它页面、样式、脚本和正式资产放在同目录。
覆盖主要页面、导航、核心任务及代表性加载、空态、失败、权限、冲突、成功与恢复状态；只处理实际适用状态。
不初始化正式框架工程，不在 frontend/ 或 backend/ 写业务代码。页面使用正式业务内容，不出现演示、模拟数据或待接接口等过程说明；实际模拟边界在交接中明确。
允许修正两份产品文档中已授权的行为澄清、术语和一致性问题；产品功能说明提供原型入口及需要长期保留的交互决定。不增加第三份产品定义、manifest 或全量逐页规格。
不改写产品初稿及导入原始资料，不擅自增减产品承诺；实质范围变化在原对话中交给负责人决定并同步有效正文。
静态预览严格复用 `.pcm/runtime.json` 的 frontend host、port、endpoint。未知占用按冲突处理，不换端口或停止未知进程；交接前释放本任务明确启动的预览服务。
完成浏览器操作和实际渲染检查，覆盖目标视口与基本可访问性；进行独立体验评审和必要定向精修。按工作区约定把验收截图放入忽略目录，不作为正式资产。
专业子任务写清产品目标、设计依据、行为、范围、验证及完整插件调用要求，并确保接收方具备 Skill 工具；独立评审由具备相应能力的角色完成。
不提交、不 push。报告原型入口、与文档的一致性、浏览器验证、独立评审与精修结果、实际模拟范围和未验证项。"""


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
    resume_message: ResumeMessage | None = None,
) -> dict[str, Any]:
    validate_existing_contract(run_dir, state)
    workspace, draft = validate_inputs(run_dir, state)
    initial_resources = initial_resources_reference(state, workspace)
    existing_outputs = output_contents(workspace)
    existing = None
    if (run_dir / "steps" / "02.json").is_file():
        try:
            existing = verify_existing_intake_success(run_dir)
        except RuntimeError:
            existing = None
        if existing is not None:
            prototype = validate_prototype(existing["prototype"])
            recorded = state.get("project_intake", {}).get("prototype")
            if recorded is not None and validate_prototype(recorded) != prototype:
                raise RuntimeError("原型适用性记录与成功结果不一致")
        if existing is not None and existing_outputs is not None and (
            not prototype["applicable"] or output_contents(workspace, (PROTOTYPE_ENTRY,)) is not None
        ):
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
            return existing
    if existing is not None:
        state.setdefault("project_intake", {})["prototype"] = prototype

    state.update(
        {
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
        }
    )
    write_state(run_dir, state)
    trust_project(workspace)
    if state.get("status") != "blocked":
        state.update({"status": "running", "blocked": None, "error": None})
        write_state(run_dir, state)

    def verify_completed() -> str | None:
        validate_inputs(run_dir, state)
        if output_contents(workspace) is None:
            return completion_repair_prompt()
        return None

    decision_spec = replace(
        DECISION_LOOP_SPEC,
        decision_system_prompt=render_decision_system_prompt(
            PROJECT_INTAKE_DECISION_RULES,
            {
                "产品初稿": {
                    "path": draft.relative_to(workspace).as_posix(),
                    "content": draft_contents(draft),
                },
                "目标产品定义文档": [path.as_posix() for path in OUTPUTS],
                **(
                    {"已导入补充资料": {"path": initial_resources}}
                    if initial_resources is not None
                    else {}
                ),
            },
        ),
    )
    decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        decision_spec,
        initial_prompt(draft, workspace, initial_resources),
        verify_completed,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
        resume_message=resume_message,
    )
    if decision.verdict == "blocked":
        raise ProjectIntakeBlocked(decision.reason, decision.required_inputs)
    if decision.verdict != "completed":
        raise RuntimeError("Agent 决策循环未返回完成或阻塞结论")

    section = state.setdefault("project_intake", {})
    if "prototype" in section:
        prototype = validate_prototype(section["prototype"])
    else:
        documents = output_contents(workspace)
        scope = validate_frontend_scope(await classify_frontend_scope(
            config_loader(), purpose="prototype",
            context=json.dumps(documents, ensure_ascii=False),
        ))
        prototype = validate_prototype({
            **scope,
            "entry": PROTOTYPE_ENTRY.as_posix() if scope["applicable"] else None,
        })
        section["prototype"] = prototype
        write_state(run_dir, state)

    if prototype["applicable"]:
        ensure_frontend_capabilities(workspace)
        if state.get("status") == "blocked" and state.get("claude_sessions", {}).get("product_prototype") is None:
            # 文档域阻塞已解决；已有原型阻塞仍交给原循环自动恢复。
            state.update({"status": "running", "blocked": None, "error": None})
            write_state(run_dir, state)

        def verify_prototype_completed() -> str | None:
            validate_inputs(run_dir, state)
            if output_contents(workspace) is None:
                return completion_repair_prompt()
            if output_contents(workspace, (PROTOTYPE_ENTRY,)) is None:
                return f"请在原会话补全可读、非空的 HTML 原型入口 {PROTOTYPE_ENTRY.as_posix()}，并复核与两份产品定义的一致性。"
            return None

        prototype_spec = replace(
            PROTOTYPE_LOOP_SPEC,
            decision_system_prompt=render_decision_system_prompt(
                PROTOTYPE_DECISION_RULES,
                {
                    "产品定义": output_contents(workspace),
                    "原型交接": prototype,
                    **({"已导入补充资料": {"path": initial_resources}} if initial_resources else {}),
                },
            ),
        )
        decision = await run_agent_decision_loop(
            run_dir, state, workspace, prototype_spec,
            prototype_prompt(initial_resources), verify_prototype_completed,
            agent_runner=agent_runner, decision_runner=decision_runner,
            config_loader=config_loader, resume_message=resume_message,
        )
        if decision.verdict == "blocked":
            raise ProjectIntakeBlocked(decision.reason, decision.required_inputs, prototype)
        if decision.verdict != "completed":
            raise RuntimeError("原型决策循环未返回完成或阻塞结论")

    completed = result(
        "success",
        "产品定义文档与适用的 HTML 原型已完成。",
        outputs=[relative.as_posix() for relative in OUTPUTS],
        prototype=prototype,
    )
    write_step_result(run_dir, STEP, completed)
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
    return completed
