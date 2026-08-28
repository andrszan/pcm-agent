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
MAX_DECISION_ROUNDS = 6
PROJECT_READINESS_MAX_TURNS = 24
PROJECT_READINESS_MAX_BUDGET_USD = 8.0

PROJECT_READINESS_DECISION_RULES = """completed 表示已经依据已确认最终产品范围建立当前项目周期唯一、完整的准备基线：开发、联调、真实体验验收和交付所需的每个必要条件均已通过实际工具结果或明确确认成为 ready，或有事实依据地判为 not-applicable；不存在必要的 missing、pending 或未验证条件。适用的外部资源已经按既定合同匹配和准备；每项被判为 ready 的外部运行资源，其最终项目运行凭据与资源绑定都已持久化到所属仓库受保护的实际 `.env` 或等价配置，并同步无秘密公开配置示例及说明，后续开发无需重新读取共享资源清单才能使用。即使消费代码稍后实现，只要配置键、归属和用途能够唯一确定，也不能把真实凭据只留在外部资源资料中。包含秘密的实际配置在适用平台上仅当前用户可读写（POSIX 通常为 0600），并使用最终写入配置的运行凭据完成所需最小权限验证；管理凭据、资源说明、Mock、截图、清单文字或 Agent 自述不能单独证明 ready。没有提前实施业务功能、完整最终验收、发布或 Git 写操作。
continue 表示仍有可使用现有资料和工具安全完成的资源匹配、准备、项目凭据持久化、公开配置键合同、文件权限、最小权限验证或证据补全工作，或者当前回复不足以证明上述完成条件。
blocked 仅表示最终范围的必要条件仍为 missing 或 pending，且只能由当前环境无法取得的真实外部账号、运行凭据、私有数据、客户授权、专用设备、素材、付费服务、外部决定或线下动作解除；required_inputs 必须说明具体缺口和复验条件。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key="project_readiness",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=PROJECT_READINESS_MAX_TURNS,
    max_budget_usd=PROJECT_READINESS_MAX_BUDGET_USD,
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
请建立当前项目周期唯一的完整准备基线，并创建 `docs/requirements/项目准备清单.md` 作为实际准备结果的脱敏记录；清单文字不能为 ready 状态自证。

以下产品定义是当前最终产品范围的权威输入：
{product_references}

实际工程：
{assembly_references}

基础工程选择的公开事实：
```json
{selection_json}
```

可信开发资源清单：@{resource_list}
该清单是任意格式的动态候选池，不预设其中的资源类型、字段、服务名称或环境变量。请先从最终产品范围和当前工程事实推导开发、联调、真实体验验收和交付所需的全部不可替代条件，再按既定能力、兼容、安全、成本和运行边界匹配候选；改变产品或技术合同的替代不能静默采用。

在调用方授权、项目配置合同和安全边界允许时，实际准备项目专用且环境隔离的开发/测试资源与最小权限运行凭据。对每项最终范围需要且准备完成的外部运行资源，必须把最终项目运行凭据和资源绑定持久化到所属仓库被 Git 忽略的实际 `.env` 或等价受保护配置，确保后续开发无需重新读取共享资源清单即可使用；即使消费代码稍后实现，只要配置键、归属和用途能够由已确认技术合同、资源合同或工程惯例唯一确定，也应先建立最小配置键合同，不能把真实凭据只留在可信资源资料中。同步不含秘密的 `.env.example` 或既有公开配置示例，并参考资源资料中的公开说明补充必要注意事项和用法；包含秘密的实际配置在适用平台上必须仅当前用户可读写（POSIX 通常为 `0600`）。必须使用最终写入项目配置的运行凭据验证身份、权限和所需最小读写能力，不能用管理凭据、资源说明、Mock、截图或文档自述替代。

任何最终范围必要条件仍为 missing、pending 或没有真实核验证据时，都必须明确报告阻塞、实际影响、所需外部输入和复验方式，不得以“以后再准备”为由宣称完成。完整依赖安装、构建、测试、应用启动、基础联调、业务实现、最终体验验收和发布执行由后续工作完成，本次不提前实施；但它们所需的资源、身份、数据、浏览器、视口、回调、权限和其它前置条件必须纳入当前准备基线。

不得创建生产资源、未授权付费或不可逆资源，不得泄露秘密、改变既有 Git 边界，或执行 Git 暂存、提交、分支、合并、push。"""


def completion_repair_prompt() -> str:
    return (
        "项目准备清单缺失或为空。请重新核对最终产品范围、当前工程配置合同和可信资源资料，"
        "继续完成所有可安全执行的资源准备、每项 ready 外部资源的项目凭据持久化、受保护实际配置与无秘密公开示例同步、文件权限和最终运行凭据最小权限验证，"
        "再将脱敏证据写入 docs/requirements/项目准备清单.md。不要只补文档后宣称完成；"
        "任何必要条件仍缺失、待确认或未验证时，必须明确报告阻塞和复验条件。"
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
        "project-readiness 已建立并验证当前项目周期的完整准备基线。",
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
        return result(
            "success",
            "project-readiness 已建立完整准备基线，确认既有成功。",
            outputs=[CHECKLIST.as_posix()],
            readiness_baseline=existing["readiness_baseline"],
        )

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
