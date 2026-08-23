from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.files import resolve_workspace_output
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

PROJECT_READINESS_DECISION_RULES = """completed 表示项目准备清单已经生成，且当前产品定义、实际工程和可用开发资源足以确认进入基础工程项目化前的条件。
continue 表示还需给出明确指令以核验、补全或修复项目准备清单。
blocked 仅表示缺少当前环境无法取得的真实外部账号、凭据、私有数据、客户授权、专用设备、素材、付费服务或线下动作。"""

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


def verify_existing_readiness_success(run_dir: Path) -> dict[str, Any]:
    try:
        existing = json.loads((run_dir / "steps" / "05.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 5 步成功结果不可读取") from error
    if (
        existing.get("step") != STEP
        or existing.get("status") != "success"
        or existing.get("outputs") != [CHECKLIST.as_posix()]
    ):
        raise RuntimeError("第 5 步成功结果不可复用")
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
请创建或更新 `docs/requirements/项目准备清单.md`。

以下产品定义是当前产品范围的权威输入：
{product_references}

实际工程：
{assembly_references}

基础工程选择的公开事实：
```json
{selection_json}
```

可信开发资源清单：@{resource_list}
可读取该清单，并可使用其中已有的开发和测试资源设置当前项目的本机 `.env`、创建项目专用开发库或可丢弃测试库并进行核验；不得创建生产资源或在清单、回复和日志中披露秘密。

当前只核验进入基础工程项目化前条件。后续的依赖安装、构建、测试、启动、独立 Git 初始化、业务实现和完整验收不属于本次核验，不得作为当前准备阻塞。"""


def completion_repair_prompt() -> str:
    return "请生成或补全非空项目准备清单：docs/requirements/项目准备清单.md。"


def advance_success(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
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
        "success", "project-readiness 已生成项目准备清单。", outputs=[CHECKLIST.as_posix()]
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
        verify_existing_readiness_success(run_dir)
        return result(
            "success",
            "project-readiness 已生成项目准备清单，确认既有成功。",
            outputs=[CHECKLIST.as_posix()],
        )

    if (
        position == (STEP, STEP, CURRENT_NODE)
        and checklist is not None
        and step_result_status(run_dir, STEP) == "success"
    ):
        existing = verify_existing_readiness_success(run_dir)
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
    return advance_success(run_dir, state)
