from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any

from common.agent_decision_loop import AIDecisionFailure
from common.files import sha256
from common.state import (
    create_run_dir,
    read_state,
    requirement_step_result_path,
    write_requirement_step_result,
    write_state,
    write_step_result,
)
from config import LLMConfig, load_template_repository, load_workspace_root
from steps.step_00_product_draft import run as run_product_draft
from steps.step_01_create_workspace import (
    WorkspaceBlocked,
    clone_and_verify,
    extract_project_identity,
    initialize_root_repository,
    inspect_clone,
    inspect_root_repository,
    prepare_staging,
    publish,
    verify_clone,
    verify_prepared,
    verify_published_content,
)
from steps.step_01_create_workspace import (
    result as workspace_result,
)
from steps.step_02_project_intake import ProjectIntakeBlocked
from steps.step_02_project_intake import result as project_intake_result
from steps.step_02_project_intake import run as run_project_intake
from steps.step_03_foundation_selection import run as run_foundation_selection
from steps.step_04_assemble_foundation import run as run_assemble_foundation
from steps.step_04_assemble_foundation.step import result as assembly_result
from steps.step_05_project_readiness import ProjectReadinessBlocked
from steps.step_05_project_readiness import result as project_readiness_result
from steps.step_05_project_readiness import run as run_project_readiness
from steps.step_05_project_readiness.step import CURRENT_NODE as PROJECT_READINESS_NODE
from steps.step_06_project_bootstrap import ProjectBootstrapBlocked
from steps.step_06_project_bootstrap import result as project_bootstrap_result
from steps.step_06_project_bootstrap import run as run_project_bootstrap
from steps.step_06_project_bootstrap.step import CURRENT_NODE as PROJECT_BOOTSTRAP_NODE
from steps.step_07_solution_design import SolutionDesignBlocked
from steps.step_07_solution_design import result as solution_design_result
from steps.step_07_solution_design import run as run_solution_design
from steps.step_07_solution_design.step import CURRENT_NODE as SOLUTION_DESIGN_NODE
from steps.step_08_initialize_repositories import InitializeRepositoriesBlocked
from steps.step_08_initialize_repositories import result as initialize_repositories_result
from steps.step_08_initialize_repositories import run as run_initialize_repositories
from steps.step_08_initialize_repositories.step import CURRENT_NODE as INITIALIZE_REPOSITORIES_NODE
from steps.step_09_engineering_architecture import EngineeringArchitectureBlocked
from steps.step_09_engineering_architecture import result as engineering_architecture_result
from steps.step_09_engineering_architecture import run as run_engineering_architecture
from steps.step_09_engineering_architecture.step import CURRENT_NODE as ENGINEERING_ARCHITECTURE_NODE
from steps.step_10_ui_ux_framework import UIUXFrameworkBlocked
from steps.step_10_ui_ux_framework import result as ui_ux_framework_result
from steps.step_10_ui_ux_framework import run as run_ui_ux_framework
from steps.step_10_ui_ux_framework.step import CURRENT_NODE as UI_UX_FRAMEWORK_NODE
from steps.step_11_requirement_breakdown import RequirementBreakdownBlocked
from steps.step_11_requirement_breakdown import result as requirement_breakdown_result
from steps.step_11_requirement_breakdown import run as run_requirement_breakdown
from steps.step_11_requirement_breakdown.step import CURRENT_NODE as REQUIREMENT_BREAKDOWN_NODE
from steps.step_12_initialize_requirement_registry import result as requirement_registry_result
from steps.step_12_initialize_requirement_registry import run as run_requirement_registry
from steps.step_12_initialize_requirement_registry.step import has_complete_success as has_requirement_registry_success
from steps.step_13_select_requirement import result as requirement_selection_result
from steps.step_13_select_requirement import run as run_requirement_selection
from steps.step_13_select_requirement.step import (
    CURRENT_NODE as SELECT_REQUIREMENT_NODE,
    PHASE as SELECT_REQUIREMENT_PHASE,
    NoPendingRequirements,
    RequirementSelectionError,
    failure_scope as requirement_selection_failure_scope,
    has_complete_success as has_requirement_selection_success,
)
from steps.step_14_trd_design import TRDDesignBlocked
from steps.step_14_trd_design import result as trd_design_result
from steps.step_14_trd_design import run as run_trd_design
from steps.step_14_trd_design.step import (
    CURRENT_NODE as TRD_DESIGN_NODE,
    failure_scope as trd_design_failure_scope,
    has_complete_success as has_trd_design_success,
)
from steps.step_15_development import DevelopmentBlocked
from steps.step_15_development import result as development_result
from steps.step_15_development import run as run_development
from steps.step_15_development.step import (
    CURRENT_NODE as DEVELOPMENT_NODE,
    failure_scope as development_failure_scope,
    has_complete_success as has_development_success,
)
from steps.step_16_rule_retrospective import RuleRetrospectiveBlocked
from steps.step_16_rule_retrospective import result as rule_retrospective_result
from steps.step_16_rule_retrospective import run as run_rule_retrospective
from steps.step_16_rule_retrospective.step import (
    CURRENT_NODE as RULE_RETROSPECTIVE_NODE,
    failure_scope as rule_retrospective_failure_scope,
    has_complete_success as has_rule_retrospective_success,
)
from steps.step_17_commit import result as requirement_commit_result
from steps.step_17_commit import run as run_requirement_commit
from steps.step_17_commit.step import (
    CURRENT_NODE as REQUIREMENT_COMMIT_NODE,
    failure_scope as requirement_commit_failure_scope,
    has_complete_success as has_requirement_commit_success,
)
from steps.step_18_merge import result as requirement_merge_result
from steps.step_18_merge import run as run_requirement_merge
from steps.step_18_merge.step import (
    CURRENT_NODE as REQUIREMENT_MERGE_NODE,
    failure_scope as requirement_merge_failure_scope,
    has_complete_success as has_requirement_merge_success,
)

DEMO_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行已实现的 PCM Demo 步骤")
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--product-draft", "--prd", dest="product_draft", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--catalog-path", type=Path)
    parser.add_argument("--run-id")
    return parser.parse_args()


def new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{token_hex(3)}"


def require_draft(path: Path | None) -> Path:
    if path is None:
        raise ValueError("当前步骤需要 --product-draft")
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"产品初稿不存在或不可读：{resolved}")
    return resolved


def run_dir_for(run_id: str) -> Path:
    run_dir = (DEMO_ROOT / "runs" / run_id).resolve()
    if run_dir.parent != (DEMO_ROOT / "runs").resolve():
        raise ValueError(f"无效运行 ID：{run_id}")
    return run_dir


def has_step_success(run_dir: Path, step: int) -> bool:
    if step not in {8, 9, 10, 11, 12}:
        return False
    try:
        existing = json.loads(
            (run_dir / "steps" / f"{step:02d}.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if step == 12:
        return has_requirement_registry_success(existing)
    if step == 10:
        applicable = existing.get("applicable") if isinstance(existing, dict) else None
        return (
            isinstance(existing, dict)
            and set(existing)
            == {
                "step",
                "name",
                "status",
                "summary",
                "applicable",
                "outputs",
                "blocked",
                "error",
            }
            and type(existing.get("step")) is int
            and existing.get("step") == 10
            and existing.get("name") == "产品级 UI/UX 框架"
            and existing.get("status") == "success"
            and isinstance(existing.get("summary"), str)
            and bool(existing["summary"].strip())
            and existing.get("blocked") is None
            and existing.get("error") is None
            and (
                (
                    applicable is True
                    and existing.get("outputs") == ["docs/ui-ux/framework.md"]
                )
                or (applicable is False and existing.get("outputs") == [])
            )
        )
    if step == 11:
        return (
            isinstance(existing, dict)
            and set(existing)
            == {
                "step",
                "name",
                "status",
                "summary",
                "applicable",
                "outputs",
                "blocked",
                "error",
            }
            and type(existing.get("step")) is int
            and existing.get("step") == 11
            and existing.get("name") == "拆分 Backlog"
            and existing.get("status") == "success"
            and isinstance(existing.get("summary"), str)
            and bool(existing["summary"].strip())
            and existing.get("applicable") is True
            and existing.get("outputs") == ["docs/backlog/backlog.md"]
            and existing.get("blocked") is None
            and existing.get("error") is None
        )
    if (
        not isinstance(existing, dict)
        or type(existing.get("step")) is not int
        or existing.get("step") != step
        or existing.get("status") != "success"
        or not isinstance(existing.get("summary"), str)
        or not existing["summary"]
        or existing.get("applicable") is not True
        or existing.get("blocked") is not None
        or existing.get("error") is not None
    ):
        return False
    if step == 9:
        return (
            set(existing)
            == {
                "step",
                "name",
                "status",
                "summary",
                "applicable",
                "outputs",
                "blocked",
                "error",
            }
            and bool(existing["summary"].strip())
            and existing.get("name") == "工程架构设计"
            and existing.get("outputs") == ["docs/design/工程架构设计.md"]
        )

    names = existing.get("applicable_repositories")
    repositories = existing.get("repositories")
    if (
        existing.get("name") != "首次提交适用仓库"
        or existing.get("outputs") != []
        or not isinstance(names, list)
        or not names
        or names[0] != "root"
        or any(name not in {"root", "frontend", "backend"} for name in names)
        or len(set(names)) != len(names)
        or not isinstance(repositories, list)
        or len(repositories) != len(names)
    ):
        return False
    return all(
        repository
        == {
            "name": name,
            "path": "." if name == "root" else name,
            "branch": "main",
            "worktree_clean": True,
        }
        for name, repository in zip(names, repositories, strict=True)
    )


def load_or_create_step_one_run(args: argparse.Namespace) -> tuple[Path, dict[str, Any], Path]:
    if args.run_id and run_dir_for(args.run_id).is_dir():
        run_dir = run_dir_for(args.run_id)
        state = read_state(run_dir)
        if state.get("current_step") == 0 and state.get("status") != "success":
            raise RuntimeError("第 0 步尚未成功，不能建立项目工作区")
        if state.get("current_step") not in {0, 1}:
            raise RuntimeError("已有运行状态不属于第 0 或第 1 步")
        draft_path = Path(state["input"]["source_path"])
        if args.product_draft and args.product_draft.resolve() != draft_path:
            raise RuntimeError("--product-draft 与已有运行记录不一致")
        return run_dir, state, draft_path

    draft_path = require_draft(args.product_draft)
    run_id = args.run_id or new_run_id()
    run_dir = create_run_dir(DEMO_ROOT / "runs", run_id)
    draft_bytes = draft_path.read_bytes()
    draft_content = draft_bytes.decode("utf-8")
    state = {
        "run_id": run_id,
        "status": "running",
        "current_step": 1,
        "input": {
            "type": "product_draft",
            "source_path": str(draft_path),
            "source_sha256": sha256(draft_path),
            "content": draft_content,
            "published_path": None,
        },
        "publication_phase": None,
        "blocked": None,
        "error": None,
    }
    write_state(run_dir, state)
    return run_dir, state, draft_path


def complete_step_one(
    args: argparse.Namespace, run_dir: Path, state: dict[str, Any], draft_path: Path
) -> tuple[Path, dict[str, Any]]:
    run_id = state["run_id"]
    source_hash = state["input"]["source_sha256"]
    draft_bytes = state["input"]["content"].encode("utf-8")
    if sha256(draft_path) != source_hash or sha256_bytes(draft_bytes) != source_hash:
        raise RuntimeError("产品初稿与已保存运行输入不一致")

    if "project" not in state:
        identity, attempts = asyncio.run(
            extract_project_identity(state["input"]["content"], LLMConfig.load())
        )
        if identity["blocked_reason"]:
            raise RuntimeError(identity["blocked_reason"])
        state["project"] = {
            "topic_name": identity["topic_name"],
            "project_directory_name": identity["project_directory_name"],
            "extraction": {
                "directory_name_source": identity["directory_name_source"],
                "reason": identity["reason"],
                "attempts": attempts,
            },
        }
        write_state(run_dir, state)

    workspace_root, root_source = load_workspace_root(args.workspace_root)
    template_repository, template_source = load_template_repository()
    if not workspace_root.is_dir():
        raise RuntimeError(f"产品工作区根目录不存在：{workspace_root}")
    project_name = state["project"]["project_directory_name"]
    final_path = workspace_root / project_name
    staging_path = workspace_root / f"{project_name}.pcm-tmp-{run_id}"

    if "workspace" in state:
        recorded = state["workspace"]
        if (
            Path(recorded["root"]) != workspace_root
            or Path(recorded["staging_path"]) != staging_path
            or Path(recorded["final_path"]) != final_path
            or recorded.get("template_repository") != template_repository
        ):
            raise RuntimeError("工作区或模板配置与已有运行记录不一致")
    else:
        state["workspace"] = {
            "root": str(workspace_root),
            "root_source": root_source,
            "template_repository": template_repository,
            "template_source": template_source,
            "staging_path": str(staging_path),
            "final_path": str(final_path),
        }
        state["publication_phase"] = "intent_recorded"
        write_state(run_dir, state)

    phase = state["publication_phase"]
    if final_path.exists():
        if (
            phase == "prepared_verified"
            and not staging_path.exists()
            and verify_published_content(final_path, source_hash)
        ):
            state["publication_phase"] = "published"
            write_state(run_dir, state)
            phase = "published"
        elif (
            phase in {"published", "git_initialized"}
            and not staging_path.exists()
            and verify_published_content(final_path, source_hash)
        ):
            pass
        else:
            raise RuntimeError("最终项目路径已存在或发布现场冲突")
    elif staging_path.exists() and phase == "intent_recorded":
        state["template"] = inspect_clone(staging_path, template_repository)
        state["publication_phase"] = "clone_verified"
        write_state(run_dir, state)
        phase = "clone_verified"
    elif phase == "intent_recorded":
        state["template"] = clone_and_verify(staging_path, template_repository)
        state["publication_phase"] = "clone_verified"
        write_state(run_dir, state)
        phase = "clone_verified"

    if phase == "clone_verified":
        if not verify_clone(staging_path, state["template"]):
            raise RuntimeError("临时 clone 与已有运行证据不一致")
        prepare_staging(staging_path, draft_bytes, source_hash)
        if sha256(draft_path) != source_hash:
            raise RuntimeError("第 1 步执行期间源产品初稿发生变化")
        state["publication_phase"] = "prepared_verified"
        write_state(run_dir, state)
        phase = "prepared_verified"

    if phase == "prepared_verified" and not final_path.exists():
        if not verify_prepared(staging_path, source_hash):
            raise RuntimeError("临时工作区与发布前证据不一致")
        publish(staging_path, final_path)
        state["publication_phase"] = "published"
        write_state(run_dir, state)
        phase = "published"

    if phase == "published":
        if not verify_published_content(final_path, source_hash) or staging_path.exists():
            raise RuntimeError("最终项目工作区发布核验失败")
        state["root_repository"] = initialize_root_repository(final_path)
        state["publication_phase"] = "git_initialized"
        write_state(run_dir, state)
        phase = "git_initialized"

    if phase != "git_initialized":
        raise RuntimeError(f"第 1 步发布阶段不符合预期：{phase}")
    if not verify_published_content(final_path, source_hash) or staging_path.exists():
        raise RuntimeError("最终项目工作区核验失败")
    root_repository = inspect_root_repository(final_path)
    if state.get("root_repository") != root_repository:
        raise RuntimeError("根 Git 仓库与已有运行证据不一致")
    if sha256(draft_path) != source_hash:
        raise RuntimeError("第 1 步发布期间源产品初稿发生变化")
    published_draft = final_path / "docs" / "产品初稿.md"
    state.update(
        {
            "status": "success",
            "current_step": 1,
            "publication_phase": "git_initialized",
            "root_repository": root_repository,
            "input": {**state["input"], "published_path": str(published_draft)},
            "checks": {
                "template_capabilities_present": True,
                "upstream_git_removed": True,
                "docs_reinitialized": True,
                "draft_hash_matches": True,
                "source_draft_unchanged": sha256(draft_path) == source_hash,
                "renamed_to_final_path": True,
                "root_git_initialized": True,
                "root_git_is_final_path": root_repository["path"] == str(final_path.resolve()),
                "root_git_has_no_commits": root_repository["head"] is None,
            },
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return run_dir, workspace_result(
        "success",
        "已从固定模板发布独立产品项目工作区，并初始化零提交根 Git 仓库。",
        outputs=["docs/产品初稿.md"],
    )


def load_step_two_run(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 2 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    state = read_state(run_dir)
    if state.get("current_step") not in {1, 2}:
        raise RuntimeError("已有运行状态不属于第 1 或第 2 步")
    return run_dir, state


async def run_step_two(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    run_dir, state = load_step_two_run(args)
    return run_dir, await run_project_intake(run_dir, state)


async def run_step_three(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 3 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_foundation_selection(
        run_dir, read_state(run_dir), catalog_path=args.catalog_path
    )


def run_step_four(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 4 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, run_assemble_foundation(run_dir, read_state(run_dir))


async def run_step_five(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 5 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_project_readiness(run_dir, read_state(run_dir))


async def run_step_six(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 6 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_project_bootstrap(run_dir, read_state(run_dir))


async def run_step_seven(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 7 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_solution_design(run_dir, read_state(run_dir))


async def run_step_eight(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 8 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_initialize_repositories(run_dir, read_state(run_dir))


async def run_step_nine(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 9 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_engineering_architecture(run_dir, read_state(run_dir))


async def run_step_ten(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 10 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_ui_ux_framework(run_dir, read_state(run_dir))


async def run_step_eleven(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 11 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_requirement_breakdown(run_dir, read_state(run_dir))


async def run_step_twelve(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 12 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_requirement_registry(run_dir, read_state(run_dir))


def run_step_thirteen(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 13 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, run_requirement_selection(run_dir, read_state(run_dir))


async def run_step_fourteen(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 14 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_trd_design(run_dir, read_state(run_dir))


async def run_step_fifteen(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 15 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_development(run_dir, read_state(run_dir))


async def run_step_sixteen(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 16 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_rule_retrospective(run_dir, read_state(run_dir))


async def run_step_seventeen(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 17 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, await run_requirement_commit(run_dir, read_state(run_dir))


def run_step_eighteen(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if not args.run_id:
        raise ValueError("第 18 步需要 --run-id")
    run_dir = run_dir_for(args.run_id)
    if not run_dir.is_dir():
        raise ValueError(f"运行记录不存在：{args.run_id}")
    return run_dir, run_requirement_merge(run_dir, read_state(run_dir))


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def run_step_zero(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    draft_path = require_draft(args.product_draft)
    before_hash = sha256(draft_path)
    result = run_product_draft(draft_path)
    after_hash = sha256(draft_path)
    if before_hash != after_hash:
        raise RuntimeError("第 0 步意外修改了产品初稿")
    run_id = args.run_id or new_run_id()
    run_dir = create_run_dir(DEMO_ROOT / "runs", run_id)
    write_step_result(run_dir, 0, result)
    write_state(
        run_dir,
        {
            "run_id": run_id,
            "status": result["status"],
            "current_step": 0,
            "input": {
                "type": "product_draft",
                "source_path": str(draft_path),
                "source_sha256": before_hash,
                "content": draft_path.read_text(encoding="utf-8"),
                "published_path": None,
            },
        },
    )
    return run_dir, result


def main() -> int:
    args = parse_args()
    if args.step not in {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18}:
        print(f"步骤尚未实现：{args.step}", file=sys.stderr)
        return 2

    run_dir: Path | None = None
    error_message = ""
    no_pending = False
    try:
        if args.step == 0:
            run_dir, result = run_step_zero(args)
        elif args.step == 1:
            run_dir, state, draft_path = load_or_create_step_one_run(args)
            run_dir, result = complete_step_one(args, run_dir, state, draft_path)
        else:
            if args.step == 2:
                if not args.run_id:
                    raise ValueError("第 2 步需要 --run-id")
                run_dir = run_dir_for(args.run_id)
                run_dir, result = asyncio.run(run_step_two(args))
            else:
                if args.step == 3:
                    run_dir, result = asyncio.run(run_step_three(args))
                elif args.step == 4:
                    run_dir, result = run_step_four(args)
                else:
                    if not args.run_id:
                        raise ValueError(f"第 {args.step} 步需要 --run-id")
                    candidate = run_dir_for(args.run_id)
                    if not candidate.is_dir():
                        raise ValueError(f"运行记录不存在：{args.run_id}")
                    run_dir = candidate
                    if args.step == 5:
                        run_dir, result = asyncio.run(run_step_five(args))
                    elif args.step == 6:
                        run_dir, result = asyncio.run(run_step_six(args))
                    elif args.step == 7:
                        run_dir, result = asyncio.run(run_step_seven(args))
                    elif args.step == 8:
                        run_dir, result = asyncio.run(run_step_eight(args))
                    elif args.step == 9:
                        run_dir, result = asyncio.run(run_step_nine(args))
                    elif args.step == 10:
                        run_dir, result = asyncio.run(run_step_ten(args))
                    elif args.step == 11:
                        run_dir, result = asyncio.run(run_step_eleven(args))
                    elif args.step == 12:
                        run_dir, result = asyncio.run(run_step_twelve(args))
                    elif args.step == 13:
                        run_dir, result = run_step_thirteen(args)
                    elif args.step == 14:
                        run_dir, result = asyncio.run(run_step_fourteen(args))
                    elif args.step == 15:
                        run_dir, result = asyncio.run(run_step_fifteen(args))
                    elif args.step == 16:
                        run_dir, result = asyncio.run(run_step_sixteen(args))
                    elif args.step == 17:
                        run_dir, result = asyncio.run(run_step_seventeen(args))
                    else:
                        run_dir, result = run_step_eighteen(args)
    except ProjectIntakeBlocked as error:
        result = project_intake_result(
            "blocked",
            str(error),
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
                "resume_step": 2,
            },
        )
        error_message = str(error)
    except WorkspaceBlocked as error:
        result = workspace_result(
            "blocked",
            str(error),
            blocked={"reason": str(error), "required_inputs": [str(error)], "resume_step": 1},
        )
        error_message = str(error)
    except ProjectReadinessBlocked as error:
        result = project_readiness_result(
            "blocked",
            str(error),
            outputs=error.outputs,
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
                "resume_step": 5,
            },
        )
        error_message = str(error)
    except ProjectBootstrapBlocked as error:
        result = project_bootstrap_result(
            "blocked",
            str(error),
            outputs=error.outputs,
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
                "resume_phase": "project_initialization",
                "resume_node": PROJECT_BOOTSTRAP_NODE,
                "resume_step": 6,
            },
        )
        error_message = str(error)
    except SolutionDesignBlocked as error:
        result = solution_design_result(
            "blocked",
            str(error),
            outputs=error.outputs,
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
                "resume_phase": "project_initialization",
                "resume_node": SOLUTION_DESIGN_NODE,
                "resume_step": 7,
            },
        )
        error_message = str(error)
    except InitializeRepositoriesBlocked as error:
        result = initialize_repositories_result(
            "blocked",
            str(error),
            blocked={
                "reason": error.reason,
                "required_inputs": error.required_inputs,
                "applicable_repositories": error.applicable_repositories,
            },
        )
        error_message = str(error)
    except EngineeringArchitectureBlocked as error:
        result = engineering_architecture_result(
            "blocked",
            str(error),
            outputs=error.outputs,
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
                "resume_phase": "project_initialization",
                "resume_node": ENGINEERING_ARCHITECTURE_NODE,
                "resume_step": 9,
            },
        )
        error_message = str(error)
    except UIUXFrameworkBlocked as error:
        result = ui_ux_framework_result(
            "blocked",
            str(error),
            outputs=error.outputs,
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
                "resume_phase": "project_initialization",
                "resume_node": UI_UX_FRAMEWORK_NODE,
                "resume_step": 10,
            },
        )
        error_message = str(error)
    except RequirementBreakdownBlocked as error:
        result = requirement_breakdown_result(
            "blocked",
            str(error),
            outputs=error.outputs,
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
                "resume_phase": "project_initialization",
                "resume_node": REQUIREMENT_BREAKDOWN_NODE,
                "resume_step": 11,
            },
        )
        error_message = str(error)
    except RuleRetrospectiveBlocked as error:
        result = rule_retrospective_result(
            "blocked",
            str(error),
            requirement_id=error.requirement_id,
            development_session_id=error.development_session_id,
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
            },
        )
        error_message = str(error)
    except DevelopmentBlocked as error:
        result = development_result(
            "blocked",
            str(error),
            requirement_id=error.requirement_id,
            trd_path=error.trd_path,
            development_session_id=error.development_session_id,
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
            },
        )
        error_message = str(error)
    except TRDDesignBlocked as error:
        result = trd_design_result(
            "blocked",
            str(error),
            requirement_id=error.requirement_id,
            branch=error.branch,
            trd_path=error.trd_path,
            trd_session_id=error.trd_session_id,
            outputs=error.outputs,
            blocked={
                "reason": str(error),
                "required_inputs": error.required_inputs,
                "resume_phase": "phase_1_requirement_development",
                "resume_node": TRD_DESIGN_NODE,
                "resume_step": 14,
            },
        )
        error_message = str(error)
    except Exception as error:  # noqa: BLE001 - 顶层入口必须将所有步骤异常转换为结果。
        if args.step == 2:
            result_factory = project_intake_result
        elif args.step == 4:
            result_factory = assembly_result
        elif args.step == 5:
            result_factory = project_readiness_result
        elif args.step == 6:
            result_factory = project_bootstrap_result
        elif args.step == 7:
            result_factory = solution_design_result
        elif args.step == 8:
            result_factory = initialize_repositories_result
        elif args.step == 9:
            result_factory = engineering_architecture_result
        elif args.step == 10:
            result_factory = ui_ux_framework_result
        elif args.step == 11:
            result_factory = requirement_breakdown_result
        elif args.step == 12:
            result_factory = requirement_registry_result
        else:
            result_factory = workspace_result
        if args.step == 18:
            scope = None
            if run_dir is not None:
                try:
                    scope = requirement_merge_failure_scope(run_dir, read_state(run_dir))
                except Exception:  # noqa: BLE001 - 失败结果只能使用可安全确认的活动需求。
                    scope = None
            result = requirement_merge_result(
                "failed",
                "需求分支程序化合并失败。",
                requirement_id=scope["requirement_id"] if scope else None,
                branch=scope["branch"] if scope else None,
                error={
                    "type": type(error).__name__,
                    "message": "需求分支程序化合并未完成。",
                },
            )
            error_message = "需求分支程序化合并失败。"
        elif args.step == 17:
            scope = None
            if run_dir is not None:
                try:
                    scope = requirement_commit_failure_scope(run_dir, read_state(run_dir))
                except Exception:  # noqa: BLE001 - 失败结果只能使用可安全确认的活动需求。
                    scope = None
            result = requirement_commit_result(
                "failed",
                "需求变更统一提交失败。",
                requirement_id=scope["requirement_id"] if scope else None,
                branch=scope["branch"] if scope else None,
                error={
                    "type": type(error).__name__,
                    "message": "需求变更统一提交未完成。",
                },
            )
            error_message = "需求变更统一提交失败。"
        elif args.step == 16:
            scope = None
            if run_dir is not None:
                try:
                    scope = rule_retrospective_failure_scope(run_dir, read_state(run_dir))
                except Exception:  # noqa: BLE001 - 失败结果只能使用可安全确认的活动需求。
                    scope = None
            result = rule_retrospective_result(
                "failed",
                "规则复盘失败。",
                requirement_id=scope["requirement_id"] if scope else None,
                development_session_id=scope["development_session_id"] if scope else None,
                error={
                    "type": type(error).__name__,
                    "message": "规则复盘未完成。",
                },
            )
            error_message = "规则复盘失败。"
        elif args.step == 15:
            scope = None
            if run_dir is not None:
                try:
                    scope = development_failure_scope(run_dir, read_state(run_dir))
                except Exception:  # noqa: BLE001 - 失败结果只能使用可安全确认的活动需求。
                    scope = None
            result = development_result(
                "failed",
                "需求实现与验证失败。",
                requirement_id=scope["requirement_id"] if scope else None,
                trd_path=scope["trd_path"] if scope else None,
                development_session_id=scope["development_session_id"] if scope else None,
                error={
                    "type": type(error).__name__,
                    "message": "需求实现与验证未完成。",
                },
            )
            error_message = "需求实现与验证失败。"
        elif args.step == 14:
            scope = None
            if run_dir is not None:
                try:
                    scope = trd_design_failure_scope(run_dir, read_state(run_dir))
                except Exception:  # noqa: BLE001 - 失败结果只能使用可安全确认的活动需求。
                    scope = None
            result = trd_design_result(
                "failed",
                "活动 TRD 设计失败。",
                requirement_id=scope["requirement_id"] if scope else None,
                branch=scope["branch"] if scope else None,
                trd_path=scope["trd_path"] if scope else None,
                trd_session_id=scope["trd_session_id"] if scope else None,
                error={
                    "type": type(error).__name__,
                    "message": "活动 TRD 设计未完成。",
                },
            )
            error_message = "活动 TRD 设计失败。"
        elif args.step == 13:
            scope = None
            if run_dir is not None:
                try:
                    scope = requirement_selection_failure_scope(run_dir, read_state(run_dir))
                except Exception:  # noqa: BLE001 - 失败结果只能使用可安全确认的活动需求。
                    scope = None
            safe_message = (
                str(error)
                if isinstance(error, (NoPendingRequirements, RequirementSelectionError))
                else "需求选择未完成。"
            )
            result = requirement_selection_result(
                "failed",
                "需求选择失败。",
                requirement_id=scope[0] if scope else None,
                branch=scope[1] if scope else None,
                error={
                    "type": type(error).__name__,
                    "message": safe_message,
                },
            )
            error_message = safe_message
            no_pending = isinstance(error, NoPendingRequirements)
        elif args.step == 12:
            result = result_factory(
                "failed",
                "需求注册表初始化失败。",
                error={
                    "type": type(error).__name__,
                    "message": "需求注册表初始化未完成。",
                },
            )
            error_message = "需求注册表初始化失败。"
        else:
            result = result_factory(
                "failed",
                f"第 {args.step} 步执行失败。",
                error={"type": type(error).__name__, "message": str(error)},
            )
            error_message = f"{type(error).__name__}: {error}"

        if isinstance(error, AIDecisionFailure):
            result["error"] = error.as_error()
            error_message = str(error)

    if result["status"] != "success" and not error_message:
        detail = result.get("blocked") or result.get("error") or {}
        error_message = str(detail.get("reason") or detail.get("message") or result["summary"])

    selection_scope: tuple[str, str] | None = None
    trd_scope: dict[str, str | None] | None = None
    development_scope: dict[str, str | None] | None = None
    rule_retrospective_scope: dict[str, str] | None = None
    requirement_commit_scope: dict[str, str] | None = None
    requirement_merge_scope: dict[str, str] | None = None
    if run_dir is not None and args.step == 18:
        try:
            requirement_merge_state = read_state(run_dir)
            requirement_merge_scope = requirement_merge_failure_scope(
                run_dir, requirement_merge_state
            )
            protected_success = has_requirement_merge_success(
                run_dir, requirement_merge_state
            )
        except Exception:  # noqa: BLE001 - 状态损坏时仍需返回脱敏失败信息。
            protected_success = False
    elif run_dir is not None and args.step == 17:
        try:
            requirement_commit_state = read_state(run_dir)
            requirement_commit_scope = requirement_commit_failure_scope(
                run_dir, requirement_commit_state
            )
            protected_success = has_requirement_commit_success(
                run_dir, requirement_commit_state
            )
        except Exception:  # noqa: BLE001 - 状态损坏时仍需返回脱敏失败信息。
            protected_success = False
    elif run_dir is not None and args.step == 16:
        try:
            rule_retrospective_state = read_state(run_dir)
            rule_retrospective_scope = rule_retrospective_failure_scope(
                run_dir, rule_retrospective_state
            )
            protected_success = has_rule_retrospective_success(
                run_dir, rule_retrospective_state
            )
        except Exception:  # noqa: BLE001 - 状态损坏时仍需返回脱敏失败信息。
            protected_success = False
    elif run_dir is not None and args.step == 15:
        try:
            development_state = read_state(run_dir)
            development_scope = development_failure_scope(run_dir, development_state)
            protected_success = has_development_success(run_dir, development_state)
        except Exception:  # noqa: BLE001 - 状态损坏时仍需返回脱敏失败信息。
            protected_success = False
    elif run_dir is not None and args.step == 14:
        try:
            trd_state = read_state(run_dir)
            trd_scope = trd_design_failure_scope(run_dir, trd_state)
            protected_success = has_trd_design_success(run_dir, trd_state)
        except Exception:  # noqa: BLE001 - 状态损坏时仍需返回脱敏失败信息。
            protected_success = False
    elif run_dir is not None and args.step == 13:
        try:
            selection_state = read_state(run_dir)
            selection_scope = requirement_selection_failure_scope(run_dir, selection_state)
            protected_success = has_requirement_selection_success(run_dir, selection_state)
        except Exception:  # noqa: BLE001 - 状态损坏时仍需返回脱敏失败信息。
            protected_success = False
    else:
        protected_success = (
            run_dir is not None
            and args.step in {8, 9, 10, 11, 12}
            and has_step_success(run_dir, args.step)
        )

    if run_dir is not None and args.step == 18:
        if (
            result["status"] != "success"
            and not protected_success
            and requirement_merge_scope is not None
        ):
            try:
                state = read_state(run_dir)
            except Exception:  # noqa: BLE001 - 状态损坏时不能构造 scoped 失败结果。
                state = None
            if state is not None:
                state.update(
                    {
                        "status": result["status"],
                        "phase": "phase_1_requirement_development",
                        "step": 18,
                        "current_step": 18,
                        "current_node": REQUIREMENT_MERGE_NODE,
                        "blocked": result["blocked"],
                        "error": result["error"],
                    }
                )
                write_state(run_dir, state)
                write_requirement_step_result(
                    run_dir,
                    requirement_merge_scope["requirement_id"],
                    18,
                    result,
                )
    elif run_dir is not None and args.step == 17:
        if (
            result["status"] != "success"
            and not protected_success
            and requirement_commit_scope is not None
        ):
            try:
                state = read_state(run_dir)
            except Exception:  # noqa: BLE001 - 状态损坏时不能构造 scoped 失败结果。
                state = None
            if state is not None:
                state.update(
                    {
                        "status": result["status"],
                        "phase": "phase_1_requirement_development",
                        "step": 17,
                        "current_step": 17,
                        "current_node": REQUIREMENT_COMMIT_NODE,
                        "blocked": result["blocked"],
                        "error": result["error"],
                    }
                )
                write_state(run_dir, state)
                write_requirement_step_result(
                    run_dir,
                    requirement_commit_scope["requirement_id"],
                    17,
                    result,
                )
    elif run_dir is not None and args.step == 16:
        if (
            result["status"] != "success"
            and not protected_success
            and rule_retrospective_scope is not None
        ):
            try:
                state = read_state(run_dir)
            except Exception:  # noqa: BLE001 - 状态损坏时不能构造 scoped 失败结果。
                state = None
            if state is not None:
                state.update(
                    {
                        "status": result["status"],
                        "phase": "phase_1_requirement_development",
                        "step": 16,
                        "current_step": 16,
                        "current_node": RULE_RETROSPECTIVE_NODE,
                        "blocked": result["blocked"],
                        "error": result["error"],
                    }
                )
                write_state(run_dir, state)
                write_requirement_step_result(
                    run_dir,
                    rule_retrospective_scope["requirement_id"],
                    16,
                    result,
                )
    elif run_dir is not None and args.step == 15:
        if result["status"] != "success" and not protected_success and development_scope is not None:
            try:
                state = read_state(run_dir)
            except Exception:  # noqa: BLE001 - 状态损坏时不能构造 scoped 失败结果。
                state = None
            if state is not None:
                state.update(
                    {
                        "status": result["status"],
                        "phase": "phase_1_requirement_development",
                        "step": 15,
                        "current_step": 15,
                        "current_node": DEVELOPMENT_NODE,
                        "blocked": result["blocked"],
                        "error": result["error"],
                    }
                )
                write_state(run_dir, state)
                write_requirement_step_result(
                    run_dir, str(development_scope["requirement_id"]), 15, result
                )
    elif run_dir is not None and args.step == 14:
        if result["status"] != "success" and not protected_success and trd_scope is not None:
            try:
                state = read_state(run_dir)
            except Exception:  # noqa: BLE001 - 状态损坏时不能构造 scoped 失败结果。
                state = None
            if state is not None:
                state.update(
                    {
                        "status": result["status"],
                        "step": 14,
                        "current_step": 14,
                        "current_node": TRD_DESIGN_NODE,
                        "blocked": result["blocked"],
                        "error": result["error"],
                    }
                )
                write_state(run_dir, state)
                write_requirement_step_result(
                    run_dir, str(trd_scope["requirement_id"]), 14, result
                )
    elif run_dir is not None and args.step == 13:
        if result["status"] != "success" and not protected_success:
            try:
                state = read_state(run_dir)
            except Exception:  # noqa: BLE001 - 状态损坏时不能构造 scoped 失败结果。
                state = None
            at_selection_anchor = (
                state is not None
                and state.get("phase") == SELECT_REQUIREMENT_PHASE
                and (
                    state.get("step"),
                    state.get("current_step"),
                    state.get("current_node"),
                )
                == (13, 13, SELECT_REQUIREMENT_NODE)
            )
            if state is not None and at_selection_anchor and selection_scope is not None:
                state.update(
                    {
                        "status": "failed",
                        "step": 13,
                        "current_step": 13,
                        "current_node": SELECT_REQUIREMENT_NODE,
                        "blocked": None,
                        "error": result["error"],
                    }
                )
                write_state(run_dir, state)
                write_requirement_step_result(run_dir, selection_scope[0], 13, result)
            elif state is not None and at_selection_anchor and not no_pending:
                state.update(
                    {
                        "status": "failed",
                        "blocked": None,
                        "error": result["error"],
                    }
                )
                write_state(run_dir, state)
    elif run_dir is not None and args.step in {1, 2, 5, 6, 7, 8, 9, 10, 11, 12}:
        if result["status"] != "success" and not protected_success:
            try:
                state = read_state(run_dir)
            except Exception:  # noqa: BLE001 - 状态损坏时仍需保存步骤失败结果。
                state = None
            if state is not None:
                update = {
                    "status": result["status"],
                    "blocked": result["blocked"],
                    "error": result["error"],
                }
                if args.step != 12:
                    update["current_step"] = args.step
                if args.step == 5:
                    update.update({"step": 5, "current_node": PROJECT_READINESS_NODE})
                elif args.step == 6:
                    update.update({"step": 6, "current_node": PROJECT_BOOTSTRAP_NODE})
                elif args.step == 7:
                    update.update({"step": 7, "current_node": SOLUTION_DESIGN_NODE})
                elif args.step == 8:
                    update.update({"step": 8, "current_node": INITIALIZE_REPOSITORIES_NODE})
                elif args.step == 9:
                    update.update({"step": 9, "current_node": ENGINEERING_ARCHITECTURE_NODE})
                elif args.step == 10:
                    update.update({"step": 10, "current_node": UI_UX_FRAMEWORK_NODE})
                elif args.step == 11:
                    update.update({"step": 11, "current_node": REQUIREMENT_BREAKDOWN_NODE})
                state.update(update)
                write_state(run_dir, state)
        if not protected_success:
            write_step_result(run_dir, args.step, result)

    if run_dir is not None:
        scoped_path: Path | None = None
        if args.step in {13, 14, 15, 16, 17, 18}:
            requirement_id = result.get("requirement_id")
            if isinstance(requirement_id, str):
                try:
                    scoped_path = requirement_step_result_path(
                        run_dir, requirement_id, args.step
                    )
                except ValueError:
                    scoped_path = None
        if result["status"] != "success":
            detail_path = scoped_path if scoped_path is not None else run_dir / "state.json"
            print(
                f"步骤 {args.step} {result['status']}：{error_message}\n"
                f"详细结果：{detail_path}",
                file=sys.stderr,
            )
        else:
            print(scoped_path or run_dir / "steps" / f"{args.step:02d}.json")
    else:
        print(result["summary"], file=sys.stderr)
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
