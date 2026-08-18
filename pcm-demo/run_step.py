from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any

from common.files import sha256
from common.state import create_run_dir, read_state, write_state, write_step_result
from config import LLMConfig, load_template_repository, load_workspace_root
from steps.step_00_product_draft import run as run_product_draft
from steps.step_01_create_workspace import extract_project_identity
from steps.step_01_create_workspace import (
    WorkspaceBlocked,
    clone_and_verify,
    inspect_clone,
    prepare_staging,
    publish,
    result as workspace_result,
    verify_clone,
    verify_prepared,
)
from steps.step_02_project_intake import ProjectIntakeBlocked
from steps.step_02_project_intake import result as project_intake_result
from steps.step_02_project_intake import run as run_project_intake

DEMO_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行已实现的 PCM Demo 步骤")
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--product-draft", "--prd", dest="product_draft", type=Path)
    parser.add_argument("--workspace-root", type=Path)
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
        if phase == "prepared_verified" and not staging_path.exists() and verify_prepared(final_path, source_hash):
            state["publication_phase"] = "published"
        elif phase == "published" and not staging_path.exists() and verify_prepared(final_path, source_hash):
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

    if not verify_prepared(final_path, source_hash) or staging_path.exists():
        raise RuntimeError("最终项目工作区核验失败")
    if sha256(draft_path) != source_hash:
        raise RuntimeError("第 1 步发布期间源产品初稿发生变化")
    published_draft = final_path / "docs" / "产品初稿.md"
    state.update(
        {
            "status": "success",
            "current_step": 1,
            "publication_phase": "published",
            "input": {**state["input"], "published_path": str(published_draft)},
            "checks": {
                "template_capabilities_present": True,
                "git_removed": True,
                "docs_reinitialized": True,
                "draft_hash_matches": True,
                "source_draft_unchanged": sha256(draft_path) == source_hash,
                "renamed_to_final_path": True,
            },
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return run_dir, workspace_result(
        "success",
        "已从固定模板发布独立产品项目工作区。",
        outputs=[str(final_path), str(published_draft)],
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
    if args.step not in {0, 1, 2}:
        print(f"步骤尚未实现：{args.step}", file=sys.stderr)
        return 2

    run_dir: Path | None = None
    error_message = ""
    try:
        if args.step == 0:
            run_dir, result = run_step_zero(args)
        elif args.step == 1:
            run_dir, state, draft_path = load_or_create_step_one_run(args)
            run_dir, result = complete_step_one(args, run_dir, state, draft_path)
        else:
            if not args.run_id:
                raise ValueError("第 2 步需要 --run-id")
            run_dir = run_dir_for(args.run_id)
            run_dir, result = asyncio.run(run_step_two(args))
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
    except Exception as error:
        result_factory = project_intake_result if args.step == 2 else workspace_result
        result = result_factory(
            "failed",
            f"第 {args.step} 步执行失败。",
            error={"type": type(error).__name__, "message": str(error)},
        )
        error_message = f"{type(error).__name__}: {error}"

    if run_dir is not None and args.step in {1, 2}:
        if result["status"] != "success":
            state = read_state(run_dir)
            state.update(
                {
                    "status": result["status"],
                    "current_step": args.step,
                    "blocked": result["blocked"],
                    "error": result["error"],
                }
            )
            write_state(run_dir, state)
        write_step_result(run_dir, args.step, result)

    if run_dir is not None:
        if result["status"] != "success":
            print(
                f"步骤 {args.step} {result['status']}：{error_message}\n"
                f"详细结果：{run_dir / 'steps' / f'{args.step:02d}.json'}",
                file=sys.stderr,
            )
        else:
            print(run_dir / "steps" / f"{args.step:02d}.json")
    else:
        print(result["summary"], file=sys.stderr)
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
