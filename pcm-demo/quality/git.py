from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import Any


def git(path: Path, *args: str, optional: bool = False) -> str | None:
    process = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, timeout=120,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_") and key.upper() != "PCM_GITLAB_TOKEN"},
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


def validate_adoption(path: Path, record: dict[str, Any], *, branches: tuple[str, ...] = ("main",)) -> str:
    """只接管清单中当前未暂存的普通文件，不改变一般 clean main 合同。"""
    if path.is_symlink() or not path.is_dir() or git(path, "rev-parse", "--show-toplevel") != str(path):
        raise RuntimeError("接管目标不是独立 Git 仓库")
    check_operations(path)
    head = record["head"]
    if (git(path, "branch", "--show-current") not in branches
            or git(path, "rev-parse", "HEAD") != head or branch_tip(path, "main") != head):
        raise RuntimeError("接管仓库分支或 HEAD 已漂移")
    if git(path, "diff", "--cached", "--ita-visible-in-index", "--name-only", "-z"):
        raise RuntimeError("接管不允许 staged 内容")
    # 名称集合先比较，避免读取任何未授权文件（包括 ignored 配置）。
    changes = record["changes"]
    expected = {row["path"] for row in changes}
    if len(expected) != len(changes):
        raise RuntimeError("接管路径重复")
    for relative in expected:
        parts = Path(relative).parts
        if (not parts or Path(relative).is_absolute() or Path(relative).as_posix() != relative
                or any(part in {".", "..", ".git"} for part in parts)
                or any(char in relative for char in "*?[]\\\x00\n\r")):
            raise RuntimeError("接管路径必须是明确的仓库相对文件路径")
        target = path / relative
        if any(item.is_symlink() for item in (target, *target.parents) if item != path.parent):
            raise RuntimeError("接管路径不能经过符号链接")
    if changed_paths(path, head) != expected:
        raise RuntimeError("接管变更集合与授权不一致")
    flags = git(path, "ls-files", "-v", "-z") or ""
    if any(row and (row[0].islower() or row[0] == "S") for row in flags.split("\0")):
        raise RuntimeError("接管不允许 assume-unchanged 或 skip-worktree 隐藏变更")
    for row in changes:
        relative = row["path"]
        target = path / relative
        entry = git(path, "--literal-pathspecs", "ls-tree", "-z", head, "--", relative) or ""
        base = None
        base_mode = None
        if entry:
            metadata, found = entry.rstrip("\0").split("\t", 1)
            base_mode, kind, oid = metadata.split()
            if found != relative or kind != "blob" or base_mode not in {"100644", "100755"}:
                raise RuntimeError("接管基线不是普通文件")
            data = subprocess.check_output(
                ["git", "-C", str(path), "cat-file", "blob", oid], timeout=120,
                env={key: value for key, value in os.environ.items()
                     if not key.startswith("GIT_") and key.upper() != "PCM_GITLAB_TOKEN"},
            )
            base = hashlib.sha256(data).hexdigest()
        if (row["base_sha256"], row["base_mode"]) != (base, base_mode):
            raise RuntimeError("接管文件基线指纹不一致")
        if target.exists():
            mode = target.lstat().st_mode
            if not stat.S_ISREG(mode) or stat.S_IMODE(mode) not in {0o644, 0o755}:
                raise RuntimeError("接管文件类型或模式不合法")
            current = hashlib.sha256(target.read_bytes()).hexdigest()
            current_mode = "100755" if mode & stat.S_IXUSR else "100644"
            change = "M" if entry else "A"
        else:
            current = current_mode = None
            change = "D" if entry else None
        if (row["change"], row["sha256"], row["mode"]) != (change, current, current_mode):
            raise RuntimeError("接管文件变更类型、SHA256 或模式不一致")
    return head


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
