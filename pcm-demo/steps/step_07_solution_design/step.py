from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.files import resolve_workspace_output
from common.state import step_result_status, write_state, write_step_result
from config import LLMConfig
from steps.step_04_assemble_foundation.step import (
    temporary_root,
    verify_existing_success,
    workspace_from_state,
)
from steps.step_05_project_readiness.step import (
    checklist_contents,
    checklist_present,
    load_product_outputs,
    load_selection,
    product_output_contents,
    verify_existing_readiness_success,
)
from steps.step_06_project_bootstrap.step import (
    load_assembly,
    verify_existing_bootstrap_success,
    verify_git_boundaries,
)

STEP = 7
NAME = "总体技术方案"
CURRENT_NODE = "project:07_solution_design"
NEXT_NODE = "project:08_initialize_repositories"
CONVERSATION_KEY = "solution_design"
SKILL_NAME = "solution-design"
DESIGN_PATH = Path("docs/design/技术方案.md")
CHECKLIST = Path("docs/requirements/项目准备清单.md")
MAX_DECISION_ROUNDS = 8
SOLUTION_DESIGN_MAX_TURNS = 48
SOLUTION_DESIGN_MAX_BUDGET_USD = 16.0
LEGACY_COMPLETION_MESSAGES = (
    "已完成 solution-design：总体技术方案已生成并通过完成条件与工程事实核验。",
)

SOLUTION_DESIGN_DECISION_RULES = """- completed：固定技术方案文档已写入；基于实际工程事实明确了系统边界、主要技术选择、交付单元、跨单元协作、关键风险和未决事项，并清晰区分工程事实、确认决定、目标、假设和待确认事项；没有把业务实现或 Git 写操作混入工作。
- continue：文档、事实核对或方案内容尚不完整，但可使用已有资料和工具继续完成。
- blocked：只能用于缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务或线下动作。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key="solution_design",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=SOLUTION_DESIGN_MAX_TURNS,
    max_budget_usd=SOLUTION_DESIGN_MAX_BUDGET_USD,
    decision_system_prompt=render_decision_system_prompt(SOLUTION_DESIGN_DECISION_RULES, {}),
    legacy_completion_messages=LEGACY_COMPLETION_MESSAGES,
)
DESIGN_REPAIR_PROMPT = "固定技术方案文档缺失或为空。请仅创建或补全 docs/design/技术方案.md，然后报告结果。"


class SolutionDesignBlocked(RuntimeError):
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


def design_repair(workspace: Path) -> str | None:
    try:
        path = resolve_workspace_output(workspace, DESIGN_PATH.as_posix())
    except ValueError as error:
        raise RuntimeError("技术方案文档路径不符合约定") from error
    current = workspace
    for part in DESIGN_PATH.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError("技术方案文档路径不能包含符号链接")
    if not path.exists():
        return DESIGN_REPAIR_PROMPT
    if not path.is_file():
        raise RuntimeError("技术方案文档必须是普通文件")
    try:
        if not path.read_text(encoding="utf-8").strip():
            return DESIGN_REPAIR_PROMPT
    except (OSError, UnicodeError) as error:
        raise RuntimeError("技术方案文档不可读取") from error
    return None


def design_present(workspace: Path) -> bool:
    return design_repair(workspace) is None


def verify_existing_solution_success(run_dir: Path) -> dict[str, Any]:
    try:
        existing = json.loads((run_dir / "steps" / "07.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 7 步成功结果不可读取") from error
    if (
        existing.get("step") != STEP
        or existing.get("status") != "success"
        or existing.get("applicable") is not True
        or existing.get("outputs") != [DESIGN_PATH.as_posix()]
    ):
        raise RuntimeError("第 7 步成功结果不可复用")
    return existing


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], dict[str, Any], list[str]]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于总体技术方案锚点")
    workspace = workspace_from_state(state)
    product_outputs = load_product_outputs(run_dir, workspace)
    selection = load_selection(run_dir)
    assembly = load_assembly(run_dir)
    verify_existing_success(
        workspace,
        selection,
        assembly,
        temporary_root(workspace, str(state.get("run_id", ""))),
    )
    verify_existing_readiness_success(run_dir)
    if not checklist_present(workspace):
        raise RuntimeError("第 5 步项目准备清单不存在或不可读取")
    outputs = assembly.get("outputs")
    if not isinstance(outputs, list) or any(
        not isinstance(output, str) or not output for output in outputs
    ):
        raise RuntimeError("第 4 步适用工程目录不符合约定")
    verify_existing_bootstrap_success(run_dir, outputs)
    verify_git_boundaries(workspace, outputs)
    return workspace, product_outputs, assembly, outputs


def advance_success(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    saved = result(
        "success",
        "solution-design 已生成总体技术方案并完成工程事实核验。",
        outputs=[DESIGN_PATH.as_posix()],
    )
    write_step_result(run_dir, STEP, saved)
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
    return saved


def prompt_assembly(assembly: dict[str, Any]) -> dict[str, Any]:
    visible: dict[str, Any] = {}
    for target, entry in (assembly.get("assembly") or {}).items():
        if entry is None:
            visible[target] = None
            continue
        if not isinstance(entry, dict):
            raise RuntimeError("第 4 步组装来源不符合约定")
        visible[target] = {
            key: entry.get(key)
            for key in (
                "target",
                "id",
                "default_branch",
                "path",
                "branch",
                "commit_sha",
            )
        }
    return visible


def initial_prompt(
    product_outputs: list[str],
    assembly: dict[str, Any],
    outputs: list[str],
) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    project_references = "\n".join(f"- @./{output}" for output in outputs)
    assembly_json = json.dumps(prompt_assembly(assembly), ensure_ascii=False, indent=2)
    return f"""/solution-design
调用方已授权你直接在当前项目创建或更新总体技术方案文档。请基于真实工程事实完成设计，不实施业务功能。

权威产品定义：
{product_references}

项目准备事实：
- @./{CHECKLIST.as_posix()}

实际适用工程：
{project_references}

组装白名单事实：
```json
{assembly_json}
```

读取足以支撑方案主张的产品定义、准备清单、已有文档和实际工程事实，创建或更新唯一固定产物 `docs/design/技术方案.md`。文档必须区分当前工程事实、已确认决定、目标状态、假设和待确认事项；明确系统上下文与边界、交付单元和职责、数据所有权与依赖方向、跨单元关键流程及协作方式；记录主要技术取舍的理由、代价、替代方案和重新讨论条件，以及有影响范围的风险和未决事项。方案须与已组装、已项目化的工程一致，不重新选择模板或组装工程。

不得实现或修改业务代码、工程配置、迁移或基础设施；不得初始化、暂存、提交、建分支、合并或推送 Git；不得泄露秘密。最终完整回复须列出文档路径、支撑方案的工程事实、确认的边界与选择、风险假设未决事项、未验证范围，以及本轮未执行的实现或 Git 操作。"""


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    workspace, product_outputs, assembly, outputs = validate_inputs(run_dir, state)
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))

    def completion_verifier() -> str | None:
        verified_workspace, _, _, _ = validate_inputs(run_dir, state)
        return design_repair(verified_workspace)

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        verify_existing_solution_success(run_dir)
        if completion_verifier() is not None:
            raise RuntimeError("第 7 步既有成功缺少非空技术方案文档")
        return result(
            "success",
            "solution-design 已生成总体技术方案，确认既有成功。",
            outputs=[DESIGN_PATH.as_posix()],
        )

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于总体技术方案锚点")

    if step_result_status(run_dir, STEP) == "success":
        verify_existing_solution_success(run_dir)
        if completion_verifier() is not None:
            raise RuntimeError("第 7 步既有成功缺少非空技术方案文档")
        return advance_success(run_dir, state)

    if state.get("status") != "blocked":
        state.update(
            {"current_step": STEP, "status": "running", "blocked": None, "error": None}
        )
        write_state(run_dir, state)

    checklist_content = checklist_contents(workspace)
    if checklist_content is None:
        raise RuntimeError("第 5 步项目准备清单不存在或不可读取")
    decision_spec = replace(
        DECISION_LOOP_SPEC,
        decision_system_prompt=render_decision_system_prompt(
            SOLUTION_DESIGN_DECISION_RULES,
            {
                "产品定义": product_output_contents(workspace, product_outputs),
                "项目准备清单": checklist_content,
                "适用工程": outputs,
                "组装白名单事实": prompt_assembly(assembly),
            },
        ),
    )
    decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        decision_spec,
        initial_prompt(product_outputs, assembly, outputs),
        completion_verifier,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
    )
    if decision.verdict == "blocked":
        validate_inputs(run_dir, state)
        raise SolutionDesignBlocked(
            decision.reason,
            decision.required_inputs,
            [DESIGN_PATH.as_posix()] if design_repair(workspace) is None else [],
        )
    return advance_success(run_dir, state)
