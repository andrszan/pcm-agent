from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_workspace_output(workspace: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts:
        raise ValueError(f"步骤产物路径必须相对于产品工作区：{value}")
    workspace = workspace.resolve()
    path = workspace / relative
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as error:
        raise ValueError(f"步骤产物路径超出产品工作区：{value}") from error
    return path


def write_json(path: Path, data: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
