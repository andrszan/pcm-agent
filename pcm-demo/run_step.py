from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any

from common.files import sha256
from common.state import (
    create_run_dir,
    open_run_dir,
    read_json,
    write_state,
    write_step_result,
)
from steps.step_00_product_draft import run as run_product_draft
from steps.step_01_create_workspace import run as run_create_workspace

DEMO_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DEMO_ROOT.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行已实现的 PCM Demo 步骤")
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--prd", type=Path)
    parser.add_argument("--run-id")
    return parser.parse_args()


def new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{token_hex(3)}"


def require_prd(path: Path | None) -> Path:
    if path is None:
        raise ValueError("当前运行需要 --prd")
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"PRD 文件不存在或不可读：{resolved}")
    return resolved


def trusted_step_zero_run(run_id: str) -> tuple[Path, Path, dict[str, Any]]:
    run_dir = open_run_dir(DEMO_ROOT / "runs", run_id)
    state = read_json(run_dir / "state.json")
    result = read_json(run_dir / "steps" / "00.json")
    source = Path(str((state.get("input") or {}).get("source_prd", ""))).resolve()
    expected_hash = (state.get("input") or {}).get("source_sha256")
    if not (
        state.get("run_id") == run_id
        and state.get("status") == "success"
        and state.get("current_step") == 0
        and result.get("step") == 0
        and result.get("status") == "success"
        and source.is_file()
        and expected_hash
        and sha256(source) == expected_hash
    ):
        raise ValueError(f"运行目录不是可信的第 0 步结果：{run_dir}")
    return run_dir, source, state


def run_step_zero(args: argparse.Namespace) -> int:
    prd_path = require_prd(args.prd)
    before_hash = sha256(prd_path)
    result = run_product_draft(prd_path)
    after_hash = sha256(prd_path)
    if before_hash != after_hash:
        raise RuntimeError("第 0 步意外修改了源 PRD")

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
                "type": "prd",
                "source_prd": str(prd_path),
                "source_sha256": before_hash,
                "source_sha256_after_step": after_hash,
            },
        },
    )
    print(run_dir / "steps" / "00.json")
    return 0 if result["status"] == "success" else 1


def run_step_one(args: argparse.Namespace) -> int:
    if args.run_id and (DEMO_ROOT / "runs" / args.run_id).exists():
        run_dir, prd_path, state = trusted_step_zero_run(args.run_id)
        if args.prd and args.prd.resolve() != prd_path:
            raise ValueError("--prd 与第 0 步记录的源 PRD 不一致")
        run_id = args.run_id
    else:
        prd_path = require_prd(args.prd)
        run_id = args.run_id or new_run_id()
        run_dir = create_run_dir(DEMO_ROOT / "runs", run_id)
        source_hash = sha256(prd_path)
        state = {
            "run_id": run_id,
            "status": "running",
            "current_step": 1,
            "input": {
                "type": "prd",
                "source_prd": str(prd_path),
                "source_sha256": source_hash,
                "source_sha256_after_step": source_hash,
            },
        }

    before_hash = sha256(prd_path)
    state.update({"status": "running", "current_step": 1})
    write_state(run_dir, state)
    workspace = (DEMO_ROOT / "workspace" / run_id).resolve()
    try:
        result = run_create_workspace(prd_path, workspace, REPO_ROOT)
        after_hash = sha256(prd_path)
        if before_hash != after_hash:
            raise RuntimeError("第 1 步意外修改了源 PRD")
    except (OSError, RuntimeError) as error:
        result = {
            "step": 1,
            "name": "建立项目工作区",
            "status": "failed",
            "summary": "建立项目工作区时发生错误。",
            "applicable": True,
            "outputs": [],
            "blocked": None,
            "error": {
                "type": type(error).__name__,
                "message": str(error),
            },
        }
        state.update({"status": "failed", "current_step": 1, "error": result["error"]})
        write_step_result(run_dir, 1, result)
        write_state(run_dir, state)
        print(run_dir / "steps" / "01.json")
        return 1

    if result["status"] == "success":
        workspace_prd = workspace / "docs" / "prd" / prd_path.name
        state.update(
            {
                "status": "success",
                "current_step": 1,
                "input": {
                    "type": "prd",
                    "source_prd": str(prd_path),
                    "source_sha256": before_hash,
                    "source_sha256_after_step": after_hash,
                    "workspace_prd": str(workspace_prd),
                },
                "workspace": str(workspace),
                "blocked": None,
                "error": None,
            }
        )
    else:
        state.update(
            {
                "status": result["status"],
                "current_step": 1,
                "blocked": result["blocked"],
                "error": result["error"],
            }
        )
    write_step_result(run_dir, 1, result)
    write_state(run_dir, state)
    print(run_dir / "steps" / "01.json")
    return 0 if result["status"] == "success" else 1


def main() -> int:
    args = parse_args()
    if args.step not in {0, 1}:
        print(f"步骤尚未实现：{args.step}", file=sys.stderr)
        return 2

    try:
        return run_step_zero(args) if args.step == 0 else run_step_one(args)
    except (OSError, UnicodeError, RuntimeError, ValueError) as error:
        print(f"运行失败：{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
