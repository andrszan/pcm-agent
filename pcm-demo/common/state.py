from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common.files import write_json


REQUIREMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def is_valid_requirement_id(value: object) -> bool:
    return isinstance(value, str) and REQUIREMENT_ID_PATTERN.fullmatch(value) is not None


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


def requirement_step_result_path(run_dir: Path, requirement_id: str, step: int) -> Path:
    if not is_valid_requirement_id(requirement_id):
        raise ValueError("无效需求 ID")
    if type(step) is not int or step < 0:
        raise ValueError("无效步骤编号")
    requirements = run_dir / "steps" / "requirements"
    for directory in (run_dir, run_dir / "steps", requirements, requirements / requirement_id):
        if directory.is_symlink():
            raise ValueError("需求结果目录不能是符号链接")
    return requirements / requirement_id / f"{step:02d}.json"


def write_requirement_step_result(
    run_dir: Path, requirement_id: str, step: int, result: dict[str, Any]
) -> None:
    path = requirement_step_result_path(run_dir, requirement_id, step)
    path.parent.mkdir(parents=True, exist_ok=True)
    path = requirement_step_result_path(run_dir, requirement_id, step)
    if path.is_symlink():
        raise ValueError("需求结果目录不能是符号链接")
    write_json(path, result)
