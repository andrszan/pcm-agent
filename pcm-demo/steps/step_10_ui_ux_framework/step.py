from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.files import resolve_workspace_output
from common.state import step_result_status, write_state, write_step_result
from config import LLMConfig
from steps.step_05_project_readiness.step import (
    CHECKLIST,
    checklist_contents,
    load_product_outputs,
    product_output_contents,
    verify_existing_readiness_success,
)
from steps.step_07_solution_design.step import (
    DESIGN_PATH,
    verify_existing_solution_success,
)

STEP = 10
NAME = "产品级 UI/UX 框架"
CURRENT_NODE = "project:10_ui_ux_framework"
NEXT_NODE = "project:11_requirement_breakdown"
CONVERSATION_KEY = "ui_ux_framework"
SKILL_NAME = "ui-ux-framework"
FRAMEWORK_PATH = Path("docs/ui-ux/framework.md")
ARCHITECTURE_OUTPUT_PATH = Path("docs/design/工程架构设计.md")
MAX_DECISION_ROUNDS = 8
UI_UX_FRAMEWORK_MAX_TURNS = 48
UI_UX_FRAMEWORK_MAX_BUDGET_USD = 16.0

FRAMEWORK_REPAIR_PROMPT = (
    "固定产品级 UI/UX 框架文档缺失或为空。请仅创建或补全 "
    "docs/ui-ux/framework.md；不得修改任何其他文件，不得执行 Git 写操作，然后报告结果。"
)
COMMIT_REPAIR_PROMPT = """/commit-changes
只授权处理产品根 Git 仓库中的固定文档 `docs/ui-ux/framework.md`。请核验该文档；仅当它存在未提交变更时，暂存并提交这一个文件，然后确认产品根仓库工作区干净。不得暂存、提交或修改任何其他路径，不得处理子仓库，不得建分支、改写历史或 push。若固定文档相对当前提交没有变化，直接报告无变更，不得制造变更。"""

UI_UX_FRAMEWORK_DECISION_RULES = """- completed：固定产品级 UI/UX 框架文档已生成，基于权威产品定义、项目准备清单、总体技术方案、工程架构设计和实际前端工程，明确产品级体验原则、信息与交互框架、跨需求一致性约束、可访问性及响应式基线、设计资产与协作边界，并区分工程事实、确认决定、目标、假设和待确认事项；没有越界开展单项需求或页面实现。
- continue：框架文档、前端工程事实核验或关键体验方向仍可在当前项目中补全。
- blocked：只能用于缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务或线下动作。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key=CONVERSATION_KEY,
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=UI_UX_FRAMEWORK_MAX_TURNS,
    max_budget_usd=UI_UX_FRAMEWORK_MAX_BUDGET_USD,
    decision_system_prompt=render_decision_system_prompt(UI_UX_FRAMEWORK_DECISION_RULES, {}),
)


class UIUXFrameworkBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        outputs: list[str] | None = None,
    ) -> None:
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


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


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
        raise RuntimeError("工作区状态路径必须为绝对路径")
    if workspace.is_symlink():
        raise RuntimeError("产品工作区不得是符号链接")
    root = root.resolve()
    workspace = workspace.resolve()
    if workspace.parent != root or not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    return workspace


def _read_json(path: Path, message: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(message) from error
    if not isinstance(value, dict):
        raise RuntimeError(message)
    return value


def _repository_path(workspace: Path, name: str) -> Path:
    return workspace if name == "root" else workspace / name


def _step_eight_handoff(run_dir: Path, state: dict[str, Any]) -> tuple[Path, list[str]]:
    workspace = _workspace_from_state(state)
    previous = _read_json(run_dir / "steps" / "08.json", "第 8 步成功结果不可读取")
    names = previous.get("applicable_repositories")
    if (
        previous.get("step") != 8
        or previous.get("status") != "success"
        or previous.get("applicable") is not True
        or previous.get("outputs") != []
        or not isinstance(names, list)
        or not names
        or names[0] != "root"
        or any(name not in {"root", "frontend", "backend"} for name in names)
        or len(set(names)) != len(names)
    ):
        raise RuntimeError("第 8 步仓库 clean 交接结果不符合约定")
    if state.get("applicable_repositories") != names:
        raise RuntimeError("第 8 步仓库 clean 交接状态不符合约定")
    return workspace, names


def _document_contents(workspace: Path, relative: Path, label: str) -> str:
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError(f"{label}路径不能包含符号链接")
    try:
        path = resolve_workspace_output(workspace, relative.as_posix())
    except ValueError as error:
        raise RuntimeError(f"{label}路径不符合约定") from error
    if not path.is_file():
        raise RuntimeError(f"{label}不是普通文件")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"{label}不可读取") from error
    if not content.strip():
        raise RuntimeError(f"{label}不能为空")
    return content


def _architecture_output(run_dir: Path) -> Path:
    previous = _read_json(run_dir / "steps" / "09.json", "第 9 步成功结果不可读取")
    outputs = previous.get("outputs")
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
    }
    if (
        set(previous) != expected_keys
        or previous.get("step") != 9
        or previous.get("name") != "工程架构设计"
        or previous.get("status") != "success"
        or not isinstance(previous.get("summary"), str)
        or not previous["summary"].strip()
        or previous.get("applicable") is not True
        or previous.get("outputs") != [ARCHITECTURE_OUTPUT_PATH.as_posix()]
        or previous.get("blocked") is not None
        or previous.get("error") is not None
    ):
        raise RuntimeError("第 9 步工程架构设计结果不可复用")
    output = outputs[0]
    relative = Path(output)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RuntimeError("第 9 步工程架构设计产物路径不符合约定")
    return relative


def _validate_applicable_inputs(
    run_dir: Path, workspace: Path, names: list[str]
) -> tuple[list[str], str, str, Path, str]:
    if "frontend" not in names:
        raise RuntimeError("当前产品没有权威 frontend 仓库，产品级 UI/UX 框架不适用")
    product_outputs = load_product_outputs(run_dir, workspace)
    verify_existing_readiness_success(run_dir, workspace, product_outputs)
    checklist = checklist_contents(workspace)
    if checklist is None:
        raise RuntimeError("第 5 步项目准备清单不存在或不可读取")
    verify_existing_solution_success(run_dir)
    design = _document_contents(workspace, DESIGN_PATH, "总体技术方案")
    architecture_path = _architecture_output(run_dir)
    architecture = _document_contents(workspace, architecture_path, "工程架构设计")
    return product_outputs, checklist, design, architecture_path, architecture


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], list[str], str, str, Path, str]:
    if _position(state) not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于产品级 UI/UX 框架锚点")
    workspace, names = _step_eight_handoff(run_dir, state)
    product_outputs, checklist, design, architecture_path, architecture = (
        _validate_applicable_inputs(run_dir, workspace, names)
    )
    return (
        workspace,
        names,
        product_outputs,
        checklist,
        design,
        architecture_path,
        architecture,
    )


def _git_run(
    path: Path,
    *args: str,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=path,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if completed.returncode not in allowed_returncodes:
        raise RuntimeError("无法读取 Git 仓库状态")
    return completed


def _git_read(path: Path, *args: str) -> str:
    return _git_run(path, *args).stdout.rstrip("\n")


def _repository_facts(workspace: Path, names: list[str]) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    for name in names:
        repository = _repository_path(workspace, name)
        if repository.is_symlink() or not repository.is_dir():
            raise RuntimeError("权威 Git 仓库路径不存在或是符号链接")
        path = repository.resolve()
        top_level = Path(_git_read(path, "rev-parse", "--show-toplevel")).resolve()
        if top_level != path:
            raise RuntimeError("Git 仓库顶层目录与权威仓库路径不一致")
        if _git_read(path, "branch", "--show-current") != "main":
            raise RuntimeError("Git 仓库分支不是 main")
        status = _git_read(path, "status", "--porcelain=v1", "--untracked-files=all")
        repositories.append(
            {
                "name": name,
                "path": str(path),
                "branch": "main",
                "worktree_clean": status == "",
                "status": status,
            }
        )
    return repositories


def _document_status(workspace: Path) -> str:
    return _git_read(
        workspace,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        FRAMEWORK_PATH.as_posix(),
    )


def _document_tracked(workspace: Path) -> bool:
    completed = _git_run(
        workspace,
        "ls-files",
        "--error-unmatch",
        "--",
        FRAMEWORK_PATH.as_posix(),
        allowed_returncodes=(0, 1),
    )
    return completed.returncode == 0


def _verify_worktree_boundary(
    workspace: Path, names: list[str]
) -> tuple[list[dict[str, Any]], str]:
    repositories = _repository_facts(workspace, names)
    for repository in repositories[1:]:
        if not repository["worktree_clean"]:
            raise RuntimeError("产品级 UI/UX 框架期间子仓库必须保持 clean")
    root_status = repositories[0]["status"]
    document_status = _document_status(workspace)
    if " -> " in root_status or root_status != document_status:
        raise RuntimeError("产品根仓库存在固定产品级 UI/UX 框架文档范围外的修改")
    return repositories, root_status


def framework_repair(workspace: Path) -> str | None:
    current = workspace
    for part in FRAMEWORK_PATH.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError("产品级 UI/UX 框架文档路径不能包含符号链接")
    try:
        path = resolve_workspace_output(workspace, FRAMEWORK_PATH.as_posix())
    except ValueError as error:
        raise RuntimeError("产品级 UI/UX 框架文档路径不符合约定") from error
    if not path.exists():
        return FRAMEWORK_REPAIR_PROMPT
    if not path.is_file():
        raise RuntimeError("产品级 UI/UX 框架文档必须是普通文件")
    try:
        if not path.read_text(encoding="utf-8").strip():
            return FRAMEWORK_REPAIR_PROMPT
    except (OSError, UnicodeError) as error:
        raise RuntimeError("产品级 UI/UX 框架文档不可读取") from error
    return None


def _execution_artifacts_present(run_dir: Path, state: dict[str, Any]) -> bool:
    sessions = state.get("claude_sessions")
    references = state.get("decision_conversations")
    conversation_path = run_dir / "conversations" / f"{CONVERSATION_KEY}.json"
    return (
        isinstance(sessions, dict)
        and CONVERSATION_KEY in sessions
        or isinstance(references, dict)
        and CONVERSATION_KEY in references
        or CONVERSATION_KEY in state
        or conversation_path.exists()
        or conversation_path.is_symlink()
    )


def _result_repositories(repositories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": repository["name"],
            "path": repository["path"],
            "branch": repository["branch"],
            "worktree_clean": repository["worktree_clean"],
        }
        for repository in repositories
    ]


def _completion_ready(
    workspace: Path, names: list[str]
) -> tuple[bool, list[dict[str, Any]]]:
    repair = framework_repair(workspace)
    repositories, root_status = _verify_worktree_boundary(workspace, names)
    return (
        repair is None and root_status == "" and _document_tracked(workspace),
        repositories,
    )


def _verify_existing_applicable_success(run_dir: Path) -> dict[str, Any]:
    existing = _read_json(run_dir / "steps" / "10.json", "第 10 步成功结果不可读取")
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
    }
    if (
        set(existing) != expected_keys
        or existing.get("step") != STEP
        or existing.get("name") != NAME
        or existing.get("status") != "success"
        or not isinstance(existing.get("summary"), str)
        or not existing["summary"].strip()
        or existing.get("applicable") is not True
        or existing.get("outputs") != [FRAMEWORK_PATH.as_posix()]
        or existing.get("blocked") is not None
        or existing.get("error") is not None
    ):
        raise RuntimeError("第 10 步适用成功结果不可复用")
    return existing


def _verify_existing_inapplicable_success(run_dir: Path) -> dict[str, Any]:
    existing = _read_json(run_dir / "steps" / "10.json", "第 10 步成功结果不可读取")
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
    }
    if (
        set(existing) != expected_keys
        or existing.get("step") != STEP
        or existing.get("name") != NAME
        or existing.get("status") != "success"
        or not isinstance(existing.get("summary"), str)
        or not existing["summary"].strip()
        or existing.get("applicable") is not False
        or existing.get("outputs") != []
        or existing.get("blocked") is not None
        or existing.get("error") is not None
    ):
        raise RuntimeError("第 10 步不适用成功结果不可复用")
    return existing


def _advance_not_applicable(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    saved = result(
        "success",
        "当前产品的第 8 步权威仓库清单不包含 frontend，产品级 UI/UX 框架不适用。",
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


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    names: list[str],
    repositories: list[dict[str, Any]],
) -> dict[str, Any]:
    saved = result(
        "success",
        "ui-ux-framework 已生成固定产品级 UI/UX 框架文档，固定文档和 Git 交付已核验。",
        outputs=[FRAMEWORK_PATH.as_posix()],
    )
    write_step_result(run_dir, STEP, saved)
    state.update(
        {
            "status": "success",
            "phase": "project_initialization",
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "applicable_repositories": names,
            "repositories": _result_repositories(repositories),
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return saved


def initial_prompt(
    product_outputs: list[str],
    architecture_path: Path,
) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    return f"""/ui-ux-framework
我授权你在当前项目按 bootstrap 模式建立产品级 UI/UX 框架。请基于权威领域资料和实际前端工程创建或更新唯一固定产物 `docs/ui-ux/framework.md`。

权威产品定义：
{product_references}

项目准备事实：
- @./{CHECKLIST.as_posix()}

总体技术方案：
- @./{DESIGN_PATH.as_posix()}

工程架构设计：
- @./{architecture_path.as_posix()}

权威前端工程：
- @./frontend

文档仅定义跨需求适用的产品级体验框架：产品体验目标与原则、信息和交互框架、跨需求一致性约束、内容与反馈基线、可访问性和响应式基线、设计资产边界及协作规则。必须区分当前工程事实、已确认决定、目标状态、假设和待确认事项；高影响方向不得自行定案，应清晰记录供决策负责人继续确认。

只允许创建或更新固定产物。不得开展单项需求设计，不得设计或实现页面、CSS、组件或主题，不得修改或新增测试、迁移、业务代码、工程配置、项目规则或其他文档，不得执行 Git 写操作，不得处理或披露秘密。最终完整回复须列出文档路径、依据的产品和工程事实、主要框架方向、风险与待确认事项、未验证范围。"""


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    position = _position(state)
    if position not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于产品级 UI/UX 框架锚点")

    workspace, names = _step_eight_handoff(run_dir, state)
    if "frontend" not in names:
        product_outputs = load_product_outputs(run_dir, workspace)
        verify_existing_readiness_success(run_dir, workspace, product_outputs)
        _architecture_output(run_dir)
        existing_step_status = step_result_status(run_dir, STEP)
        if _execution_artifacts_present(run_dir, state):
            raise RuntimeError("不适用产品级 UI/UX 框架入口不得包含既有执行产物")
        if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
            _verify_existing_inapplicable_success(run_dir)
            return result(
                "success",
                "当前产品的第 8 步权威仓库清单不包含 frontend，确认既有不适用成功。",
                applicable=False,
            )
        if position != (STEP, STEP, CURRENT_NODE):
            raise RuntimeError("运行状态不位于产品级 UI/UX 框架锚点")
        if existing_step_status == "success":
            _verify_existing_inapplicable_success(run_dir)
        return _advance_not_applicable(run_dir, state)

    (
        workspace,
        names,
        product_outputs,
        checklist,
        design,
        architecture_path,
        architecture,
    ) = validate_inputs(run_dir, state)
    initial_agent_prompt = initial_prompt(product_outputs, architecture_path)
    existing_step_status = step_result_status(run_dir, STEP)
    fresh = (
        position == (STEP, STEP, CURRENT_NODE)
        and state.get("status") == "success"
        and existing_step_status != "success"
    )
    started = _execution_artifacts_present(run_dir, state)
    if fresh and started:
        raise RuntimeError("新鲜产品级 UI/UX 框架入口不得包含既有执行产物")

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        _verify_existing_applicable_success(run_dir)
        ready, _ = _completion_ready(workspace, names)
        if not ready:
            raise RuntimeError("第 10 步成功后固定文档或仓库状态发生漂移")
        return result(
            "success",
            "ui-ux-framework 已生成固定产品级 UI/UX 框架文档，固定文档和 Git 交付已核验，确认既有成功。",
            outputs=[FRAMEWORK_PATH.as_posix()],
        )

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于产品级 UI/UX 框架锚点")

    if existing_step_status == "success":
        _verify_existing_applicable_success(run_dir)
        ready, repositories = _completion_ready(workspace, names)
        if not ready:
            raise RuntimeError("第 10 步既有成功缺少有效固定文档或 clean 仓库")
        return advance_success(run_dir, state, names, repositories)

    repositories, root_status = _verify_worktree_boundary(workspace, names)
    if not started and (
        root_status != "" or any(not item["worktree_clean"] for item in repositories)
    ):
        raise RuntimeError("首次产品级 UI/UX 框架 Agent 执行前第 8 步权威仓库必须全仓 clean")

    if state.get("status") != "blocked":
        state.update(
            {"current_step": STEP, "status": "running", "blocked": None, "error": None}
        )
        write_state(run_dir, state)

    decision_spec = replace(
        DECISION_LOOP_SPEC,
        decision_system_prompt=render_decision_system_prompt(
            UI_UX_FRAMEWORK_DECISION_RULES,
            {
                "产品定义": product_output_contents(workspace, product_outputs),
                "项目准备清单": checklist,
                "总体技术方案": design,
                "工程架构设计": architecture,
                "权威前端工程": "frontend",
                "固定输出": FRAMEWORK_PATH.as_posix(),
            },
        ),
    )

    def completion_verifier() -> str | None:
        repair = framework_repair(workspace)
        if repair is not None:
            return repair
        _, root_status = _verify_worktree_boundary(workspace, names)
        if root_status != "":
            return COMMIT_REPAIR_PROMPT
        if _document_tracked(workspace):
            return None
        raise RuntimeError("固定产品级 UI/UX 框架文档未受 Git 跟踪，无法在 clean 仓库中完成")

    async def _verified_decision_runner(
        messages: list[dict[str, str]],
        config: Any,
        *,
        system_prompt: str,
    ) -> Any:
        _verify_worktree_boundary(workspace, names)
        return await decision_runner(messages, config, system_prompt=system_prompt)

    decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        decision_spec,
        initial_agent_prompt,
        completion_verifier,
        agent_runner=agent_runner,
        decision_runner=_verified_decision_runner,
        config_loader=config_loader,
    )

    if decision.verdict == "blocked":
        outputs = [FRAMEWORK_PATH.as_posix()] if framework_repair(workspace) is None else []
        blocked = {
            "reason": decision.reason,
            "required_inputs": decision.required_inputs,
            "resume_phase": "project_initialization",
            "resume_node": CURRENT_NODE,
            "resume_step": STEP,
        }
        saved = result("blocked", decision.reason, outputs=outputs, blocked=blocked)
        write_step_result(run_dir, STEP, saved)
        state.update(
            {
                "status": "blocked",
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": blocked,
                "error": None,
            }
        )
        write_state(run_dir, state)
        raise UIUXFrameworkBlocked(decision.reason, decision.required_inputs, outputs)

    ready, repositories = _completion_ready(workspace, names)
    if not ready:
        raise RuntimeError("产品级 UI/UX 框架固定文档或 Git 交付未通过核验")
    return advance_success(run_dir, state, names, repositories)
