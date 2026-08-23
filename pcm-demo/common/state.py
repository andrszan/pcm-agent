from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.files import write_json


def create_run_dir(runs_dir: Path, run_id: str) -> Path:
    if Path(run_id).name != run_id or run_id in {"", ".", ".."}:
        raise ValueError(f"无效运行 ID：{run_id}")
    resolved_runs_dir = runs_dir.resolve()
    run_dir = (resolved_runs_dir / run_id).resolve()
    try:
        run_dir.relative_to(resolved_runs_dir)
    except ValueError as error:
        raise ValueError(f"无效运行 ID：{run_id}") from error
    if run_dir.exists():
        raise FileExistsError(f"运行目录已存在，拒绝覆盖：{run_dir}")
    (run_dir / "steps").mkdir(parents=True)
    (run_dir / "logs").mkdir()
    return run_dir


def read_state(run_dir: Path) -> dict[str, Any]:
    data = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("运行状态必须是 JSON 对象")
    return data


def step_result_status(run_dir: Path, step: int) -> str | None:
    path = run_dir / "steps" / f"{step:02d}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("步骤结果不可读取") from error
    status = data.get("status") if isinstance(data, dict) else None
    if status not in {"success", "blocked", "failed"}:
        raise RuntimeError("步骤结果状态不符合约定")
    return status


def write_state(run_dir: Path, state: dict[str, Any]) -> None:
    write_json(run_dir / "state.json", state)


def write_step_result(run_dir: Path, step: int, result: dict[str, Any]) -> None:
    write_json(run_dir / "steps" / f"{step:02d}.json", result)
