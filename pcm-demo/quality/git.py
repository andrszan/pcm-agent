from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def git(path: Path, *args: str, optional: bool = False) -> str | None:
    process = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, timeout=120,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    )
    if process.returncode:
        if optional and process.returncode == 1:
            return None
        raise RuntimeError(f"Git 操作失败：{' '.join(args[:2])}（{path.name}）")
    return process.stdout if "-z" in args else process.stdout.strip()


def workspace(state: dict[str, Any]) -> Path:
    value = state.get("workspace", {}).get("final_path")
    root = state.get("workspace", {}).get("root")
    if not isinstance(value, str) or not isinstance(root, str):
        raise RuntimeError("产品工作区记录不完整")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir() or path.resolve().parent != Path(root).resolve():
        raise RuntimeError("产品工作区路径与来源不一致")
    return path.resolve()


def repositories(state: dict[str, Any]) -> list[tuple[str, Path]]:
    root = workspace(state)
    names = state.get("applicable_repositories")
    records = state.get("repositories")
    if not isinstance(names, list) or not names or names[0] != "root" or len(set(names)) != len(names):
        raise RuntimeError("适用仓库清单无效")
    if not isinstance(records, list) or len(records) != len(names):
        raise RuntimeError("适用仓库路径记录不完整")
    result = []
    for name, record in zip(names, records, strict=True):
        if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
            raise RuntimeError("仓库名称不合法")
        path = root if name == "root" else root / name
        if record.get("name") != name or record.get("path") != str(path):
            raise RuntimeError("仓库描述与产品路径不一致")
        result.append((name, path))
    return result


def clean_repository(path: Path, branch: str) -> str:
    if path.is_symlink() or not path.is_dir() or git(path, "rev-parse", "--show-toplevel") != str(path):
        raise RuntimeError("目标不是自身独立 Git 仓库")
    check_operations(path)
    if git(path, "branch", "--show-current") != branch:
        raise RuntimeError(f"仓库 {path.name} 不在预期分支 {branch}")
    if git(path, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError(f"仓库 {path.name} 存在未提交变更；保留现场，不自动清理")
    return str(git(path, "rev-parse", "HEAD"))


def check_operations(path: Path) -> None:
    for reference in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if git(path, "rev-parse", "-q", "--verify", reference, optional=True):
            raise RuntimeError("仓库有进行中的 Git 操作")
    for name in ("rebase-merge", "rebase-apply", "BISECT_START", "sequencer"):
        value = Path(str(git(path, "rev-parse", "--git-path", name)))
        if (value if value.is_absolute() else path / value).exists():
            raise RuntimeError("仓库有进行中的 Git 操作")


def main_versions(state: dict[str, Any]) -> dict[str, str]:
    return {name: clean_repository(path, "main") for name, path in repositories(state)}


def branch_tip(path: Path, branch: str) -> str | None:
    return git(path, "rev-parse", "-q", "--verify", f"refs/heads/{branch}", optional=True)


def ancestor(path: Path, before: str, after: str) -> bool:
    return git(path, "merge-base", "--is-ancestor", before, after, optional=True) is not None


def changed_paths(path: Path, base: str) -> set[str]:
    tracked = git(path, "diff", "--name-only", "-z", base) or ""
    untracked = git(path, "ls-files", "--others", "--exclude-standard", "-z") or ""
    return {name for text in (tracked, untracked) for name in text.split("\0") if name}


def validate_document_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) < 2 or path.parts[0] != "docs" or path.suffix != ".md":
        raise ValueError("入池只允许产品 docs 内明确的 Markdown 文档")
    if path.parts[1] in {"trd", "ignore"}:
        raise ValueError("入池不能修改历史 TRD 或私密资源资料")
    return path.as_posix()
