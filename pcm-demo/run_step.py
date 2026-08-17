from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from common.files import sha256
from common.state import create_run_dir, write_state, write_step_result
from steps.step_00_product_draft import run as run_product_draft

DEMO_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行已实现的 PCM Demo 步骤")
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--run-id")
    return parser.parse_args()


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    args = parse_args()
    if args.step != 0:
        print(f"步骤尚未实现：{args.step}", file=sys.stderr)
        return 2

    prd_path = args.prd.resolve()
    if not prd_path.is_file():
        print(f"PRD 文件不存在或不可读：{prd_path}", file=sys.stderr)
        return 2

    try:
        before_hash = sha256(prd_path)
        result = run_product_draft(prd_path)
        after_hash = sha256(prd_path)
        if before_hash != after_hash:
            raise RuntimeError("第 0 步意外修改了源 PRD")
    except (OSError, UnicodeError, RuntimeError) as error:
        print(f"运行失败：{type(error).__name__}: {error}", file=sys.stderr)
        return 1

    try:
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
    except (OSError, ValueError) as error:
        print(f"运行失败：{type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print(run_dir / "steps" / "00.json")
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
