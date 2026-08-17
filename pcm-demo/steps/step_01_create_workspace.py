from __future__ import annotations

import shutil
from pathlib import Path

from common.files import sha256

CAPABILITY_FILES = (
    Path("CLAUDE.md"),
    Path("AGENTS.md"),
    Path(".claude/skills/project-intake/SKILL.md"),
)


def run(source_prd: Path, workspace: Path, capability_root: Path) -> dict[str, object]:
    if workspace.exists():
        return {
            "step": 1,
            "name": "建立项目工作区",
            "status": "blocked",
            "summary": "预期工作区已存在，无法确认归属，已拒绝覆盖。",
            "applicable": True,
            "outputs": [],
            "blocked": {
                "reason": "工作区已存在",
                "required_inputs": ["提供新的 run ID 或确认现有工作区归属"],
                "resume_step": 1,
            },
            "error": None,
        }

    missing = [str(path) for path in CAPABILITY_FILES if not (capability_root / path).is_file()]
    if missing:
        return {
            "step": 1,
            "name": "建立项目工作区",
            "status": "failed",
            "summary": "缺少创建工作区所需的项目能力文件。",
            "applicable": True,
            "outputs": [],
            "blocked": None,
            "error": {
                "type": "missing_capability_files",
                "message": f"缺少能力文件：{', '.join(missing)}",
            },
        }

    source_hash = sha256(source_prd)
    workspace_prd = workspace / "docs" / "prd" / source_prd.name
    workspace_prd.parent.mkdir(parents=True)
    for relative_path in CAPABILITY_FILES:
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(capability_root / relative_path, target)
    shutil.copy2(source_prd, workspace_prd)

    if sha256(workspace_prd) != source_hash or sha256(source_prd) != source_hash:
        raise RuntimeError("PRD 复制或源文件完整性核验失败")

    return {
        "step": 1,
        "name": "建立项目工作区",
        "status": "success",
        "summary": "已创建独立工作区并复制 PRD 与 project-intake 最小能力。",
        "applicable": True,
        "outputs": [str(workspace), str(workspace_prd)],
        "blocked": None,
        "error": None,
    }
