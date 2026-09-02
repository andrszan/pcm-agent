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
    design_repair,
    verify_existing_solution_success,
)

STEP = 9
NAME = "工程架构设计"
CURRENT_NODE = "project:09_engineering_architecture"
NEXT_NODE = "project:10_ui_ux_framework"
CONVERSATION_KEY = "engineering_architecture"
SKILL_NAME = "engineering-architecture"
ARCHITECTURE_PATH = Path("docs/design/工程架构设计.md")
MAX_DECISION_ROUNDS = 16
ENGINEERING_ARCHITECTURE_MAX_TURNS = 100

ARCHITECTURE_REPAIR_PROMPT = (
    "固定工程架构设计文档缺失或为空。请仅创建或补全 "
    "docs/design/工程架构设计.md；不得修改任何其他文件，不得执行 Git 写操作。"
    "必须按当前工程架构合同为每个适用且含相关业务代码的交付单元分别补齐有限 Current/Target 地图、"
    "目录/模块职责、公开/私有边界、允许/禁止依赖和至少一个代表性文件放置演练；"
    "根仓或另一单元概述不得替代。frontend 存在时按实际工程覆盖应用装配/路由页面、业务功能、"
    "远程/局部/跨页面状态、传输到展示模型映射和共享 UI 准入；backend 存在时按实际工程覆盖入口/契约、"
    "编排/规则、持久化/外部适配及事务/授权/错误/副作用/重试/恢复。双端均含业务代码时两端各至少一个演练；"
    "不适用必须基于事实，不得虚构。已确认的稳定业务 owner、目录/包/模块边界、公开出口、私有禁区和依赖方向属于约束；"
    "代表性文件放置只验证归属，边界内部文件名、数量和等价拆分可按真实职责调整。不得把前端职责静默打平到巨型路由/页面或通用收纳目录，"
    "不得把后端业务包静默降级为同名平铺文件，也不得跨所有者合并或绕过公开出口；Current 已存在此类偏差时须给出最小迁移。"
    "仍只维护根仓这一份文档，不得创建 frontend/backend 本地架构文档。"
    "使用 [当前]/[目标]/[按需]/[迁移] 标注并给出最小迁移和可观察演进；不得固定框架、FSD、DDD、Clean、目录模板或行数阈值，"
    "千行仅触发职责调查。不得只写空壳、不得虚构 Current、不得创建目标目录或预留抽象，然后报告结果。"
)
COMMIT_REPAIR_PROMPT = """/commit-changes
只授权处理产品根 Git 仓库中的固定文档 `docs/design/工程架构设计.md`。请核验该文档；仅当它存在未提交变更时，暂存并提交这一个文件，然后确认产品根仓库工作区干净。不得暂存、提交或修改任何其他路径，不得处理子仓库，不得建分支、改写历史或 push。若固定文档相对当前提交没有变化，直接报告无变更，不得制造变更。"""

ENGINEERING_ARCHITECTURE_DECISION_RULES = """- completed：固定工程架构设计文档已生成，且仍为根仓唯一的 `docs/design/工程架构设计.md`，没有创建 frontend/backend 本地架构文档；每个适用且含相关业务代码的交付单元均分别有有限 Current/Target 地图，使用 [当前]/[目标]/[按需]/[迁移] 标注，明确目录/模块职责、公开/私有边界、允许/禁止依赖，并至少有一个代表性文件放置演练，说明最小迁移和可观察演进，根仓或另一单元概述不能替代。已确认的稳定业务 owner、目录/包/模块边界、公开出口、私有禁区和依赖方向已作为约束；代表性文件放置只验证归属，边界内部文件名、数量和等价拆分仍可按真实职责调整。frontend 存在时，已按实际工程覆盖应用装配/路由页面、业务功能、远程/局部/跨页面状态、传输到展示模型映射和共享 UI 准入，且没有把稳定职责静默打平到巨型路由/页面或通用收纳目录；backend 存在时，已按实际工程覆盖入口/契约、编排/规则、持久化/外部适配及事务/授权/错误/副作用/重试/恢复，且没有把稳定业务包静默降级为同名平铺文件。双端均含业务代码时，frontend 和 backend 各至少有一个演练；不适用已有事实依据，未虚构。跨所有者合并、公开出口绕过或私有路径引用等 Current 偏差已有最小迁移，不作为文件组织等价调整。架构决策矩阵有决策证据，当前下游所需的高影响架构决定已收敛，且没有越界实现业务功能。不得固定框架、FSD、DDD、Clean、目录模板或行数阈值；千行仅触发职责调查。
- continue：上述逐交付单元工程归属合同、稳定边界与内部粒度区分、Current 偏差迁移、工程事实核验或下游所需高影响架构决定仍可依据当前事实补全。
- blocked：只能用于缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务或线下动作。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key=CONVERSATION_KEY,
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=ENGINEERING_ARCHITECTURE_MAX_TURNS,
    model_tier="high",
    effort="high",
    decision_system_prompt=render_decision_system_prompt(
        ENGINEERING_ARCHITECTURE_DECISION_RULES, {}
    ),
)


class EngineeringArchitectureBlocked(RuntimeError):
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


def _step_eight_handoff(run_dir: Path, state: dict[str, Any]) -> list[str]:
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
    return names


def _document_contents(workspace: Path, relative: Path, label: str) -> str:
    try:
        path = resolve_workspace_output(workspace, relative.as_posix())
    except ValueError as error:
        raise RuntimeError(f"{label}路径不符合约定") from error
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError(f"{label}路径不能包含符号链接")
    if not path.is_file():
        raise RuntimeError(f"{label}不是普通文件")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"{label}不可读取") from error
    if not content.strip():
        raise RuntimeError(f"{label}不能为空")
    return content


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], list[str], str, str]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于工程架构设计锚点")
    workspace = _workspace_from_state(state)
    product_outputs = load_product_outputs(run_dir, workspace)
    verify_existing_readiness_success(run_dir, workspace, product_outputs)
    checklist = checklist_contents(workspace)
    if checklist is None:
        raise RuntimeError("第 5 步项目准备清单不存在或不可读取")
    verify_existing_solution_success(run_dir)
    if design_repair(workspace) is not None:
        raise RuntimeError("第 7 步既有成功缺少非空技术方案文档")
    design = _document_contents(workspace, DESIGN_PATH, "总体技术方案")
    names = _step_eight_handoff(run_dir, state)
    return workspace, product_outputs, names, checklist, design


def _git_run(path: Path, *args: str, allowed_returncodes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
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
        ARCHITECTURE_PATH.as_posix(),
    )


def _document_tracked(workspace: Path) -> bool:
    completed = _git_run(
        workspace,
        "ls-files",
        "--error-unmatch",
        "--",
        ARCHITECTURE_PATH.as_posix(),
        allowed_returncodes=(0, 1),
    )
    return completed.returncode == 0


def _verify_worktree_boundary(
    workspace: Path, names: list[str]
) -> tuple[list[dict[str, Any]], str]:
    repositories = _repository_facts(workspace, names)
    for repository in repositories[1:]:
        if not repository["worktree_clean"]:
            raise RuntimeError("工程架构设计期间子仓库必须保持 clean")
    root_status = repositories[0]["status"]
    document_status = _document_status(workspace)
    if " -> " in root_status or root_status != document_status:
        raise RuntimeError("产品根仓库存在固定工程架构文档范围外的修改")
    return repositories, root_status


def architecture_repair(workspace: Path) -> str | None:
    try:
        path = resolve_workspace_output(workspace, ARCHITECTURE_PATH.as_posix())
    except ValueError as error:
        raise RuntimeError("工程架构设计文档路径不符合约定") from error
    current = workspace
    for part in ARCHITECTURE_PATH.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError("工程架构设计文档路径不能包含符号链接")
    if not path.exists():
        return ARCHITECTURE_REPAIR_PROMPT
    if not path.is_file():
        raise RuntimeError("工程架构设计文档必须是普通文件")
    try:
        if not path.read_text(encoding="utf-8").strip():
            return ARCHITECTURE_REPAIR_PROMPT
    except (OSError, UnicodeError) as error:
        raise RuntimeError("工程架构设计文档不可读取") from error
    return None


def _fresh_artifacts_present(run_dir: Path, state: dict[str, Any]) -> bool:
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
    repair = architecture_repair(workspace)
    repositories, root_status = _verify_worktree_boundary(workspace, names)
    return (
        repair is None and root_status == "" and _document_tracked(workspace),
        repositories,
    )


def verify_existing_success(run_dir: Path) -> dict[str, Any]:
    existing = _read_json(run_dir / "steps" / "09.json", "第 9 步成功结果不可读取")
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
        or existing.get("outputs") != [ARCHITECTURE_PATH.as_posix()]
        or existing.get("blocked") is not None
        or existing.get("error") is not None
    ):
        raise RuntimeError("第 9 步成功结果不可复用")
    return existing


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    names: list[str],
    repositories: list[dict[str, Any]],
) -> dict[str, Any]:
    saved = result(
        "success",
        "engineering-architecture 已生成固定工程架构设计文档，固定文档和 Git 交付已核验。",
        outputs=[ARCHITECTURE_PATH.as_posix()],
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


def initial_prompt(product_outputs: list[str], names: list[str]) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    engineering_references = "\n".join(
        "- 产品根工程：@./" if name == "root" else f"- {name} 工程：@./{name}"
        for name in names
    )
    return f"""/engineering-architecture
请基于权威领域资料和当前实际工程，创建或更新唯一固定产物 `docs/design/工程架构设计.md`。

权威产品定义：
{product_references}

项目准备事实：
- @./{CHECKLIST.as_posix()}

总体技术方案：
- @./{DESIGN_PATH.as_posix()}

实际工程：
{engineering_references}

文档应把权威输入和实际工程收敛为根仓唯一单份、逐交付单元闭合的工程归属合同，而非通用技术清单：每个适用且含相关业务代码的交付单元均须分别给出有限 Current/Target 地图，使用 [当前]/[目标]/[按需]/[迁移] 区分已证实事实、已收敛目标、仅在有证据和消费者时才需要的能力及必要迁移；明确目录/模块职责、公开/私有边界、允许/禁止依赖，并至少有一个代表性文件放置演练，说明最小迁移和可观察演进，根仓或另一单元概述不得替代，不得虚构 Current。已确认的稳定业务 owner、目录/包/模块边界、公开出口、私有禁区和依赖方向属于约束；代表性文件放置只验证归属，边界内部文件名、数量和等价拆分可按真实职责调整。frontend 存在时按实际工程覆盖应用装配/路由页面、业务功能、远程/局部/跨页面状态、传输到展示模型映射和共享 UI 准入，不得把稳定职责静默打平到巨型路由/页面或通用 `components`、`hooks`、`services`、`shared` 收纳位置；backend 存在时按实际工程覆盖入口/契约、编排/规则、持久化/外部适配及事务/授权/错误/副作用/重试/恢复，不得把已确认业务包静默降级为同名平铺文件。双端均含业务代码时，两端各至少有一个演练；不适用必须基于事实。跨所有者合并、公开出口绕过或私有路径引用等 Current 偏差须设计最小迁移，不能作为文件组织等价调整。用架构决策矩阵记录决定、证据、影响和状态，收敛当前下游所需的高影响架构决定。仍只维护根仓 `docs/design/工程架构设计.md`，不得创建 frontend/backend 本地架构文档。不得固定框架、FSD、DDD、Clean、目录模板或行数阈值；千行仅触发职责调查，不是强制拆分。不得预建 `domain`、`application`、`infrastructure`、`shared`、服务、队列、接口或无消费者结构，不得无边界全仓扫描。配置、运行、数据、测试、安全等主题仅按权威输入或实际工程证据展开，不机械罗列。

只允许创建或更新固定产物，不得实现业务功能、修改工程代码或配置、修改 `CLAUDE.md`、`AGENTS.md` 或其它项目规则、执行 Git 写操作、处理秘密。最终完整回复须列出文档路径、依据的工程事实、主要架构决定、风险与未决事项、未验证范围。"""


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    workspace, product_outputs, names, checklist, design = validate_inputs(run_dir, state)
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    existing_step_status = step_result_status(run_dir, STEP)
    initial_agent_prompt = initial_prompt(product_outputs, names)
    fresh = (
        position == (STEP, STEP, CURRENT_NODE)
        and state.get("status") == "success"
        and existing_step_status != "success"
    )
    started = _fresh_artifacts_present(run_dir, state)
    if fresh and started:
        raise RuntimeError("新鲜工程架构设计入口不得包含既有执行产物")

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        verify_existing_success(run_dir)
        ready, _ = _completion_ready(workspace, names)
        if not ready:
            raise RuntimeError("第 9 步成功后固定文档或仓库状态发生漂移")
        return result(
            "success",
            "engineering-architecture 已生成固定工程架构设计文档，固定文档和 Git 交付已核验，确认既有成功。",
            outputs=[ARCHITECTURE_PATH.as_posix()],
        )

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于工程架构设计锚点")

    if existing_step_status == "success":
        verify_existing_success(run_dir)
        ready, repositories = _completion_ready(workspace, names)
        if not ready:
            raise RuntimeError("第 9 步既有成功缺少有效固定文档或 clean 仓库")
        return advance_success(run_dir, state, names, repositories)

    repositories, root_status = _verify_worktree_boundary(workspace, names)
    if not started and (
        root_status != "" or any(not item["worktree_clean"] for item in repositories)
    ):
        raise RuntimeError("首次工程架构 Agent 执行前第 8 步权威仓库必须全仓 clean")

    if state.get("status") != "blocked":
        state.update(
            {"current_step": STEP, "status": "running", "blocked": None, "error": None}
        )
        write_state(run_dir, state)

    decision_spec = replace(
        DECISION_LOOP_SPEC,
        decision_system_prompt=render_decision_system_prompt(
            ENGINEERING_ARCHITECTURE_DECISION_RULES,
            {
                "产品定义": product_output_contents(workspace, product_outputs),
                "项目准备清单": checklist,
                "总体技术方案": design,
                "权威工程": names,
                "固定输出": ARCHITECTURE_PATH.as_posix(),
            },
        ),
    )

    def completion_verifier() -> str | None:
        repair = architecture_repair(workspace)
        if repair is not None:
            return repair
        _, root_status = _verify_worktree_boundary(workspace, names)
        if root_status != "":
            return COMMIT_REPAIR_PROMPT
        if _document_tracked(workspace):
            return None
        raise RuntimeError("固定工程架构设计文档未受 Git 跟踪，无法在 clean 仓库中完成")

    async def _verified_decision_runner(
        messages: list[dict[str, str]],
        config: Any,
        *,
        system_prompt: str,
    ) -> Any:
        _verify_worktree_boundary(workspace, names)
        return await decision_runner(
            messages,
            config,
            system_prompt=system_prompt,
        )

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
        outputs = (
            [ARCHITECTURE_PATH.as_posix()]
            if architecture_repair(workspace) is None
            else []
        )
        blocked = {
            "reason": decision.reason,
            "required_inputs": decision.required_inputs,
            "resume_phase": "project_initialization",
            "resume_node": CURRENT_NODE,
            "resume_step": STEP,
        }
        saved = result(
            "blocked",
            decision.reason,
            outputs=outputs,
            blocked=blocked,
        )
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
        raise EngineeringArchitectureBlocked(
            decision.reason, decision.required_inputs, outputs
        )

    ready, repositories = _completion_ready(workspace, names)
    if not ready:
        raise RuntimeError("工程架构设计固定文档或 Git 交付未通过核验")
    return advance_success(run_dir, state, names, repositories)
