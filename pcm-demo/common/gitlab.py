from __future__ import annotations

import json
import re
import subprocess
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from common.error_diagnostics import redact_text
from common.git_environment import git_environment
from common.state import write_state
from config import load_settings

PARENT_PATH = "baiyiyu/andrszan/pcm-projects"
API_URL = "https://gitlab.com/api/v4"
API_TIMEOUT = 30


class RemoteBlocked(RuntimeError):
    """缺少当前环境无法自行取得的 GitLab 或 SSH 授权。"""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 固定服务不跟随重定向，避免 PRIVATE-TOKEN 被转发到其它地址。
        return None


class _Client:
    def __init__(self) -> None:
        secret = load_settings().pcm_gitlab_token
        self.token = secret.get_secret_value().strip() if secret is not None else ""
        if not self.token:
            raise RemoteBlocked("缺少 PCM_GITLAB_TOKEN；请提供固定父 group 下的 GitLab API 授权后恢复")
        self.opener = build_opener(_NoRedirect())

    def request(self, method: str, path: str, data: dict | None = None, *, missing_ok: bool = False) -> dict | None:
        request = Request(
            f"{API_URL}/{path}",
            data=json.dumps(data).encode("utf-8") if data is not None else None,
            headers={"PRIVATE-TOKEN": self.token, "Content-Type": "application/json"},
            method=method,
        )
        failure: RuntimeError | None = None
        try:
            with self.opener.open(request, timeout=API_TIMEOUT) as response:
                value = json.load(response)
            if not isinstance(value, dict):
                raise ValueError("GitLab API 响应不是对象")
            return value
        except HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            try:
                detail = redact_text(error.read(4096).decode("utf-8", errors="replace"), known_secrets=[self.token])
            except (OSError, HTTPException, ValueError):
                detail = "响应正文不可读取"
            message = f"GitLab API {method} {path} 返回 HTTP {error.code}：{detail}"
            if error.code in {401, 403}:
                failure = RemoteBlocked(message + "；请补齐 PCM_GITLAB_TOKEN 的认证或目标权限后恢复")
            else:
                failure = RuntimeError(message)
        except (OSError, URLError, HTTPException, ValueError) as error:
            detail = redact_text(str(error), known_secrets=[self.token])
            failure = RuntimeError(f"GitLab API {method} {path} 请求失败：{detail}")
        # 不把原异常链（可能携带令牌）交给通用诊断采集器。
        raise failure


def _id(value: object) -> bool:
    return type(value) is int and value > 0


def _parent(client: _Client) -> dict:
    parent = client.request("GET", f"groups/{quote(PARENT_PATH, safe='')}", missing_ok=True)
    if parent is None:
        raise RemoteBlocked(f"无法读取 GitLab 父 group {PARENT_PATH}；请确认 PCM_GITLAB_TOKEN 的访问权限")
    if not _id(parent.get("id")) or parent.get("full_path") != PARENT_PATH:
        raise RuntimeError("GitLab 父 group 的 ID 或完整路径不符合约定")
    return {"id": parent["id"], "full_path": PARENT_PATH}


def preflight() -> dict:
    """仅核验配置、当前身份和固定父 group 可读性，不证明创建或 SSH 写权限。"""
    client = _Client()
    user = client.request("GET", "user")
    if not _id(user.get("id")) or user.get("state") not in {None, "active"}:
        raise RemoteBlocked("PCM_GITLAB_TOKEN 未对应可用 GitLab 用户；请补齐有效认证")
    return _parent(client)


def _contract(state: dict) -> tuple[dict, str, list[dict]]:
    remote = state.get("remote_sync")
    if not isinstance(remote, dict) or remote.get("enabled") is not True:
        raise RuntimeError("remote_sync 启用事实无效")
    name = remote.get("project_name")
    if not isinstance(name, str) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None:
        raise RuntimeError("remote_sync 稳定项目名无效")
    names, repositories = state.get("applicable_repositories"), state.get("repositories")
    if (
        not isinstance(names, list) or not names or names[0] != "root"
        or any(not isinstance(item, str) or item not in {"root", "frontend", "backend"} for item in names)
        or len(set(names)) != len(names)
        or not isinstance(repositories, list)
        or any(not isinstance(item, dict) for item in repositories)
        or [item.get("name") for item in repositories] != names
    ):
        raise RuntimeError("远程初始化的权威仓库清单无效")
    for repository in repositories:
        path = repository.get("path")
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise RuntimeError("远程初始化的仓库路径必须为绝对路径")
    records = remote.get("repositories", {})
    if not isinstance(records, dict) or set(records) - set(names):
        raise RuntimeError("remote_sync 仓库归属记录无效")
    subgroup_path = f"{PARENT_PATH}/{name}"
    if "parent_group" in remote:
        parent = remote["parent_group"]
        if not isinstance(parent, dict) or not _id(parent.get("id")) or parent.get("full_path") != PARENT_PATH:
            raise RuntimeError("remote_sync 父 group 归属记录无效")
    if "subgroup" in remote:
        group = remote["subgroup"]
        if (
            "parent_group" not in remote or not isinstance(group, dict)
            or not _id(group.get("id")) or group.get("full_path") != subgroup_path
            or group.get("parent_id") != remote["parent_group"]["id"]
        ):
            raise RuntimeError("remote_sync subgroup 归属记录无效")
    for key, record in records.items():
        project_path = f"{subgroup_path}/{name}" + (f"-{key}" if key != "root" else "")
        if (
            not isinstance(record, dict) or "subgroup" not in remote
            or not _id(record.get("project_id")) or record.get("path_with_namespace") != project_path
            or record.get("namespace_id") != remote["subgroup"]["id"]
            or record.get("url") != f"git@gitlab.com:{project_path}.git"
        ):
            raise RuntimeError(f"remote_sync {key} 项目归属记录无效")
    return remote, name, repositories


def _git(path: Path, *args: str, absent_ok: bool = False) -> str:
    env = {key: value for key, value in git_environment().items() if key != "PCM_GITLAB_TOKEN"}
    failure = None
    try:
        completed = subprocess.run(["git", *args], cwd=path, env=env, text=True, capture_output=True, timeout=120)
        if absent_ok and completed.returncode == 1:
            return ""
        if completed.returncode != 0:
            failure = RuntimeError(f"远程初始化 Git 操作失败：{path.name} ({args[0]})")
        else:
            return completed.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        failure = RuntimeError(f"远程初始化 Git 操作失败或超时：{path.name} ({args[0]})")
    raise failure


def _check_origin(repository: dict, record: dict | None) -> None:
    path = Path(repository["path"])
    settings = _git(path, "config", "--get-regexp", r"^remote\.origin\.", absent_ok=True)
    if not settings:
        return
    if record is None:
        raise RuntimeError(f"{repository['name']} 已有未知 origin，拒绝覆盖或接管")
    expected = [record["url"]]
    if (
        _git(path, "remote", "get-url", "--all", "origin").splitlines() != expected
        or _git(path, "remote", "get-url", "--push", "--all", "origin").splitlines() != expected
        or _git(path, "config", "--get-all", "remote.origin.mirror", absent_ok=True) not in {"", "false"}
    ):
        raise RuntimeError(f"{repository['name']} origin 与已登记绑定冲突，拒绝覆盖")


def _verify_group(value: dict, path: str, parent_id: int, expected_id: int | None = None) -> None:
    if (
        not _id(value.get("id")) or (expected_id is not None and value.get("id") != expected_id)
        or value.get("full_path") != path or value.get("parent_id") != parent_id
        or value.get("visibility") != "private"
    ):
        raise RuntimeError("GitLab subgroup 的 ID、路径、父级或 private 属性不符合约定")


def _verify_project(value: dict, record: dict, subgroup_path: str) -> None:
    namespace = value.get("namespace")
    if (
        value.get("id") != record["project_id"] or not _id(value.get("id"))
        or value.get("path_with_namespace") != record["path_with_namespace"]
        or value.get("ssh_url_to_repo") != record["url"] or value.get("visibility") != "private"
        or not isinstance(namespace, dict) or namespace.get("id") != record["namespace_id"]
        or namespace.get("full_path") != subgroup_path
    ):
        raise RuntimeError("GitLab project 的 ID、路径、namespace、SSH 地址或 private 属性不符合约定")


def prepare_repositories(run_dir: Path, state: dict[str, Any]) -> None:
    """创建并及时登记 private 对象，只绑定本次已确认归属的 origin；不执行 push。"""
    remote, name, repositories = _contract(state)
    records = remote.setdefault("repositories", {})
    # 整批检查在任何远程写操作前完成，不能创建对象后才发现本地绑定冲突。
    for repository in repositories:
        path = Path(repository["path"])
        if path.is_symlink() or Path(_git(path, "rev-parse", "--show-toplevel")).resolve() != path.resolve():
            raise RuntimeError("远程初始化仓库不是独立 Git 顶层目录")
        if _git(path, "branch", "--show-current") != "main" or _git(path, "status", "--porcelain"):
            raise RuntimeError("远程初始化要求所有仓库均为 clean main")
        _git(path, "rev-parse", "--verify", "HEAD")
        _check_origin(repository, records.get(repository["name"]))
    client = _Client()
    parent = _parent(client)
    if "parent_group" in remote and remote["parent_group"] != parent:
        raise RuntimeError("GitLab 父 group 与已登记归属不一致")
    remote["parent_group"] = parent
    write_state(run_dir, state)
    subgroup_path = f"{PARENT_PATH}/{name}"
    group = remote.get("subgroup")
    if group is None:
        if client.request("GET", f"groups/{quote(subgroup_path, safe='')}", missing_ok=True) is not None:
            raise RuntimeError("GitLab 同名 subgroup 创建结果／归属未确认，拒绝接管；请核实原创建结果后恢复")
        value = client.request("POST", "groups", {"name": name, "path": name, "parent_id": parent["id"], "visibility": "private"})
        _verify_group(value, subgroup_path, parent["id"])
        group = {"id": value["id"], "full_path": subgroup_path, "parent_id": parent["id"]}
        remote["subgroup"] = group
        write_state(run_dir, state)
    else:
        value = client.request("GET", f"groups/{group['id']}")
        _verify_group(value, subgroup_path, parent["id"], group["id"])
    for repository in repositories:
        key = repository["name"]
        project_name = name if key == "root" else f"{name}-{key}"
        project_path = f"{subgroup_path}/{project_name}"
        record = records.get(key)
        if record is None:
            if client.request("GET", f"projects/{quote(project_path, safe='')}", missing_ok=True) is not None:
                raise RuntimeError(f"GitLab {key} 同名 project 创建结果／归属未确认，拒绝接管；请核实原创建结果后恢复")
            value = client.request("POST", "projects", {
                "name": project_name, "path": project_name, "namespace_id": group["id"],
                "visibility": "private", "initialize_with_readme": False,
            })
            record = {"project_id": value.get("id"), "path_with_namespace": project_path,
                      "namespace_id": group["id"], "url": f"git@gitlab.com:{project_path}.git"}
            _verify_project(value, record, subgroup_path)
            if value.get("empty_repo") is not True or value.get("default_branch") is not None:
                raise RuntimeError("GitLab 新建项目不是空仓库，拒绝绑定")
            records[key] = record
            write_state(run_dir, state)
        else:
            value = client.request("GET", f"projects/{record['project_id']}")
            _verify_project(value, record, subgroup_path)
        _check_origin(repository, record)
        path = Path(repository["path"])
        if not _git(path, "config", "--get-regexp", r"^remote\.origin\.", absent_ok=True):
            _git(path, "remote", "add", "origin", record["url"])
        _check_origin(repository, record)


def finalize_repositories(state: dict[str, Any], *, verified_versions: dict[str, str]) -> None:
    """首推成功后核验 private/default branch，并以已核验远程 SHA 设置 upstream。"""
    remote, name, repositories = _contract(state)
    records = remote.get("repositories", {})
    if set(records) != {item["name"] for item in repositories}:
        raise RuntimeError("GitLab 首推核验缺少项目归属记录")
    if (
        not isinstance(verified_versions, dict) or set(verified_versions) != set(records)
        or any(not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha) is None
               for sha in verified_versions.values())
    ):
        raise RuntimeError("GitLab 首推核验缺少完整的已验证远程 SHA")
    client = _Client()
    for repository in repositories:
        record = records[repository["name"]]
        path = f"projects/{record['project_id']}"
        value = client.request("GET", path)
        _verify_project(value, record, f"{PARENT_PATH}/{name}")
        if value.get("default_branch") != "main":
            client.request("PUT", path, {"default_branch": "main"})
            value = client.request("GET", path)
            _verify_project(value, record, f"{PARENT_PATH}/{name}")
            if value.get("default_branch") != "main":
                raise RuntimeError("GitLab 默认分支未设为 main")
        _check_origin(repository, record)
        local = Path(repository["path"])
        sha = verified_versions[repository["name"]]
        if _git(local, "rev-parse", "refs/heads/main") != sha:
            raise RuntimeError("设置 upstream 前本地 main 已偏离首推目标")
        # 响应丢失后远程可能已一致，但 Git 尚未写入本地 tracking ref。
        _git(local, "update-ref", "--no-deref", "refs/remotes/origin/main", sha)
        _git(local, "config", "--local", "branch.main.remote", "origin")
        _git(local, "config", "--local", "branch.main.merge", "refs/heads/main")
        if _git(local, "rev-parse", "main@{upstream}") != sha:
            raise RuntimeError("main upstream 与已核验的远程目标不一致")
