from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from stat import S_IMODE, S_ISDIR, S_ISREG
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


def git_path_is_ignored(root: Path, relative: str) -> bool:
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.excludesFile=/dev/null",
                "check-ignore",
                "--quiet",
                "--no-index",
                "--",
                relative,
            ],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    message = (result.stderr or result.stdout).strip()
    raise RuntimeError(f"Git 忽略规则核验失败：{message}")


def workspace_env_is_ignored(root: Path) -> bool:
    return git_path_is_ignored(root, ".env")


def initial_resources_are_ignored(root: Path) -> bool:
    return git_path_is_ignored(root, "initial-resources/")


def validate_initial_resources(path: Path) -> Path:
    source = path.absolute()
    try:
        source_stat = source.lstat()
    except OSError as error:
        raise ValueError(f"初始资料不存在或不可读取：{source}") from error
    if source.is_symlink() or not (
        S_ISREG(source_stat.st_mode) or S_ISDIR(source_stat.st_mode)
    ):
        raise ValueError(f"初始资料必须是非符号链接的普通文件或目录：{source}")
    if source.name in {"", ".", ".."}:
        raise ValueError(f"初始资料路径缺少可用名称：{source}")
    if S_ISDIR(source_stat.st_mode):
        for current_root, directories, files in os.walk(source, followlinks=False):
            for name in [*directories, *files]:
                current = Path(current_root) / name
                current_stat = current.lstat()
                if current.is_symlink() or not (
                    S_ISREG(current_stat.st_mode) or S_ISDIR(current_stat.st_mode)
                ):
                    raise ValueError(f"初始资料包含符号链接或特殊文件：{current}")
    return source.resolve()


def reject_nested_workspace(source: Path, *targets: Path) -> None:
    if not source.is_dir():
        return
    for target in targets:
        try:
            target.resolve().relative_to(source.resolve())
        except ValueError:
            continue
        raise RuntimeError("初始资料目录不能递归包含目标项目或临时工作区")


def _verify_resource_copy(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return False
    if path.is_symlink() or not (
        S_ISREG(path_stat.st_mode) or S_ISDIR(path_stat.st_mode)
    ):
        return False
    if S_ISDIR(path_stat.st_mode):
        try:
            return all(_verify_resource_copy(child) for child in path.iterdir())
        except OSError:
            return False
    return True


def copy_initial_resources(staging: Path, source: Path) -> str:
    relative = Path("initial-resources") / source.name
    container = staging / relative.parent
    if os.path.lexists(container):
        raise RuntimeError("临时工作区已存在 initial-resources，拒绝覆盖未知目录或半复制现场")
    container.mkdir()
    destination = staging / relative
    try:
        if source.is_dir():
            shutil.copytree(source, destination, symlinks=False)
        else:
            shutil.copy2(source, destination)
    except Exception as error:
        raise RuntimeError("复制初始资料失败，已保留半复制现场") from error
    if not _verify_resource_copy(destination):
        raise RuntimeError("初始资料副本核验失败，已保留现场")
    return relative.as_posix()


def verify_workspace_env(root: Path, expected_bytes: bytes) -> bool:
    path = root / ".env"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return False
    try:
        file_stat = os.fstat(descriptor)
        if not S_ISREG(file_stat.st_mode) or S_IMODE(file_stat.st_mode) != 0o600:
            return False
        with os.fdopen(descriptor, "rb") as file:
            descriptor = -1
            return file.read() == expected_bytes
    except OSError:
        return False
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def verify_clone(staging: Path, template: dict[str, str]) -> bool:
    return (
        (staging / ".git").is_dir()
        and not os.path.lexists(staging / ".env")
        and verify_required_paths(staging)
        and git("remote", "get-url", "origin", cwd=staging) == template["remote_url"]
        and git("branch", "--show-current", cwd=staging) == template["actual_branch"]
        and git("rev-parse", "HEAD", cwd=staging) == template["commit_sha"]
        and workspace_env_is_ignored(staging)
    )


def verify_published_content(
    root: Path,
    source_hash: str,
    workspace_env_bytes: bytes,
    initial_resources_path: str | None = None,
) -> bool:
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
        and verify_workspace_env(root, workspace_env_bytes)
        and (
            initial_resources_path is None
            or _verify_resource_copy(root / initial_resources_path)
        )
    )


def verify_prepared(
    root: Path,
    source_hash: str,
    workspace_env_bytes: bytes,
    initial_resources_path: str | None = None,
) -> bool:
    return (
        verify_published_content(
            root, source_hash, workspace_env_bytes, initial_resources_path
        )
        and not (root / ".git").exists()
    )


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
    if os.path.lexists(staging / ".env"):
        raise RuntimeError("固定模板不得包含 .env")
    if not workspace_env_is_ignored(staging):
        raise RuntimeError("固定模板根 Git 必须忽略 .env")
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


def prepare_staging(
    staging: Path,
    draft_bytes: bytes,
    source_hash: str,
    workspace_env_bytes: bytes,
    initial_resources: Path | None = None,
) -> Path:
    require_real_directory(staging, "临时工作区")
    git_dir = staging / ".git"
    docs_dir = staging / "docs"
    workspace_env = staging / ".env"
    if not git_dir.is_dir() or not verify_required_paths(staging):
        raise RuntimeError("临时目录不是完整、可核验的模板 clone")
    if os.path.lexists(workspace_env):
        raise RuntimeError("固定模板不得包含 .env")
    if not workspace_env_bytes:
        raise RuntimeError("AI Agent 工作区环境配置不能为空")
    shutil.rmtree(git_dir)
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    docs_dir.mkdir()
    published_draft = docs_dir / "产品初稿.md"
    published_draft.write_bytes(draft_bytes)
    descriptor = os.open(
        workspace_env,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as file:
        os.fchmod(file.fileno(), 0o600)
        file.write(workspace_env_bytes)
    initial_resources_path = (
        copy_initial_resources(staging, initial_resources)
        if initial_resources is not None
        else None
    )
    if (
        git_dir.exists()
        or sorted(path.name for path in docs_dir.iterdir()) != ["产品初稿.md"]
        or sha256(published_draft) != source_hash
        or not verify_required_paths(staging)
        or not verify_workspace_env(staging, workspace_env_bytes)
        or (
            initial_resources_path is not None
            and not _verify_resource_copy(staging / initial_resources_path)
        )
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
