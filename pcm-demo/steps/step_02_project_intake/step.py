from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.files import resolve_workspace_output, sha256, write_json
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

PROJECT_INTAKE_DECISION_RULES = """completed 表示两份正式产品定义文档已经生成、非空并可用，且产品定义已经为开发验收数据基线明确以下合同之一：客户自主体验主要功能所需的初始角色、内容、代表性状态、适用对象资源；或产品从空态建立首条业务数据并进入主要功能的成功路径。这里只定义产品体验所需事实和适用范围，不设计 Seed 命令、数据结构或后续实现。
continue 表示还需给出明确指令以澄清产品或完成、修复这两份文档。
blocked 仅表示缺少当前环境无法取得的真实外部账号、凭据、私有数据、客户授权、专用设备、素材、付费服务或线下动作。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key="project_intake",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=PROJECT_INTAKE_MAX_TURNS,
    model_tier="high",
    effort="high",
    decision_system_prompt=render_decision_system_prompt(PROJECT_INTAKE_DECISION_RULES, {}),
    legacy_completion_messages=(
        "已完成 project-intake：两份正式产品定义文档已生成并通过文件事实核验。",
    ),
)


class ProjectIntakeBlocked(RuntimeError):
    def __init__(self, reason: str, required_inputs: list[str]):
        super().__init__(reason)
        self.required_inputs = required_inputs


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


def trust_project(workspace: Path) -> None:
    claude_json = Path.home() / ".claude.json"
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
    source = Path(state["input"]["source_path"])
    expected_hash = state["input"]["source_sha256"]
    if not source.is_file() or sha256(source) != expected_hash or sha256(draft) != expected_hash:
        raise RuntimeError("源产品初稿或项目内产品初稿与运行记录不一致")
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


def output_contents(workspace: Path) -> dict[str, str] | None:
    """返回可用正式文档；缺失或空文件可修复，路径异常必须失败。"""

    contents: dict[str, str] = {}
    incomplete = False
    for relative in OUTPUTS:
        current = workspace
        for index, part in enumerate(relative.parts):
            current /= part
            if current.is_symlink():
                raise RuntimeError("产品定义产物路径不能包含符号链接")
            if index < len(relative.parts) - 1 and current.exists() and not current.is_dir():
                raise RuntimeError("产品定义产物父路径与预期目录冲突")
        if not current.exists():
            incomplete = True
            continue
        if not current.is_file():
            raise RuntimeError("产品定义产物不是普通文件")
        try:
            content = current.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise RuntimeError("产品定义产物不可读取") from error
        if not content.strip():
            incomplete = True
            continue
        contents[relative.as_posix()] = content
    return None if incomplete else contents


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
    return existing


def initial_prompt(draft: Path, workspace: Path) -> str:
    reference = draft.relative_to(workspace).as_posix()
    outputs = "\n".join(f"- `{path.as_posix()}`" for path in OUTPUTS)
    return f"""/project-intake @./{reference}
以产品初稿为当前产品定义的权威输入，持续澄清并形成以下两份非空正式文档：
{outputs}
产品定义还须明确开发验收数据基线的产品侧前提，形成以下一种可验收合同：
- 若客户需要带有初始业务事实自主体验主要功能，明确所需的初始角色、内容、代表性状态、适用对象资源；
- 若产品应从空态开始，明确用户建立首条业务数据并成功进入主要功能的路径。
这里只定义产品体验、适用范围和成功结果，不设计 Seed 命令、数据结构或后续实现。只处理产品定义文档。"""


def completion_repair_prompt() -> str:
    paths = "、".join(path.as_posix() for path in OUTPUTS)
    return f"请生成或补全两份非空正式产品定义文档：{paths}。"


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    workspace, draft = validate_inputs(run_dir, state)
    existing_outputs = output_contents(workspace)
    if existing_outputs is not None and (run_dir / "steps" / "02.json").is_file():
        try:
            existing = verify_existing_intake_success(run_dir)
        except RuntimeError:
            existing = None
        if existing is not None:
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
    if _is_legacy_completed_position(state):
        raise RuntimeError("第 2 步成功状态缺少可复用的完整结果")

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
            },
        ),
    )
    decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        decision_spec,
        initial_prompt(draft, workspace),
        verify_completed,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
    )
    if decision.verdict == "blocked":
        raise ProjectIntakeBlocked(decision.reason, decision.required_inputs)
    if decision.verdict != "completed":
        raise RuntimeError("Agent 决策循环未返回完成或阻塞结论")

    completed = result(
        "success",
        "project-intake 已生成产品定义文档。",
        outputs=[relative.as_posix() for relative in OUTPUTS],
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
