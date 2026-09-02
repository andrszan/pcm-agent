from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.files import resolve_workspace_output, sha256
from common.state import step_result_status, write_state, write_step_result
from config import LLMConfig, load_dev_resource_list
from steps.step_03_foundation_selection.step import FoundationSelectionResult
from steps.step_04_assemble_foundation.step import (
    temporary_root,
    verify_existing_success,
    workspace_from_state,
)

STEP = 5
NAME = "核验项目准备状态"
CURRENT_NODE = "project:05_verify_readiness"
NEXT_NODE = "project:06_bootstrap_foundation"
CONVERSATION_KEY = "project_readiness"
SKILL_NAME = "project-readiness"
CHECKLIST = Path("docs/requirements/项目准备清单.md")
MAX_DECISION_ROUNDS = 16
PROJECT_READINESS_MAX_TURNS = 100
READINESS_SCOPE_CONTRACT = "development-external-resources-v3"

PROJECT_READINESS_DECISION_RULES = """completed 表示当前开发的资源准备基线已经建立：清单只纳入完成编码、开发环境联调和开发环境真实验收所需，且必须由调用方提供或授权的外部服务、账号、凭据、授权素材、私有数据或专用设备；每项已纳入的开发必需外部资源均已真实可用。匹配候选前已优先验证实际受保护配置中现有的非空运行凭据与资源绑定；满足当前开发合同时原样保留，不使用候选池中的维护、共享或更宽权限身份替换，也不把候选凭据的探针结果误记为最终项目凭据结果。清单中的资源匹配和脱敏证据只描述最终选定绑定、兼容依据及最终凭据的实际结果，不得提及、比较或说明任何未采用候选，包括“未使用候选管理身份”之类否定表述。每项 ready 外部运行资源的最终项目凭据与资源绑定都已持久化到所属仓库受保护的实际 `.env` 或等价配置，公开键合同已同步，含秘密文件权限安全（POSIX 通常为 0600），并使用最终写入配置的运行凭据完成最小行为和隔离验证。不存在以下两类阻塞：开发必需外部资源在候选池中缺失、当前环境无法安全生成且无兼容替代；已匹配资源真实不可用、凭据无效、权限不足、隔离不合格，或缺少开发所需接口能力、可用配额、回调/白名单及其它既定能力。依赖安装、业务实现、migration、Seed、产品内账号、完整联调和浏览器验收属于后续开发工作；只服务生产部署或生产运行的正式域名、DNS/TLS、生产资源与凭据、生产回调与配额、监控、备份、容量和发布安全属于清单准入范围外。项目准备清单不是范围外事项账本，正文任何位置都不得列举、命名或汇总这些事项，也不得借“未纳入清单”“范围外”“未来事项”“非阻塞”或 `not-applicable` 等章节、说明或状态保留它们。是否纳入按当前开发用途判断，开发 SMTP TLS、localhost 回调、开发白名单、沙箱范围和开发配额仍属于开发资源能力。权限与隔离按最终凭据的实际可见范围和行为判断：服务不支持派生项目身份时，只有非管理、非生产的共享开发身份，且调用方明确授权、作用范围满足开发合同，才可以兼容使用；共享管理或根凭据、生产身份、能够访问合同外资源的身份不得写入应用配置，无法派生合格开发身份时属于第二类阻塞。列表接口只返回获授权项目资源且范围外访问被拒绝时，不因接口成功本身误判越权。清单正文任何位置仍提及纯生产事项、非当前必需候选或后续内部工作时不能 completed，即使它们位于“未纳入清单”、范围外说明或无状态汇总中。管理凭据、资源说明、Mock、截图、清单文字或 Agent 自述不能单独证明 ready，且没有执行 Git 写操作。
continue 表示仍有可使用当前资料和工具安全完成的开发资源范围清理、现有项目绑定核验、缺失或失效资源匹配、创建、项目凭据持久化、公开配置键合同、文件权限、最小行为/隔离验证或证据补全工作。实际配置中的现有运行绑定满足开发合同时必须保留，不得用候选池中的维护、共享或更宽权限身份替换；候选池只用于补齐缺失、失效或确实不合格的绑定。清单中不得提及或比较未采用候选，发现“未使用某候选”之类否定表述时也必须删除。清单正文任何位置提及纯生产事项、非当前必需候选或后续内部工作时返回 continue，并删除对应章节、说明和汇总；不得把它们改写为未纳入、范围外、未来事项、非阻塞或无状态记录。产品规则或技术细节尚待设计、业务尚未实现、生产发布条件缺失时，不返回 continue 试图解决这些事项。
blocked 只允许两种情况：一、已确认当前开发必须依赖的外部资源在调用方候选池中不存在、当前环境无法安全生成且没有兼容替代；二、已匹配的开发资源经过真实验证不可用、凭据无效、权限不足、隔离不符合开发要求，或缺少开发所需接口能力、可用配额、回调注册、白名单、沙箱范围及其它既定合同能力。required_inputs 必须精确指出缺少或不可用的开发资源、能力和复验条件；不得包含生产域名、生产回调、生产配额或其它生产发布条件，也不得因业务实现、产品规则待定或未来最终验收返回 blocked。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key="project_readiness",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=PROJECT_READINESS_MAX_TURNS,
    model_tier="high",
    effort="high",
    decision_system_prompt=render_decision_system_prompt(PROJECT_READINESS_DECISION_RULES, {}),
    legacy_completion_messages=(
        "已完成 project-readiness：项目准备清单已生成并通过文件事实核验。",
    ),
)


class ProjectReadinessBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        outputs: list[str] | None = None,
    ):
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.outputs = outputs or []


def result(
    status: str,
    summary: str,
    *,
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
    readiness_baseline: dict[str, Any] | None = None,
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
        "readiness_baseline": readiness_baseline,
    }


def checklist_contents(workspace: Path) -> str | None:
    """返回可用清单；缺失或空内容可修复，路径异常必须失败。"""

    try:
        path = resolve_workspace_output(workspace, CHECKLIST.as_posix())
    except ValueError as error:
        raise RuntimeError("项目准备清单路径不符合约定") from error
    current = workspace.resolve()
    for index, part in enumerate(CHECKLIST.parts):
        current /= part
        if current.is_symlink():
            raise RuntimeError("项目准备清单路径不能包含符号链接")
        if index < len(CHECKLIST.parts) - 1 and current.exists() and not current.is_dir():
            raise RuntimeError("项目准备清单父路径与预期目录冲突")
    if current != path:
        raise RuntimeError("项目准备清单路径与工作区解析不一致")
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError("项目准备清单不是普通文件")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError("项目准备清单不可读取") from error
    return content if content.strip() else None


def checklist_present(workspace: Path) -> bool:
    try:
        return checklist_contents(workspace) is not None
    except RuntimeError:
        return False


def readiness_baseline(
    workspace: Path, product_outputs: list[str]
) -> dict[str, Any]:
    if checklist_contents(workspace) is None:
        raise RuntimeError("项目准备清单不存在或为空")
    try:
        checklist = resolve_workspace_output(workspace, CHECKLIST.as_posix())
        product_hashes = {
            output: sha256(resolve_workspace_output(workspace, output))
            for output in product_outputs
        }
        return {
            "scope_contract": READINESS_SCOPE_CONTRACT,
            "checklist_sha256": sha256(checklist),
            "product_outputs_sha256": product_hashes,
        }
    except (OSError, ValueError) as error:
        raise RuntimeError("项目准备基线证据无法生成") from error


def verify_existing_readiness_success(
    run_dir: Path, workspace: Path, product_outputs: list[str]
) -> dict[str, Any]:
    try:
        existing = json.loads((run_dir / "steps" / "05.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 5 步成功结果不可读取") from error
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
        "readiness_baseline",
    }
    if (
        set(existing) != expected_keys
        or existing.get("step") != STEP
        or existing.get("name") != NAME
        or existing.get("status") != "success"
        or not isinstance(existing.get("summary"), str)
        or not existing["summary"].strip()
        or existing.get("applicable") is not True
        or existing.get("outputs") != [CHECKLIST.as_posix()]
        or existing.get("blocked") is not None
        or existing.get("error") is not None
        or existing.get("readiness_baseline")
        != readiness_baseline(workspace, product_outputs)
    ):
        raise RuntimeError("第 5 步成功结果或准备基线不可复用")
    return existing


def load_product_outputs(run_dir: Path, workspace: Path) -> list[str]:
    try:
        previous = json.loads((run_dir / "steps" / "02.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 2 步产品定义结果不可读取") from error
    outputs = previous.get("outputs")
    if (
        previous.get("step") != 2
        or previous.get("status") != "success"
        or not isinstance(outputs, list)
        or len(outputs) != 2
        or any(not isinstance(output, str) or not output for output in outputs)
    ):
        raise RuntimeError("第 2 步结果缺少两份成功的产品定义产物")
    resolved: list[Path] = []
    for output in outputs:
        relative = Path(output)
        if ".." in relative.parts:
            raise RuntimeError("第 2 步产品定义产物路径不能包含 ..")
        current = workspace
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise RuntimeError("第 2 步产品定义产物路径不能包含符号链接")
        try:
            path = resolve_workspace_output(workspace, output)
        except ValueError as error:
            raise RuntimeError("第 2 步产品定义产物路径不符合约定") from error
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("第 2 步产品定义产物不是非空普通文件")
        resolved.append(path)
    if len({path.resolve() for path in resolved}) != 2:
        raise RuntimeError("第 2 步产品定义产物不能指向同一文件")
    return outputs


def product_output_contents(workspace: Path, outputs: list[str]) -> dict[str, str]:
    """读取已通过路径和非空核验的产品定义正文。"""

    contents: dict[str, str] = {}
    for output in outputs:
        try:
            path = resolve_workspace_output(workspace, output)
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as error:
            raise RuntimeError("第 2 步产品定义产物不可读取") from error
        if not content.strip():
            raise RuntimeError("第 2 步产品定义产物不是非空普通文件")
        contents[output] = content
    return contents


def resource_list_facts(resource_list: Path) -> dict[str, str | bool]:
    """返回已验证资源清单的非敏感位置事实，不读取其正文。"""

    if not resource_list.is_absolute() or resource_list.is_symlink():
        raise RuntimeError("可信开发资源清单必须是非符号链接绝对路径")
    resolved = resource_list.resolve()
    if not resolved.is_file() or resolved.is_symlink() or not os.access(resolved, os.R_OK):
        raise RuntimeError("可信开发资源清单必须是可读的普通文件")
    return {"path": str(resolved), "readable": True}


def load_selection(run_dir: Path) -> FoundationSelectionResult:
    try:
        previous = json.loads((run_dir / "steps" / "03.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 3 步选型结果不可读取") from error
    if previous.get("step") != 3 or previous.get("status") != "success":
        raise RuntimeError("第 3 步选型结果未成功完成")
    try:
        selection_data = previous["template_selection"]
        selection = FoundationSelectionResult.model_validate(selection_data)
    except (KeyError, ValueError) as error:
        raise RuntimeError("第 3 步模板选择不符合约定") from error
    if not isinstance(selection_data, dict):
        raise RuntimeError("第 3 步模板选择不符合约定")
    return selection


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], FoundationSelectionResult, dict[str, Any]]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于项目准备核验锚点")
    workspace = workspace_from_state(state)
    product_outputs = load_product_outputs(run_dir, workspace)
    selection = load_selection(run_dir)
    try:
        assembly = json.loads((run_dir / "steps" / "04.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 4 步组装结果不可读取") from error
    verify_existing_success(
        workspace,
        selection,
        assembly,
        temporary_root(workspace, str(state.get("run_id", ""))),
    )
    return workspace, product_outputs, selection, assembly


def readiness_selection_projection(
    selection: FoundationSelectionResult,
) -> dict[str, dict[str, str | bool | None]]:
    def project(item: Any) -> dict[str, str | bool | None]:
        return {
            "applicable": item is not None,
            "id": item.id if item is not None else None,
            "default_branch": item.default_branch if item is not None else None,
            "path": item.path if item is not None else None,
            "reason": item.reason if item is not None else None,
        }

    return {"frontend": project(selection.frontend), "backend": project(selection.backend)}


def initial_prompt(
    product_outputs: list[str],
    assembly_outputs: list[str],
    selection: FoundationSelectionResult,
    resource_list: Path,
) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    assembly_references = (
        "\n".join(f"- @./{output}" for output in assembly_outputs)
        if assembly_outputs
        else "- 当前产品没有适用的已组装工程。"
    )
    selection_json = json.dumps(
        readiness_selection_projection(selection), ensure_ascii=False, indent=2
    )
    return f"""/project-readiness
请建立当前自动化开发周期唯一的开发资源准备基线，并创建 `docs/requirements/项目准备清单.md` 作为实际资源准备结果的脱敏记录；清单文字不能为 ready 状态自证。

以下产品定义是当前最终产品范围的权威输入：
{product_references}

实际工程：
{assembly_references}

基础工程选择的公开事实：
```json
{selection_json}
```

可信开发资源清单：@{resource_list}
该清单是任意格式的动态候选池，不预设其中的资源类型、字段、服务名称或环境变量。请先检查所属仓库受保护实际配置中已有的非空运行凭据和资源绑定，并使用这些最终配置验证当前身份、权限、隔离和最小行为；已有绑定满足开发合同时必须原样保留，不得用候选池中的维护、共享或更宽权限身份替换，也不得把候选凭据的探针结果当作最终项目凭据结果。项目准备清单中的资源匹配和证据只能描述最终选定绑定，不得提及、比较或说明未采用候选，包括“未使用候选管理身份”之类否定表述。只有实际绑定缺失、失效或验证不合格时，才从产品范围和当前工程事实推导需要调用方提供的外部条件，再按既定能力、兼容、安全和隔离边界匹配候选；改变产品或技术合同的替代不能静默采用。

在调用方授权、项目配置合同和安全边界允许时，优先实际准备项目专用且环境隔离的开发/测试资源与最小权限运行凭据；服务不支持派生项目身份时，只有非管理、非生产的共享开发身份，且调用方明确授权、数据、操作、收件人或其它实际作用范围满足当前开发合同，才可以兼容使用；共享管理或根凭据、生产身份、能够访问合同外资源的身份不得写入应用配置，无法派生合格开发身份时属于第二类阻塞。权限与隔离按最终凭据的实际可见范围和行为判断；列表接口只返回获授权项目资源且范围外访问被拒绝时，不因接口成功本身误判越权。对每项当前开发需要且准备完成的外部运行资源，必须把最终项目运行凭据和资源绑定持久化到所属仓库被 Git 忽略的实际 `.env` 或等价受保护配置，确保后续开发无需重新读取共享资源清单即可使用；即使消费代码稍后实现，只要配置键、归属和用途能够由已确认技术合同、资源合同或工程惯例唯一确定，也应先建立最小配置键合同。同步不含秘密的 `.env.example` 或既有公开配置示例，并参考资源资料中的公开说明补充必要注意事项和用法；包含秘密的实际配置在适用平台上必须仅当前用户可读写（POSIX 通常为 `0600`）。必须使用最终写入项目配置的运行凭据验证身份、权限、隔离和所需最小行为，不能用管理凭据、资源说明、Mock、截图或文档自述替代。

只允许以下两类阻塞：开发必需外部资源在候选池中不存在、当前环境无法安全生成且无兼容替代；或已匹配资源真实验证不可用、凭据无效、权限不足、隔离不合格，或缺少开发所需接口能力、可用配额、回调/白名单、沙箱范围及其它既定能力。项目准备清单只纳入当前编码、开发环境联调或开发环境真实验收所需，且必须由调用方提供或授权的外部资源。依赖安装、业务代码、migration、Seed、项目内测试账号、完整联调和浏览器验收由后续开发完成；只服务生产部署或生产运行的正式域名、DNS/TLS、生产资源与凭据、生产回调与配额、监控、备份恢复、容量和发布安全属于清单准入范围外。范围按实际开发用途判断，开发 SMTP TLS、localhost 回调、开发白名单、沙箱范围和开发配额仍属于可纳入的开发资源能力。项目准备清单只记录通过准入的当前开发必需外部资源，不得在正文任何位置列举或命名前述范围外事项，也不得建立“未纳入清单”、范围外、未来事项、非阻塞、无状态或 `not-applicable` 章节来保留它们；产品规则、隐私保留和其它设计决定同样不写入项目准备清单。

不得创建生产资源、未授权付费或不可逆资源，不得泄露秘密、改变既有 Git 边界，或执行 Git 暂存、提交、分支、合并、push。"""


def completion_repair_prompt() -> str:
    return (
        "项目准备清单缺失或为空。请重新核对当前自动化开发范围、工程配置合同和可信开发资源资料，"
        "继续完成所有可安全执行的开发资源准备、每项 ready 外部资源的项目凭据持久化、受保护实际配置与无秘密公开示例同步、文件权限和最终运行凭据最小行为/隔离验证，"
        "再将脱敏证据写入 docs/requirements/项目准备清单.md。不要只补文档后宣称完成；"
        "只有开发必需外部资源缺失、当前环境无法安全生成且无替代，或已匹配资源不可用、权限/隔离/必要能力/配额/回调/白名单不符合开发合同时才能报告阻塞。只重建当前开发必需外部资源清单；正文任何位置不得列举依赖安装、后续业务实现、产品设计、纯生产事项或其它非当前必需候选，也不得建立“未纳入清单”、范围外、未来事项、非阻塞或无状态章节来保留它们。共享兼容身份必须是调用方明确授权的非管理、非生产开发身份；共享管理或根凭据、生产身份和可访问合同外资源的身份不得作为最终运行凭据。清单只描述最终选定绑定，不得提及或比较未采用候选，也不得保留“未使用某候选”之类否定说明。"
    )


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    workspace: Path,
    product_outputs: list[str],
) -> dict[str, Any]:
    state.update(
        {
            "status": "success",
            "phase": "project_initialization",
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "blocked": None,
            "error": None,
        }
    )
    saved = result(
        "success",
        "project-readiness 已建立并验证当前自动化开发周期的资源准备基线。",
        outputs=[CHECKLIST.as_posix()],
        readiness_baseline=readiness_baseline(workspace, product_outputs),
    )
    write_step_result(run_dir, STEP, saved)
    write_state(run_dir, state)
    return saved


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
    resource_loader=load_dev_resource_list,
) -> dict[str, Any]:
    workspace, product_outputs, selection, assembly = validate_inputs(run_dir, state)
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    checklist = checklist_contents(workspace)

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        if checklist is None:
            raise RuntimeError("第 5 步成功现场不完整")
        existing = verify_existing_readiness_success(
            run_dir, workspace, product_outputs
        )
        return existing

    if (
        position == (STEP, STEP, CURRENT_NODE)
        and checklist is not None
        and step_result_status(run_dir, STEP) == "success"
    ):
        existing = verify_existing_readiness_success(
            run_dir, workspace, product_outputs
        )
        state.update(
            {
                "status": "success",
                "phase": "project_initialization",
                "step": STEP + 1,
                "current_step": STEP + 1,
                "current_node": NEXT_NODE,
                "blocked": None,
                "error": None,
            }
        )
        write_state(run_dir, state)
        return existing

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于项目准备核验锚点")

    resource_list, _ = resource_loader()
    resource_facts = resource_list_facts(resource_list)
    decision_spec = replace(
        DECISION_LOOP_SPEC,
        decision_system_prompt=render_decision_system_prompt(
            PROJECT_READINESS_DECISION_RULES,
            {
                "产品定义": product_output_contents(workspace, product_outputs),
                "适用工程": assembly["outputs"],
                "基础工程选择": readiness_selection_projection(selection),
                "可信开发资源清单": resource_facts,
            },
        ),
    )
    if state.get("status") != "blocked":
        state.update(
            {"current_step": STEP, "status": "running", "blocked": None, "error": None}
        )
        write_state(run_dir, state)

    def verify_completed() -> str | None:
        validate_inputs(run_dir, state)
        if checklist_contents(workspace) is None:
            return completion_repair_prompt()
        return None

    decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        decision_spec,
        initial_prompt(product_outputs, assembly["outputs"], selection, resource_list),
        verify_completed,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
    )
    if decision.verdict == "blocked":
        validate_inputs(run_dir, state)
        raise ProjectReadinessBlocked(
            decision.reason,
            decision.required_inputs,
            [CHECKLIST.as_posix()] if checklist_present(workspace) else [],
        )
    if decision.verdict != "completed":
        raise RuntimeError("Agent 决策循环未返回完成或阻塞结论")
    return advance_success(run_dir, state, workspace, product_outputs)
