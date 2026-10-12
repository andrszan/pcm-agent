from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common.coordination import acquire_product_lock, coordination_root, get_product, product_key
from common.remote_sync import push_inputs, push_module
from common.state import read_state


DEMO_ROOT = Path(__file__).resolve().parent
RUNS_DIR = DEMO_ROOT / "runs"
COORDINATION_ROOT = coordination_root(DEMO_ROOT)


def push_project(path: Path) -> list[dict]:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError("产品工作区必须是绝对路径的真实目录")
    key, canonical = product_key(path)
    with acquire_product_lock(COORDINATION_ROOT, "manual-push", key, canonical):
        record = get_product(COORDINATION_ROOT, key)
        owner = record.get("owner_run_id")
        if (
            record.get("product_path") != str(canonical)
            or not isinstance(owner, str)
            or owner in {"", ".", ".."}
            or Path(owner).name != owner
        ):
            raise RuntimeError("产品登记路径或创建 run 归属无效")
        run_dir = RUNS_DIR / owner
        if run_dir.is_symlink() or not run_dir.resolve().is_relative_to(RUNS_DIR.resolve()):
            raise RuntimeError("产品创建 run 路径不合法")
        state = read_state(run_dir)
        if state.get("workspace", {}).get("final_path") != str(canonical):
            raise RuntimeError("创建 run 的工作区与当前产品不一致")
        return push_module().push_repositories(push_inputs(state))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="推送指定 PCM 产品各适用仓库的 main，不提交或运行开发流程")
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        results = push_project(args.workspace)
    except (OSError, RuntimeError, ValueError) as error:
        results = getattr(error, "results", None)
        if results is not None:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"产品推送未完成：{error}", file=sys.stderr)
        return 2 if getattr(error, "blocked", False) else 1
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
