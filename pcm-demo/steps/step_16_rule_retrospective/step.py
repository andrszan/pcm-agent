from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.state import (
    is_valid_requirement_id,
    requirement_step_result_path,
    write_requirement_step_result,
    write_state,
)
from config import LLMConfig

STEP = 16
NAME = "规则复盘"
CURRENT_NODE = "requirement:16_rule_retrospective"
NEXT_NODE = "requirement:17_commit"
PHASE = "phase_1_requirement_development"
SKILL_NAME = "session-rule-retrospective"

RULE_RETROSPECTIVE_DECISION_RULES = """- completed：Agent 已明确完成规则复盘，允许有规则修改或 no-change，且没有剩余复盘工作。
- continue：当前环境仍可完成复盘时，给出明确的下一步指令。
- blocked：仅当缺少当前环境无法取得的不可替代外部资源时使用。"""

_HEX_SHA = set("0123456789abcdef")
_PSEUDO_REFS = (
    "ORIG_HEAD",
    "FETCH_HEAD",
    "MERGE_HEAD",
    "AUTO_MERGE",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "REBASE_HEAD",
    "BISECT_HEAD",
)


class RuleRetrospectiveBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        *,
        requirement_id: str,
        development_session_id: str,
    ) -> None:
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.requirement_id = requirement_id
        self.development_session_id = development_session_id


def result(
    status: str,
    summary: str,
    *,
    requirement_id: str | None = None,
    development_session_id: str | None = None,
    blocked: dict[str, Any] | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": [],
        "blocked": blocked,
        "error": error,
        "requirement_id": requirement_id,
        "development_session_id": development_session_id,
    }


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


def _is_hex_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and set(value) <= _HEX_SHA


def _read_json(path: Path, message: str) -> dict[str, Any]:
    if path.is_symlink():
        raise RuntimeError(message)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(message) from error
    if not isinstance(value, dict):
        raise RuntimeError(message)
    return value


def _workspace_from_state(state: dict[str, Any], *, require_exists: bool) -> Path:
    try:
        root_value = state["workspace"]["root"]
        workspace_value = state["workspace"]["final_path"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    if not isinstance(root_value, str) or not isinstance(workspace_value, str):
        raise RuntimeError("工作区状态记录不完整")
    root = Path(root_value)
    workspace = Path(workspace_value)
    if not root.is_absolute() or not workspace.is_absolute():
        raise RuntimeError("工作区状态路径不符合约定")
    if not require_exists:
        if workspace.parent != root:
            raise RuntimeError("产品工作区路径与状态根目录不一致")
        return workspace
    if workspace.is_symlink():
        raise RuntimeError("工作区状态路径不符合约定")
    root = root.resolve()
    workspace = workspace.resolve()
    if workspace.parent != root or not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    return workspace


def _session(state: dict[str, Any], key: str) -> str | None:
    sessions = state.get("claude_sessions")
    if sessions is None:
        return None
    if not isinstance(sessions, dict):
        raise RuntimeError("Claude session 状态不符合约定")
    value = sessions.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeError("Claude session ID 不符合约定")
    return value


def _context(
    run_dir: Path, state: dict[str, Any], *, require_workspace: bool = True
) -> dict[str, Any]:
    if state.get("phase") != PHASE or _position(state) not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于规则复盘锚点")

    workspace = _workspace_from_state(state, require_exists=require_workspace)
    requirement_id = state.get("active_requirement")
    registry = state.get("requirement_registry")
    cycle = state.get("requirement_cycle")
    if (
        not is_valid_requirement_id(requirement_id)
        or not isinstance(registry, dict)
        or not isinstance(registry.get("requirements"), list)
        or not isinstance(cycle, dict)
        or cycle.get("requirement_id") != requirement_id
        or cycle.get("branch") != f"req/{requirement_id.lower()}"
        or not isinstance(cycle.get("trd_path"), str)
        or not cycle["trd_path"]
    ):
        raise RuntimeError("活动需求上下文不符合约定")
    active = [
        item
        for item in registry["requirements"]
        if isinstance(item, dict) and item.get("status") == "active"
    ]
    if (
        len(active) != 1
        or active[0].get("id") != requirement_id
        or active[0].get("completion") is not None
    ):
        raise RuntimeError("活动需求与需求注册表不一致")

    names = state.get("applicable_repositories")
    descriptors = state.get("repositories")
    recorded = cycle.get("repositories")
    if (
        not isinstance(names, list)
        or not names
        or names[0] != "root"
        or len(set(names)) != len(names)
        or any(not isinstance(name, str) or not name for name in names)
        or not isinstance(descriptors, list)
        or len(descriptors) != len(names)
        or not isinstance(recorded, dict)
        or set(recorded) != set(names)
    ):
        raise RuntimeError("活动需求仓库状态不符合约定")
    repositories: list[dict[str, Any]] = []
    bases: dict[str, str] = {}
    for name, descriptor in zip(names, descriptors, strict=True):
        expected_path = workspace if name == "root" else workspace / name
        base = recorded.get(name)
        if (
            not isinstance(descriptor, dict)
            or descriptor.get("name") != name
            or descriptor.get("path") != str(expected_path)
            or not isinstance(base, dict)
            or set(base) != {"base_sha"}
            or not _is_hex_sha(base.get("base_sha"))
        ):
            raise RuntimeError("活动需求仓库基线不符合约定")
        repositories.append({"name": name, "path": expected_path})
        bases[name] = base["base_sha"]

    development_key = f"development_{requirement_id}"
    development_session_id = cycle.get("development_session_id")
    if (
        not isinstance(development_session_id, str)
        or not development_session_id
        or development_session_id != _session(state, development_key)
    ):
        raise RuntimeError("开发 session 与活动需求 cycle 不一致")
    saved_development = _read_json(
        requirement_step_result_path(run_dir, requirement_id, 15), "实现与验证结果不可读取"
    )
    expected_development_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
        "requirement_id",
        "trd_path",
        "development_session_id",
    }
    if (
        set(saved_development) != expected_development_keys
        or saved_development.get("step") != 15
        or saved_development.get("name") != "实现与验证"
        or saved_development.get("status") != "success"
        or not isinstance(saved_development.get("summary"), str)
        or not saved_development["summary"].strip()
        or saved_development.get("applicable") is not True
        or saved_development.get("outputs") != []
        or saved_development.get("blocked") is not None
        or saved_development.get("error") is not None
        or saved_development.get("requirement_id") != requirement_id
        or saved_development.get("trd_path") != cycle["trd_path"]
        or saved_development.get("development_session_id") != development_session_id
    ):
        raise RuntimeError("第 15 步没有当前活动需求的完整一致成功结果")
    return {
        "workspace": workspace,
        "requirement_id": requirement_id,
        "branch": cycle["branch"],
        "repositories": repositories,
        "bases": bases,
        "development_key": development_key,
        "development_session_id": development_session_id,
        "key": f"rule_retrospective_{requirement_id}",
    }


def initial_prompt() -> str:
    return "/session-rule-retrospective 本次开发会话\n请基于本会话真实发生的开发、验证、修复和审查事实完成复盘；如无满足沉淀门槛的候选，不修改文件并明确报告。"


def _git_run(
    path: Path,
    *args: str,
    allowed_returncodes: tuple[int, ...] = (0,),
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=path,
            text=text,
            capture_output=True,
            timeout=120,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if completed.returncode not in allowed_returncodes:
        raise RuntimeError("无法读取 Git 仓库状态")
    return completed


def _git_read(path: Path, *args: str) -> str:
    return _git_run(path, *args).stdout.rstrip("\n")


def _ref(path: Path, reference: str) -> str | None:
    completed = _git_run(
        path,
        "show-ref",
        "--verify",
        "--quiet",
        reference,
        allowed_returncodes=(0, 1),
    )
    if completed.returncode == 1:
        return None
    return _git_read(path, "show-ref", "--verify", "--hash", reference)


def _all_refs(path: Path) -> list[dict[str, str]]:
    completed = _git_run(
        path,
        "for-each-ref",
        "--sort=refname",
        "--format=%(refname)%00%(objectname)%00%(symref)",
        text=False,
    )
    raw = completed.stdout
    if not isinstance(raw, bytes):
        raise RuntimeError("Git 引用列表不符合约定")
    refs: list[dict[str, str]] = []
    for record in raw.splitlines():
        try:
            name, sha, symref = record.split(b"\0", 2)
            decoded_name = name.decode("utf-8")
            decoded_sha = sha.decode("ascii")
            decoded_symref = symref.decode("utf-8") or None
        except (ValueError, UnicodeError) as error:
            raise RuntimeError("Git 引用列表不符合约定") from error
        if (
            not decoded_name.startswith("refs/")
            or not _is_hex_sha(decoded_sha)
            or decoded_symref is not None
            and not decoded_symref.startswith("refs/")
        ):
            raise RuntimeError("Git 引用列表不符合约定")
        refs.append(
            {"name": decoded_name, "sha": decoded_sha, "symref": decoded_symref}
        )
    return refs


def _pseudo_refs(path: Path) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for name in _PSEUDO_REFS:
        raw_path = _git_read(path, "rev-parse", "--git-path", name)
        target = Path(raw_path)
        if not target.is_absolute():
            target = path / target
        if target.is_symlink():
            raise RuntimeError("Git pseudo-ref 不能是符号链接")
        if not target.exists():
            snapshots.append({"name": name, "exists": False, "content_sha256": None})
            continue
        if not target.is_file():
            raise RuntimeError("Git pseudo-ref 必须是普通文件")
        try:
            content_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as error:
            raise RuntimeError("Git pseudo-ref 不可读取") from error
        snapshots.append({"name": name, "exists": True, "content_sha256": content_sha256})
    return snapshots


def _index_fingerprint(path: Path) -> str:
    completed = _git_run(path, "ls-files", "--stage", "-v", "-z", text=False)
    raw = completed.stdout
    if not isinstance(raw, bytes):
        raise RuntimeError("Git index 语义状态不符合约定")
    return hashlib.sha256(raw).hexdigest()


def _has_in_progress_operation(path: Path) -> bool:
    for reference in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        completed = _git_run(
            path,
            "rev-parse",
            "-q",
            "--verify",
            reference,
            allowed_returncodes=(0, 1),
        )
        if completed.returncode == 0:
            return True
    for path_name in ("rebase-merge", "rebase-apply", "BISECT_START"):
        value = _git_read(path, "rev-parse", "--git-path", path_name)
        progress = Path(value)
        if not progress.is_absolute():
            progress = path / progress
        if progress.exists():
            return True
    return False


def _safe_relative_path(value: str) -> str:
    path = Path(value)
    if (
        not value
        or "\0" in value
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RuntimeError("Git 工作树路径不符合约定")
    return value


def _status_entries(path: Path) -> list[dict[str, str]]:
    completed = _git_run(
        path,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        text=False,
    )
    raw = completed.stdout
    if not isinstance(raw, bytes):
        raise RuntimeError("Git 工作树状态不符合约定")
    records = raw.split(b"\0")
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise RuntimeError("Git 工作树状态不符合约定")
        try:
            status = record[:2].decode("ascii")
            relative = _safe_relative_path(record[3:].decode("utf-8"))
        except UnicodeError as error:
            raise RuntimeError("Git 工作树路径不可读取") from error
        entry = {"status": status, "path": relative}
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                raise RuntimeError("Git 重命名或复制状态不完整")
            try:
                entry["source_path"] = _safe_relative_path(records[index].decode("utf-8"))
            except UnicodeError as error:
                raise RuntimeError("Git 工作树路径不可读取") from error
            index += 1
        entries.append(entry)
    return entries


def _node_path(repository: Path, relative: str) -> Path:
    parts = Path(_safe_relative_path(relative)).parts
    parent = repository
    for part in parts[:-1]:
        parent /= part
        if parent.is_symlink():
            raise RuntimeError("Git 工作树路径不能经过符号链接")
        if parent.exists() and not parent.is_dir():
            raise RuntimeError("Git 工作树路径父级不是目录")
    return parent / parts[-1]


def _node_state(
    repository: Path,
    relative: str,
    registered_nested_repositories: set[Path] | None = None,
) -> dict[str, Any]:
    target = _node_path(repository, relative)
    try:
        node = target.lstat()
    except FileNotFoundError:
        return {"kind": "missing", "mode": None, "content_sha256": None}
    mode = stat.S_IMODE(node.st_mode)
    if stat.S_ISREG(node.st_mode):
        try:
            contents = target.read_bytes()
        except OSError as error:
            raise RuntimeError("Git 工作树文件不可读取") from error
        return {
            "kind": "file",
            "mode": mode,
            "content_sha256": hashlib.sha256(contents).hexdigest(),
        }
    if stat.S_ISDIR(node.st_mode):
        nested_git = target / ".git"
        if nested_git.exists() or nested_git.is_symlink():
            registered = registered_nested_repositories or set()
            if target.resolve() not in registered:
                raise RuntimeError("Git-visible 目录不能包含未登记的嵌套 Git 仓库")
            return {"kind": "repository", "mode": mode, "content_sha256": None}
        return {"kind": "directory", "mode": mode, "content_sha256": None}
    if stat.S_ISLNK(node.st_mode):
        try:
            target_value = os.readlink(target)
        except OSError as error:
            raise RuntimeError("Git 工作树符号链接不可读取") from error
        return {
            "kind": "symlink",
            "mode": mode,
            "content_sha256": hashlib.sha256(os.fsencode(target_value)).hexdigest(),
        }
    raise RuntimeError("Git 工作树变更必须是普通文件、目录、符号链接或删除")


def _tracked_paths(repository: Path) -> list[str]:
    completed = _git_run(repository, "ls-files", "-z", text=False)
    raw = completed.stdout
    if not isinstance(raw, bytes):
        raise RuntimeError("Git tracked 路径列表不符合约定")
    paths: list[str] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            paths.append(_safe_relative_path(record.decode("utf-8")))
        except UnicodeError as error:
            raise RuntimeError("Git tracked 路径不可读取") from error
    return paths


def _verify_visible_symlinks(
    repository: Path, entries: list[dict[str, str]]
) -> None:
    paths = set(_tracked_paths(repository))
    for entry in entries:
        paths.add(entry["path"])
        if "source_path" in entry:
            paths.add(entry["source_path"])
    resolved_repository = repository.resolve()
    for relative in paths:
        target = _node_path(repository, relative)
        try:
            node = target.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISLNK(node.st_mode):
            continue
        try:
            target.resolve(strict=False).relative_to(resolved_repository)
        except (OSError, RuntimeError, ValueError) as error:
            raise RuntimeError("Git-visible 符号链接不能指向适用仓库外") from error


def _verify_rules_tree(workspace: Path) -> None:
    claude = workspace / ".claude"
    rules = claude / "rules"
    for path, label in ((claude, ".claude"), (rules, ".claude/rules")):
        if path.is_symlink():
            raise RuntimeError(f"产品 root 的 {label} 不能是符号链接")
        if path.exists() and not path.is_dir():
            raise RuntimeError(f"产品 root 的 {label} 必须是目录")
    if not rules.exists():
        return
    for current, directories, filenames in os.walk(rules, followlinks=False):
        for name in [*directories, *filenames]:
            path = Path(current) / name
            try:
                node = path.lstat()
            except OSError as error:
                raise RuntimeError("规则目录内容不可读取") from error
            if stat.S_ISLNK(node.st_mode):
                raise RuntimeError("规则目录不能包含符号链接")
            if stat.S_ISREG(node.st_mode) and node.st_nlink != 1:
                raise RuntimeError("规则文件不能是 hard link")
            if not stat.S_ISDIR(node.st_mode) and not stat.S_ISREG(node.st_mode):
                raise RuntimeError("规则目录只能包含普通目录和文件")


def _snapshot_entries(
    repository: Path,
    entries: list[dict[str, str]],
    registered_nested_repositories: set[Path] | None = None,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for entry in entries:
        snapshot: dict[str, Any] = {
            "status": entry["status"],
            "path": entry["path"],
            "node": _node_state(
                repository, entry["path"], registered_nested_repositories
            ),
        }
        if "source_path" in entry:
            snapshot["source_path"] = entry["source_path"]
            snapshot["source_node"] = _node_state(
                repository, entry["source_path"], registered_nested_repositories
            )
        snapshots.append(snapshot)
    return snapshots


def _repository_facts(repository: dict[str, Any], branch: str) -> dict[str, Any]:
    raw_path = repository["path"]
    if raw_path.is_symlink() or not raw_path.is_dir():
        raise RuntimeError("权威 Git 仓库路径不存在或是符号链接")
    path = raw_path.resolve()
    top_level = _git_read(path, "rev-parse", "--show-toplevel")
    if Path(top_level).resolve() != path:
        raise RuntimeError("Git 仓库顶层目录与权威仓库路径不一致")
    if _has_in_progress_operation(path):
        raise RuntimeError("Git 仓库存在未完成的合并、变基、拣选、还原或二分操作")
    head = _git_read(path, "rev-parse", "HEAD")
    main = _ref(path, "refs/heads/main")
    target = _ref(path, f"refs/heads/{branch}")
    current = _git_read(path, "branch", "--show-current")
    cached = _git_run(path, "diff", "--cached", "--quiet", allowed_returncodes=(0, 1))
    if not all(_is_hex_sha(value) for value in (head, main, target)):
        raise RuntimeError("Git 仓库引用不符合约定")
    return {
        "path": path,
        "head": head,
        "main": main,
        "target": target,
        "refs": _all_refs(path),
        "pseudo_refs": _pseudo_refs(path),
        "current": current,
        "index_clean": cached.returncode == 0,
        "index_sha256": _index_fingerprint(path),
        "entries": _status_entries(path),
    }


def _verify_fresh_repositories(context: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    registered_children = {
        repository["path"].resolve() for repository in context["repositories"][1:]
    }
    for repository in context["repositories"]:
        current = _repository_facts(repository, context["branch"])
        _verify_visible_symlinks(current["path"], current["entries"])
        current["registered_nested_repositories"] = (
            registered_children if repository["name"] == "root" else set()
        )
        base_sha = context["bases"][repository["name"]]
        if (
            current["current"] != context["branch"]
            or current["head"] != base_sha
            or current["main"] != base_sha
            or current["target"] != base_sha
            or not current["index_clean"]
        ):
            raise RuntimeError("规则复盘首次执行要求全部仓库处于活动需求记录的未提交基线")
        current["name"] = repository["name"]
        facts.append(current)
    return facts


def _baseline_from_facts(facts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "repositories": [
            {
                "name": fact["name"],
                "branch": fact["current"],
                "head": fact["head"],
                "main": fact["main"],
                "target": fact["target"],
                "refs": fact["refs"],
                "pseudo_refs": fact["pseudo_refs"],
                "index_clean": fact["index_clean"],
                "index_sha256": fact["index_sha256"],
                "entries": _snapshot_entries(
                    fact["path"],
                    fact["entries"],
                    fact["registered_nested_repositories"],
                ),
            }
            for fact in facts
        ],
    }


def _validate_node(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"kind", "mode", "content_sha256"}:
        return False
    kind = value.get("kind")
    mode = value.get("mode")
    content_sha256 = value.get("content_sha256")
    if kind == "missing":
        return mode is None and content_sha256 is None
    if kind in {"directory", "repository"}:
        return (
            isinstance(mode, int)
            and not isinstance(mode, bool)
            and 0 <= mode <= 0o7777
            and content_sha256 is None
        )
    return (
        kind in {"file", "symlink"}
        and isinstance(mode, int)
        and not isinstance(mode, bool)
        and 0 <= mode <= 0o7777
        and isinstance(content_sha256, str)
        and len(content_sha256) == 64
        and set(content_sha256) <= _HEX_SHA
    )


def _validate_snapshot_entry(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    renamed = isinstance(value.get("status"), str) and (
        "R" in value["status"] or "C" in value["status"]
    )
    expected = {"status", "path", "node"}
    if renamed:
        expected |= {"source_path", "source_node"}
    if set(value) != expected or not isinstance(value.get("status"), str):
        return False
    try:
        _safe_relative_path(value["path"])
        if renamed:
            _safe_relative_path(value["source_path"])
    except (RuntimeError, TypeError):
        return False
    return _validate_node(value.get("node")) and (
        not renamed or _validate_node(value.get("source_node"))
    )


def _validate_refs(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(
            isinstance(item, dict)
            and set(item) == {"name", "sha", "symref"}
            and isinstance(item.get("name"), str)
            and item["name"].startswith("refs/")
            and _is_hex_sha(item.get("sha"))
            and (
                item.get("symref") is None
                or isinstance(item["symref"], str)
                and item["symref"].startswith("refs/")
            )
            for item in value
        )
        and value == sorted(value, key=lambda item: item["name"])
        and len({item["name"] for item in value}) == len(value)
    )


def _validate_pseudo_refs(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != len(_PSEUDO_REFS):
        return False
    for expected_name, item in zip(_PSEUDO_REFS, value, strict=True):
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "exists", "content_sha256"}
            or item.get("name") != expected_name
            or not isinstance(item.get("exists"), bool)
        ):
            return False
        content_sha256 = item.get("content_sha256")
        if item["exists"]:
            if not (
                isinstance(content_sha256, str)
                and len(content_sha256) == 64
                and set(content_sha256) <= _HEX_SHA
            ):
                return False
        elif content_sha256 is not None:
            return False
    return True


def _baseline(state: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    section = state.get(context["key"])
    if section is None:
        return None
    if not isinstance(section, dict):
        raise RuntimeError("规则复盘执行状态不符合约定")
    value = section.get("baseline")
    if value is None:
        if section:
            raise RuntimeError("规则复盘恢复缺少持久化 Git 基线")
        return None
    if not isinstance(value, dict) or set(value) != {"version", "repositories"}:
        raise RuntimeError("规则复盘 Git 基线不符合约定")
    repositories = value.get("repositories")
    if value.get("version") != 1 or not isinstance(repositories, list):
        raise RuntimeError("规则复盘 Git 基线不符合约定")
    if len(repositories) != len(context["repositories"]):
        raise RuntimeError("规则复盘 Git 基线不符合约定")
    for saved, repository in zip(repositories, context["repositories"], strict=True):
        base_sha = context["bases"][repository["name"]]
        expected = {
            "name",
            "branch",
            "head",
            "main",
            "target",
            "refs",
            "pseudo_refs",
            "index_clean",
            "index_sha256",
            "entries",
        }
        if (
            not isinstance(saved, dict)
            or set(saved) != expected
            or saved.get("name") != repository["name"]
            or saved.get("branch") != context["branch"]
            or any(saved.get(key) != base_sha for key in ("head", "main", "target"))
            or not _validate_refs(saved.get("refs"))
            or not _validate_pseudo_refs(saved.get("pseudo_refs"))
            or saved.get("index_clean") is not True
            or not (
                isinstance(saved.get("index_sha256"), str)
                and len(saved["index_sha256"]) == 64
                and set(saved["index_sha256"]) <= _HEX_SHA
            )
            or not isinstance(saved.get("entries"), list)
            or not all(_validate_snapshot_entry(entry) for entry in saved["entries"])
        ):
            raise RuntimeError("规则复盘 Git 基线不符合约定")
    return value


def _execution_artifacts_present(run_dir: Path, state: dict[str, Any], context: dict[str, Any]) -> bool:
    sessions = state.get("claude_sessions")
    references = state.get("decision_conversations")
    conversation = run_dir / "conversations" / f"{context['key']}.json"
    return (
        context["key"] in state
        or isinstance(sessions, dict)
        and context["key"] in sessions
        or isinstance(references, dict)
        and context["key"] in references
        or conversation.exists()
        or conversation.is_symlink()
    )


def _entry_paths(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    paths = {entry["path"]: entry}
    if "source_path" in entry:
        paths[entry["source_path"]] = entry
    return paths


def _allowed_rule_change(relative: str, node: dict[str, Any]) -> bool:
    path = Path(relative)
    return (
        len(path.parts) >= 3
        and path.parts[:2] == (".claude", "rules")
        and path.suffix == ".md"
        and node.get("kind") == "file"
    )


def _verify_root_entries(
    repository: Path,
    baseline_entries: list[dict[str, Any]],
    current_entries: list[dict[str, Any]],
    registered_nested_repositories: set[Path],
) -> None:
    if baseline_entries == current_entries:
        return
    before: dict[str, dict[str, Any]] = {}
    after: dict[str, dict[str, Any]] = {}
    for entry in baseline_entries:
        before.update(_entry_paths(entry))
    for entry in current_entries:
        after.update(_entry_paths(entry))
    for relative in set(before) | set(after):
        previous = before.get(relative)
        current = after.get(relative)
        if previous == current:
            continue
        if any(
            entry is not None and ("R" in entry["status"] or "C" in entry["status"])
            for entry in (previous, current)
        ):
            raise RuntimeError("规则复盘不允许新增或变更重命名、复制文件")
        node = (
            current.get("node")
            if current and current["path"] == relative
            else _node_state(repository, relative, registered_nested_repositories)
        )
        if not _allowed_rule_change(relative, node):
            raise RuntimeError("规则复盘仅允许修改 .claude/rules/**/*.md 普通文件")


def _verify_boundary(context: dict[str, Any], baseline: dict[str, Any]) -> None:
    _verify_rules_tree(context["workspace"])
    registered_children = {
        repository["path"].resolve() for repository in context["repositories"][1:]
    }
    saved_repositories = baseline["repositories"]
    for repository, saved in zip(context["repositories"], saved_repositories, strict=True):
        current = _repository_facts(repository, context["branch"])
        _verify_visible_symlinks(current["path"], current["entries"])
        if (
            current["current"] != saved["branch"]
            or current["head"] != saved["head"]
            or current["main"] != saved["main"]
            or current["target"] != saved["target"]
            or current["refs"] != saved["refs"]
            or current["pseudo_refs"] != saved["pseudo_refs"]
            or current["index_clean"] is not saved["index_clean"]
            or current["index_sha256"] != saved["index_sha256"]
        ):
            raise RuntimeError("规则复盘期间 Git 仓库引用、分支或暂存区发生变化")
        registered_nested_repositories = (
            registered_children if repository["name"] == "root" else set()
        )
        entries = _snapshot_entries(
            current["path"], current["entries"], registered_nested_repositories
        )
        if repository["name"] == "root":
            _verify_root_entries(
                current["path"],
                saved["entries"],
                entries,
                registered_nested_repositories,
            )
        elif entries != saved["entries"]:
            raise RuntimeError("规则复盘期间非 root 仓库工作树发生变化")


def _saved_result(run_dir: Path, requirement_id: str) -> dict[str, Any] | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    if not path.exists() and not path.is_symlink():
        return None
    return _read_json(path, "规则复盘结果不可读取")


def _validate_success(saved: Any, state: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if _session(state, context["key"]) != context["development_session_id"]:
        raise RuntimeError("规则复盘没有复用原开发 session")
    if _baseline(state, context) is None:
        raise RuntimeError("规则复盘完整成功结果缺少 Git 基线")
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
        "requirement_id",
        "development_session_id",
    }
    if (
        not isinstance(saved, dict)
        or set(saved) != expected_keys
        or saved.get("step") != STEP
        or saved.get("name") != NAME
        or saved.get("status") != "success"
        or not isinstance(saved.get("summary"), str)
        or not saved["summary"].strip()
        or saved.get("applicable") is not True
        or saved.get("outputs") != []
        or saved.get("blocked") is not None
        or saved.get("error") is not None
        or saved.get("requirement_id") != context["requirement_id"]
        or saved.get("development_session_id") != context["development_session_id"]
    ):
        raise RuntimeError("规则复盘完整成功结果不符合约定")
    return saved


def _advance(run_dir: Path, state: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    state.update(
        {
            "status": "success",
            "phase": PHASE,
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return saved


def has_complete_success(run_dir: Path, state: dict[str, Any]) -> bool:
    try:
        context = _context(run_dir, state, require_workspace=False)
        saved = _saved_result(run_dir, context["requirement_id"])
        _validate_success(saved, state, context)
    except (RuntimeError, ValueError, TypeError):
        return False
    return True


def failure_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, str] | None:
    try:
        context = _context(run_dir, state, require_workspace=False)
    except (RuntimeError, ValueError, TypeError):
        return None
    return {
        "requirement_id": context["requirement_id"],
        "development_session_id": context["development_session_id"],
    }


def _persist_fresh_baseline(
    run_dir: Path, state: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    if _execution_artifacts_present(run_dir, state, context):
        raise RuntimeError("新鲜规则复盘入口不得包含既有执行产物")
    _verify_rules_tree(context["workspace"])
    facts = _verify_fresh_repositories(context)
    baseline = _baseline_from_facts(facts)
    sessions = state.get("claude_sessions")
    if not isinstance(sessions, dict):
        raise RuntimeError("Claude session 状态不符合约定")
    sessions[context["key"]] = context["development_session_id"]
    state[context["key"]] = {"baseline": baseline}
    state.update(
        {
            "status": "running",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return baseline


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    advanced = _position(state) == (STEP + 1, STEP + 1, NEXT_NODE)
    context = _context(run_dir, state, require_workspace=not advanced)
    saved = _saved_result(run_dir, context["requirement_id"])

    if advanced:
        if (
            state.get("status") != "success"
            or state.get("blocked") is not None
            or state.get("error") is not None
        ):
            raise RuntimeError("规则复盘成功状态不符合约定")
        return _validate_success(saved, state, context)

    baseline = _baseline(state, context)
    if baseline is None:
        baseline = _persist_fresh_baseline(run_dir, state, context)
    elif _session(state, context["key"]) != context["development_session_id"]:
        raise RuntimeError("规则复盘恢复没有原开发 session 别名")

    if saved is not None:
        try:
            complete = _validate_success(saved, state, context)
        except RuntimeError:
            pass
        else:
            _verify_boundary(context, baseline)
            return _advance(run_dir, state, complete)

    _verify_boundary(context, baseline)
    if state.get("status") != "blocked":
        state.update(
            {
                "status": "running",
                "phase": PHASE,
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": None,
                "error": None,
            }
        )
        write_state(run_dir, state)

    decision_spec = AgentDecisionLoopSpec(
        key=context["key"],
        state_key=context["key"],
        skill_name=SKILL_NAME,
        max_decision_rounds=8,
        max_turns=48,
        max_budget_usd=16.0,
        decision_system_prompt=render_decision_system_prompt(RULE_RETROSPECTIVE_DECISION_RULES, {}),
    )

    async def verified_agent_runner(prompt: str, **kwargs: Any) -> Any:
        try:
            return await agent_runner(prompt, **kwargs)
        finally:
            _verify_boundary(context, baseline)

    async def verified_decision_runner(
        messages: list[dict[str, str]], config: Any, *, system_prompt: str
    ) -> Any:
        _verify_boundary(context, baseline)
        try:
            return await decision_runner(messages, config, system_prompt=system_prompt)
        finally:
            _verify_boundary(context, baseline)

    try:
        decision = await run_agent_decision_loop(
            run_dir,
            state,
            context["workspace"],
            decision_spec,
            initial_prompt(),
            lambda: None,
            agent_runner=verified_agent_runner,
            decision_runner=verified_decision_runner,
            config_loader=config_loader,
        )
    except Exception:
        _verify_boundary(context, baseline)
        raise
    _verify_boundary(context, baseline)

    if decision.verdict == "blocked":
        blocked = {"reason": decision.reason, "required_inputs": decision.required_inputs}
        blocked_result = result(
            "blocked",
            decision.reason,
            requirement_id=context["requirement_id"],
            development_session_id=context["development_session_id"],
            blocked=blocked,
        )
        write_requirement_step_result(run_dir, context["requirement_id"], STEP, blocked_result)
        state.update(
            {
                "status": "blocked",
                "phase": PHASE,
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": blocked,
                "error": None,
            }
        )
        write_state(run_dir, state)
        raise RuleRetrospectiveBlocked(
            decision.reason,
            decision.required_inputs,
            requirement_id=context["requirement_id"],
            development_session_id=context["development_session_id"],
        )
    if decision.verdict != "completed":
        raise RuntimeError("规则复盘决策不符合约定")
    success = result(
        "success",
        "session-rule-retrospective 已完成本次开发会话的规则复盘。",
        requirement_id=context["requirement_id"],
        development_session_id=context["development_session_id"],
    )
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, success)
