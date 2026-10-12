#!/usr/bin/env python3
"""只推送显式仓库的已有提交；仅依赖 Python 标准库与 Git。"""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import signal
import subprocess
from urllib.parse import urlsplit


LOCAL_TIMEOUT = 15
NETWORK_TIMEOUT = 60
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class PushError(RuntimeError):
    def __init__(self, message, results, blocked=False):
        super().__init__(message)
        self.results = copy.deepcopy(results)
        self.blocked = blocked


class _Failure(RuntimeError):
    def __init__(self, message, blocked=False):
        super().__init__(message)
        self.blocked = blocked


def _environment():
    # 路径重定向、调用方注入的 Git 配置和工具凭据不传给 Git 或 hook。
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("GIT_", "PCM_", "LLM_"))
           and key.upper() != "PCM_GITLAB_TOKEN"
           and key not in {"SSH_ASKPASS", "SSH_ASKPASS_REQUIRE"}}
    env.update({
        "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never",
        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0",
        "GIT_SSH_VARIANT": "ssh",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "
                           "-o ConnectTimeout=15 -o ConnectionAttempts=1",
        "SSH_ASKPASS_REQUIRE": "never",
    })
    return env


def _command_error(stderr, *, ssh=False):
    # Git/hook 的原始输出可能含 URL 凭据或环境秘密，绝不原样转发。
    text = stderr.lower()
    if "host key verification failed" in text or "remote host identification has changed" in text:
        return _Failure("SSH 主机身份未获信任或已变化；请核实并修复主机信任后重试")
    if ssh and any(marker in text for marker in (
        "permission denied (publickey", "no supported authentication methods",
        "you are not allowed to push", "write access to repository not granted",
        "you don't have permission to push", "you do not have permission to push",
    )):
        return _Failure("SSH 身份或仓库写权限不可用；请配置有权访问目标分支的 SSH 身份后重试", True)
    if "non-fast-forward" in text or "fetch first" in text:
        return _Failure("远程已领先或分叉，普通推送被拒绝；保留现场，不自动拉取或合并")
    if "pre-receive hook declined" in text or "remote rejected" in text:
        return _Failure("服务端拒绝推送；请检查目标分支保护、权限或服务端 hook")
    if "could not resolve" in text or "connection refused" in text or "network is unreachable" in text:
        return _Failure("无法连接目标远程；请检查网络与远程服务后重试")
    return _Failure("Git 命令失败；请在目标仓库检查本地配置、hook 与远程可用性（原始输出未转发）")


def _git(path, *args, network=False, ssh=False, allowed=(0,)):
    command = ["git", "-C", str(path), "-c", "credential.interactive=false",
               "-c", "protocol.allow=never", "-c", "protocol.file.allow=always",
               "-c", "protocol.ssh.allow=always", "-c", "protocol.https.allow=always",
               "-c", "protocol.http.allow=always", *args]
    try:
        process = subprocess.Popen(command, env=_environment(), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace",
                                   start_new_session=True)
    except (OSError, ValueError):
        raise _Failure("无法启动 Git；请检查 Git 安装及仓库路径") from None
    try:
        stdout, stderr = process.communicate(timeout=NETWORK_TIMEOUT if network else LOCAL_TIMEOUT)
    except subprocess.TimeoutExpired:
        # 一并停止本次 Git 启动的 SSH/hook，避免主进程超时后继续推送。
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise _Failure("Git 操作超时；远程结果可能尚未确认，重试将先读取远程事实") from None
    if process.returncode not in allowed:
        raise _command_error(stderr, ssh=ssh)
    return stdout.rstrip("\r\n"), process.returncode


def _validate_url(url):
    if not url or url.startswith("-") or any(ord(char) < 32 for char in url):
        raise _Failure("远程地址无效")
    if "?" in url or "#" in url:
        raise _Failure("远程地址不允许携带查询参数或片段")
    # 不接受内嵌认证、查询参数、片段及已知令牌形式，也不把它们写入结果。
    secrets = [value for key, value in os.environ.items()
               if key.startswith(("PCM_", "LLM_"))
               and any(word in key.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "KEY"))
               and len(value) >= 8]
    if any(value in url for value in secrets) or re.search(r"(?:glpat-|gh[pousr]_|github_pat_)", url):
        raise _Failure("远程地址包含凭据；请移除 URL 中的秘密后重试")
    if "://" in url:
        try:
            parsed = urlsplit(url)
            unsafe = (parsed.scheme not in {"ssh", "https", "http", "file"}
                      or parsed.password is not None or parsed.query or parsed.fragment
                      or (parsed.scheme != "ssh" and parsed.username is not None)
                      or (parsed.scheme != "file" and not parsed.hostname))
        except ValueError:
            unsafe = True
        if unsafe:
            raise _Failure("远程地址包含认证信息、参数或不支持的协议；请使用无秘密的 SSH、HTTPS 或文件地址")
    elif "::" in url:
        raise _Failure("不支持自定义 Git remote helper 地址")
    elif not (url.startswith(("/", "./", "../")) or re.fullmatch(r"(?:[\w.-]+@)?[\w.-]+:.+", url)):
        raise _Failure("请使用明确的 SSH、HTTPS 或文件远程地址")


def _push_url(path, remote, expected_url=None):
    urls, code = _git(path, "remote", "get-url", "--push", "--all", remote, allowed=(0, 1, 2, 128))
    if code:
        raise _Failure("无法读取指定 remote 的 push 地址；请确认该 remote 已正确配置")
    urls = urls.splitlines()
    if len(urls) != 1:
        raise _Failure("远程必须恰有一个实际 push 地址，不允许多目标推送")
    url = urls[0]
    _validate_url(url)
    if expected_url is not None and url != expected_url:
        raise _Failure("实际 push 地址与 expected_url 不一致；保留原绑定")
    mirror, _ = _git(path, "config", "--bool", "--get-all", f"remote.{remote}.mirror", allowed=(0, 1))
    if "true" in mirror.splitlines():
        raise _Failure("拒绝启用了 mirror 的远程配置")
    # ls-remote 必须查询实际 push 目标；多层 rewrite 不得把核验导向另一个地址。
    resolved, _ = _git(path, "ls-remote", "--get-url", "--", url)
    if resolved != url:
        raise _Failure("远程地址存在多层 URL rewrite，无法唯一核验 push 目标")
    return url


def _local_target(path, branch, target_sha=None):
    top, code = _git(path, "rev-parse", "--show-toplevel", allowed=(0, 128))
    if code:
        raise _Failure("指定路径不是有效的非裸 Git 工作仓库")
    if Path(top).resolve() != path:
        raise _Failure("指定路径不是独立仓库自身的 Git top-level")
    # 旧版 Git 不一定支持 GIT_NO_LAZY_FETCH；保守拒绝 partial clone，避免对象检查隐式联网。
    promisor, _ = _git(path, "config", "--get-regexp", r"remote\..*\.promisor|extensions\.partialclone", allowed=(0, 1))
    if promisor:
        raise _Failure("partial clone 配置可能隐式下载对象；请使用已有完整对象的仓库推送")
    current, _ = _git(path, "symbolic-ref", "--quiet", "HEAD", allowed=(0, 1))
    if current != f"refs/heads/{branch}":
        raise _Failure("当前分支与目标分支不一致，或 HEAD 处于游离状态")
    for operation in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge",
                      "rebase-apply", "sequencer", "BISECT_START"):
        location, _ = _git(path, "rev-parse", "--git-path", operation)
        if (path / location).exists():
            raise _Failure("仓库存在进行中的 merge、rebase、cherry-pick、revert 或 bisect；请先处理现场")
    dirty, _ = _git(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")
    if dirty:
        raise _Failure("仓库尚有未提交内容（工作树、index、未跟踪项或子模块），停止推送")
    sha, code = _git(path, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", allowed=(0, 128))
    if code or not SHA.fullmatch(sha):
        raise _Failure("目标分支没有有效提交（HEAD 不存在）")
    if target_sha is not None and sha != target_sha:
        raise _Failure("本地目标提交已漂移，与 target_sha 不一致")
    return sha


def _remote_sha(path, url, branch):
    output, _ = _git(path, "ls-remote", "--refs", "--", url, f"refs/heads/{branch}",
                     network=True, ssh=_is_ssh(url))
    if not output:
        return ""
    fields = output.split()
    if len(fields) != 2 or not SHA.fullmatch(fields[0]) or fields[1] != f"refs/heads/{branch}":
        raise _Failure("远程分支查询返回了非预期结果")
    return fields[0]


def _is_ssh(url):
    return url.startswith("ssh://") or ("://" not in url and not url.startswith(("/", "./", "../")) and ":" in url)


def _check_ancestor(path, remote_sha, target_sha):
    if not remote_sha or remote_sha == target_sha:
        return
    _, code = _git(path, "cat-file", "-e", f"{remote_sha}^{{commit}}", allowed=(0, 1, 128))
    if code:
        raise _Failure("远程提交对象不在本地，无法证明快进；停止推送，不隐式 fetch 或合并")
    _, code = _git(path, "merge-base", "--is-ancestor", remote_sha, target_sha, allowed=(0, 1))
    if code:
        raise _Failure("远程已领先或分叉，不能快进到目标提交")


def push_repositories(repositories: list[dict], *, branch='main', remote='origin', on_update=None) -> list[dict]:
    """先整批预检，再按输入顺序推送；回调接收可持久化的逐仓结果副本。"""
    results = []
    if not isinstance(repositories, list) or not repositories:
        raise PushError("必须提供非空仓库列表", results)
    for item in repositories:
        repo = item if isinstance(item, dict) else {}
        target = repo.get("target_sha")
        results.append(dict(name=repo.get("name", ""), path=repo.get("path", ""), url="", branch=branch,
                            target_sha=target if isinstance(target, str) and SHA.fullmatch(target) else "",
                            remote_sha="", status="pending"))

    def notify():
        if on_update is not None:
            try:
                on_update(copy.deepcopy(results))
            except Exception:
                raise PushError("保存逐仓推送结果失败，已停止后续操作", results) from None

    def fail(index, exc):
        results[index].update(status="failed", error=str(exc))
        notify()
        raise PushError(str(exc), results, exc.blocked) from None

    seen = set()
    for index, repo in enumerate(repositories):
        try:
            if not isinstance(repo, dict) or not isinstance(repo.get("path"), str) or not repo["path"] or not isinstance(repo.get("name"), str) or not repo["name"]:
                raise _Failure("每个仓库必须提供非空字符串 name 和 path")
            if not isinstance(branch, str) or not branch or branch.startswith("-"):
                raise _Failure("目标分支无效")
            if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", remote):
                raise _Failure("remote 名称无效")
            try:
                path = Path(repo["path"]).expanduser().resolve()
            except (OSError, ValueError, RuntimeError):
                raise _Failure("无法解析仓库路径") from None
            _, code = _git(path, "check-ref-format", f"refs/heads/{branch}", allowed=(0, 1))
            if code:
                raise _Failure("目标分支名称不是有效 Git 引用")
            if path in seen:
                raise _Failure("仓库清单包含重复路径")
            seen.add(path)
            target = repo.get("target_sha")
            if target is not None and (not isinstance(target, str) or not SHA.fullmatch(target)):
                raise _Failure("target_sha 必须是完整提交 SHA")
            sha = _local_target(path, branch, target)
            url = _push_url(path, remote, repo.get("expected_url"))
            results[index].update(path=str(path), url=url, target_sha=sha)
            notify()
        except _Failure as exc:
            fail(index, exc)

    # 所有仓库的本地边界和远程历史都通过，才允许首次写入。
    for index, result in enumerate(results):
        try:
            result["remote_sha"] = _remote_sha(result["path"], result["url"], branch)
            _check_ancestor(result["path"], result["remote_sha"], result["target_sha"])
            notify()
        except _Failure as exc:
            fail(index, exc)

    for index, result in enumerate(results):
        try:
            path = Path(result["path"])
            _local_target(path, branch, result["target_sha"])
            _push_url(path, remote, result["url"])
            before = _remote_sha(path, result["url"], branch)
            result["remote_sha"] = before
            _check_ancestor(path, before, result["target_sha"])
            if before != result["target_sha"]:
                _git(path, "-c", "push.followTags=false", "-c", "push.autoSetupRemote=false",
                     "push", "--porcelain", "--no-follow-tags", "--recurse-submodules=no",
                     "--", remote, f"{result['target_sha']}:refs/heads/{branch}",
                     network=True, ssh=_is_ssh(result["url"]))
            result["remote_sha"] = _remote_sha(path, result["url"], branch)
            if result["remote_sha"] != result["target_sha"]:
                raise _Failure("推送后远程分支 SHA 与目标不一致；请保留现场并重试核验")
            _local_target(path, branch, result["target_sha"])
            _push_url(path, remote, result["url"])
            result["status"] = "unchanged" if before == result["target_sha"] else "pushed"
            notify()
        except _Failure as exc:
            fail(index, exc)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="按明确顺序安全推送已有提交，不准备或改写仓库")
    parser.add_argument("--repo", action="append", required=True, help="仓库自身的路径，可重复；按输入顺序推送")
    parser.add_argument("--branch", default="main", help="目标分支，默认 main；功能分支须明确指定")
    parser.add_argument("--remote", default="origin", help="远程名称，默认 origin")
    args = parser.parse_args(argv)
    try:
        results = push_repositories([dict(name=Path(path).name, path=path) for path in args.repo],
                                    branch=args.branch, remote=args.remote)
    except PushError as exc:
        print(json.dumps(dict(results=exc.results, error=str(exc), blocked=exc.blocked), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(dict(results=results), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
