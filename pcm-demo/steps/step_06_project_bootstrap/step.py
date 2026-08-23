from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import request_decision
from common.state import step_result_status, write_state, write_step_result
from config import LLMConfig
from steps.step_01_create_workspace.workspace import git, inspect_root_repository
from steps.step_04_assemble_foundation.step import (
    temporary_root,
    verify_existing_success,
    workspace_from_state,
)
from steps.step_05_project_readiness.step import (
    checklist_present,
    load_product_outputs,
    load_selection,
    verify_existing_readiness_success,
)

STEP = 6
NAME = "项目化基础工程"
CURRENT_NODE = "project:06_bootstrap_foundation"
NEXT_NODE = "project:07_solution_design"
CONVERSATION_KEY = "project_bootstrap"
SKILL_NAME = "project-bootstrap"
CHECKLIST = Path("docs/requirements/项目准备清单.md")
MAX_DECISION_ROUNDS = 8
PROJECT_BOOTSTRAP_MAX_TURNS = 48
PROJECT_BOOTSTRAP_MAX_BUDGET_USD = 16.0
LEGACY_COMPLETION_MESSAGES = (
    "已完成 project-bootstrap：基础工程已完成项目化并通过完成条件与工程边界核验。",
)

BOOTSTRAP_DECISION_SYSTEM_PROMPT = """根据最新 Agent 回复判断项目化工作是否完成。

- completed：产品根 README 和各适用工程的项目身份、基础配置、必要文档及安全确认的模板残留已经收口；每个适用工程的依赖安装、检查、测试、构建、启动和基础联调均已真实通过或明确不适用；涉及界面时已用真实浏览器检查代表性页面及阻断性控制台、网络错误；没有本次范围内的失败或未验证项，且未实施业务功能或 Git 写操作。
- continue：项目化、验证或完成证据尚不完整，但可使用已有资料和工具继续完成。
- blocked：只能用于缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务或线下动作。

填写 verdict、answer、reason 和 required_inputs。completed 的 answer 和 required_inputs 为空；continue 必须给出非空 answer 且 required_inputs 为空；blocked 的 answer 为空且 required_inputs 非空。reason 说明判断依据。直接输出结构化结果。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key="project_bootstrap",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=PROJECT_BOOTSTRAP_MAX_TURNS,
    max_budget_usd=PROJECT_BOOTSTRAP_MAX_BUDGET_USD,
    decision_system_prompt=BOOTSTRAP_DECISION_SYSTEM_PROMPT,
    legacy_completion_messages=LEGACY_COMPLETION_MESSAGES,
)
README_REPAIR_PROMPT = "产品根 README 缺失或为空。请仅补齐该文件的项目身份和必要基础运行说明，然后报告结果。"
COVERAGE_ARTIFACT_REPAIR_PROMPT = (
    "检测到未忽略的 .coverage 测试覆盖率数据库。请删除可确认的覆盖率临时产物，"
    "或将它加入所属仓库的 .gitignore；不得把覆盖率数据库作为项目文件保留，然后重新核验并报告。"
)


class ProjectBootstrapBlocked(RuntimeError):
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
    applicable: bool = True,
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": applicable,
        "outputs": outputs or [],
        "blocked": blocked,
        "error": error,
    }


def load_assembly(run_dir: Path) -> dict[str, Any]:
    try:
        assembly = json.loads((run_dir / "steps" / "04.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 4 步组装结果不可读取") from error
    return assembly


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], dict[str, Any], str]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于基础工程项目化锚点")
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
    return workspace, product_outputs, assembly, CHECKLIST.as_posix()


def verify_git_boundaries(workspace: Path, outputs: list[str]) -> None:
    inspect_root_repository(workspace)
    for output in outputs:
        inspect_root_repository(workspace / output)


def coverage_artifact_repair(workspace: Path, outputs: list[str]) -> str | None:
    for relative in [".", *outputs]:
        repository = workspace if relative == "." else workspace / relative
        status = git("status", "--porcelain", "--untracked-files=all", cwd=repository)
        for line in status.splitlines():
            path = line[3:].strip()
            if path == ".coverage" or path.endswith("/.coverage"):
                return COVERAGE_ARTIFACT_REPAIR_PROMPT
    return None


def verify_existing_bootstrap_success(
    run_dir: Path, expected_outputs: list[str]
) -> dict[str, Any]:
    try:
        existing = json.loads((run_dir / "steps" / "06.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 6 步成功结果不可读取") from error
    if (
        existing.get("step") != STEP
        or existing.get("status") != "success"
        or existing.get("applicable") != bool(expected_outputs)
        or existing.get("outputs") != expected_outputs
    ):
        raise RuntimeError("第 6 步成功结果不可复用")
    return existing


def root_readme_repair(workspace: Path) -> str | None:
    path = workspace / "README.md"
    if path.is_symlink():
        raise RuntimeError("产品根 README 不能是符号链接")
    if not path.exists():
        return README_REPAIR_PROMPT
    if not path.is_file():
        raise RuntimeError("产品根 README 必须是普通文件")
    try:
        if not path.read_text(encoding="utf-8").strip():
            return README_REPAIR_PROMPT
    except (OSError, UnicodeError) as error:
        raise RuntimeError("产品根 README 不可读取") from error
    return None


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    outputs: list[str],
) -> dict[str, Any]:
    saved = result(
        "success",
        "project-bootstrap 已完成基础工程项目化和验证。",
        applicable=bool(outputs),
        outputs=outputs,
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


def advance_not_applicable(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    saved = result(
        "success",
        "当前没有适用的基础工程，项目化无副作用跳过。",
        applicable=False,
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
    checklist: str,
) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    project_references = "\n".join(
        f"- @./{output}" for output in assembly.get("outputs", [])
    )
    assembly_json = json.dumps(prompt_assembly(assembly), ensure_ascii=False, indent=2)
    return f"""/project-bootstrap
调用方已授权你直接在当前项目完成有限范围的基础工程项目化，并执行真实安装、检查、测试、构建、启动、浏览器检查和基础联调。

权威产品定义：
{product_references}

项目准备事实：
- @./{checklist}

实际适用工程：
{project_references}

组装白名单事实：
```json
{assembly_json}
```

请依据这些输入和当前工程事实完成产品根 README、适用工程身份、基础配置、必要运行说明及可安全确认的模板残留收口。按锁文件和工程说明完成所有适用的依赖安装、静态或类型检查、测试、构建、启动；验证后端健康与就绪入口，存在前端时用真实浏览器读取代表性页面并检查阻断性控制台和失败网络请求，前后端同时适用时完成最小真实联调。失败先修复本次范围内的问题并重跑。完成前删除本轮测试或模板遗留的未忽略 `.coverage` 覆盖率数据库，或将这类可再生产物加入所属仓库的 `.gitignore`；不得把覆盖率数据库作为项目文件保留。

不得提前实现业务页面、导航、数据模型、业务接口、认证权限、迁移、业务数据、总体技术方案或工程架构；不得初始化、暂存、提交、建分支、合并或推送 Git；不得泄露秘密。最终完整回复须说明处理的工程、主要变更和保留项、每项真实验证结果、浏览器或联调结果，以及未验证范围、阻塞或后续事项。"""


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    workspace, product_outputs, assembly, checklist = validate_inputs(run_dir, state)
    outputs = assembly["outputs"]
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))

    verify_git_boundaries(workspace, outputs)
    if not outputs:
        if position == (STEP + 1, STEP + 1, NEXT_NODE):
            return verify_existing_bootstrap_success(run_dir, outputs)
        return advance_not_applicable(run_dir, state)

    def completion_verifier() -> str | None:
        verified_workspace, _, verified_assembly, _ = validate_inputs(run_dir, state)
        verified_outputs = verified_assembly["outputs"]
        verify_git_boundaries(verified_workspace, verified_outputs)
        readme_repair = root_readme_repair(verified_workspace)
        if readme_repair is not None:
            return readme_repair
        return coverage_artifact_repair(verified_workspace, verified_outputs)

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        verify_existing_bootstrap_success(run_dir, outputs)
        if completion_verifier() is not None:
            raise RuntimeError("第 6 步既有成功缺少非空产品根 README")
        return result(
            "success",
            "project-bootstrap 已完成基础工程项目化和验证，确认既有成功。",
            outputs=outputs,
        )

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于基础工程项目化锚点")

    if step_result_status(run_dir, STEP) == "success":
        verify_existing_bootstrap_success(run_dir, outputs)
        if completion_verifier() is not None:
            raise RuntimeError("第 6 步既有成功缺少非空产品根 README")
        return advance_success(run_dir, state, outputs)

    if state.get("status") != "blocked":
        state.update(
            {"current_step": STEP, "status": "running", "blocked": None, "error": None}
        )
        write_state(run_dir, state)

    decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        DECISION_LOOP_SPEC,
        initial_prompt(product_outputs, assembly, checklist),
        completion_verifier,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
    )
    if decision.verdict == "blocked":
        verified_workspace, _, verified_assembly, _ = validate_inputs(run_dir, state)
        verified_outputs = verified_assembly["outputs"]
        verify_git_boundaries(verified_workspace, verified_outputs)
        if coverage_artifact_repair(verified_workspace, verified_outputs) is not None:
            raise RuntimeError("项目化过程仍包含未删除或未忽略的 .coverage 覆盖率数据库")
        raise ProjectBootstrapBlocked(decision.reason, decision.required_inputs, outputs)
    return advance_success(run_dir, state, outputs)
