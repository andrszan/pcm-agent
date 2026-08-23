from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from common.files import sha256

REQUIRED_PATHS = (
    Path("CLAUDE.md"),
    Path("AGENTS.md"),
    Path(".claude/skills/project-intake/SKILL.md"),
    Path("frontend"),
    Path("backend"),
)


class WorkspaceBlocked(RuntimeError):
    pass


def git(
    *args: str, cwd: Path | None = None, remote_auth: bool = False
) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if result.returncode:
        message = (result.stderr or result.stdout).strip()
        if remote_auth and any(
            text in message.lower() for text in ("permission denied", "publickey", "access denied")
        ):
            raise WorkspaceBlocked("缺少固定模板仓库的 SSH 凭据或读取权限")
        raise RuntimeError(f"Git 命令失败：{message}")
    return result.stdout.strip()


def parse_default_branch(ls_remote_output: str) -> str:
    prefix = "ref: refs/heads/"
    for line in ls_remote_output.splitlines():
        if line.startswith(prefix) and line.endswith("\tHEAD"):
            return line[len(prefix) : -len("\tHEAD")]
    raise RuntimeError("无法确定模板默认分支")


def verify_required_paths(root: Path) -> bool:
    return all((root / path).exists() for path in REQUIRED_PATHS)


def verify_clone(staging: Path, template: dict[str, str]) -> bool:
    return (
        (staging / ".git").is_dir()
        and verify_required_paths(staging)
        and git("remote", "get-url", "origin", cwd=staging) == template["remote_url"]
        and git("branch", "--show-current", cwd=staging) == template["actual_branch"]
        and git("rev-parse", "HEAD", cwd=staging) == template["commit_sha"]
    )


def verify_published_content(root: Path, source_hash: str) -> bool:
    if root.is_symlink():
        return False
    docs_dir = root / "docs"
    published_draft = docs_dir / "产品初稿.md"
    return (
        root.is_dir()
        and docs_dir.is_dir()
        and sorted(path.name for path in docs_dir.iterdir()) == ["产品初稿.md"]
        and sha256(published_draft) == source_hash
        and verify_required_paths(root)
    )


def verify_prepared(root: Path, source_hash: str) -> bool:
    return verify_published_content(root, source_hash) and not (root / ".git").exists()


def inspect_repository(
    root: Path, *, expected_head: str, require_clean_index: bool = True
) -> dict[str, str | None]:
    if expected_head not in {"unborn", "present"}:
        raise ValueError("Git HEAD 状态必须是 unborn 或 present")
    require_real_directory(root, "Git 仓库目录")
    git_dir = root / ".git"
    if git_dir.is_symlink() or not git_dir.is_dir():
        raise RuntimeError("Git 仓库目录尚未初始化 Git 仓库")
    top_level = Path(git("rev-parse", "--show-toplevel", cwd=root)).resolve()
    branch = git("branch", "--show-current", cwd=root)
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    has_head = head.returncode == 0
    if top_level != root.resolve() or branch != "main" or has_head != (expected_head == "present"):
        expected = "尚无 commit" if expected_head == "unborn" else "已有 commit"
        raise RuntimeError(f"Git 仓库必须位于目标目录、分支为 main 且{expected}")
    if require_clean_index:
        index = (
            git("ls-files", "--stage", cwd=root)
            if expected_head == "unborn"
            else git("diff", "--cached", "--name-only", cwd=root)
        )
        if index:
            raise RuntimeError("Git 仓库不得暂存文件")
    return {"path": str(top_level), "branch": branch, "head": head.stdout.strip() or None}


def inspect_root_repository(root: Path) -> dict[str, str | None]:
    return inspect_repository(root, expected_head="unborn")


def initialize_repository(root: Path) -> dict[str, str | None]:
    require_real_directory(root, "Git 仓库目录")
    git_dir = root / ".git"
    if not git_dir.exists():
        git("init", "-b", "main", cwd=root)
    elif git_dir.is_symlink() or not git_dir.is_dir():
        raise RuntimeError("Git 仓库目录的 .git 不是目录")
    return inspect_repository(root, expected_head="unborn")


def initialize_root_repository(root: Path) -> dict[str, str | None]:
    return initialize_repository(root)


def result(status: str, summary: str, *, blocked: dict[str, Any] | None = None, error: dict[str, Any] | None = None, outputs: list[str] | None = None) -> dict[str, Any]:
    return {
        "step": 1,
        "name": "建立项目工作区",
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": outputs or [],
        "blocked": blocked,
        "error": error,
    }


def require_real_directory(path: Path, description: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"{description}不是可确认归属的真实目录：{path}")


def inspect_clone(staging: Path, template_repository: str) -> dict[str, str]:
    require_real_directory(staging, "临时 clone")
    if not (staging / ".git").is_dir() or not verify_required_paths(staging):
        raise RuntimeError("临时 clone 不完整，保留现场等待处理")
    default_branch = parse_default_branch(
        git("ls-remote", "--symref", template_repository, "HEAD", remote_auth=True)
    )
    remote_url = git("remote", "get-url", "origin", cwd=staging)
    actual_branch = git("branch", "--show-current", cwd=staging)
    commit_sha = git("rev-parse", "HEAD", cwd=staging)
    if remote_url != template_repository or actual_branch != default_branch:
        raise RuntimeError("临时 clone 的模板来源或分支与当前合同不一致")
    return {
        "repository": template_repository,
        "remote_url": remote_url,
        "default_branch": default_branch,
        "actual_branch": actual_branch,
        "commit_sha": commit_sha,
    }


def clone_and_verify(staging: Path, template_repository: str) -> dict[str, str]:
    default_branch = parse_default_branch(
        git("ls-remote", "--symref", template_repository, "HEAD", remote_auth=True)
    )
    git("clone", "--depth", "1", template_repository, str(staging))
    template = inspect_clone(staging, template_repository)
    if template["default_branch"] != default_branch:
        raise RuntimeError("clone 期间模板默认分支发生变化")
    return template


def prepare_staging(staging: Path, draft_bytes: bytes, source_hash: str) -> Path:
    require_real_directory(staging, "临时工作区")
    git_dir = staging / ".git"
    docs_dir = staging / "docs"
    if not git_dir.is_dir() or not verify_required_paths(staging):
        raise RuntimeError("临时目录不是完整、可核验的模板 clone")
    shutil.rmtree(git_dir)
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    docs_dir.mkdir()
    published_draft = docs_dir / "产品初稿.md"
    published_draft.write_bytes(draft_bytes)
    if (
        git_dir.exists()
        or sorted(path.name for path in docs_dir.iterdir()) != ["产品初稿.md"]
        or sha256(published_draft) != source_hash
        or not verify_required_paths(staging)
    ):
        raise RuntimeError("临时工作区初始化核验失败")
    return published_draft


def publish(staging: Path, final_path: Path) -> None:
    require_real_directory(staging, "临时工作区")
    if final_path.exists() or final_path.is_symlink():
        raise RuntimeError(f"最终项目路径已存在，拒绝覆盖：{final_path}")
    try:
        os.rename(staging, final_path)
    except OSError as error:
        raise RuntimeError(f"原子发布工作区失败：{error}") from error
