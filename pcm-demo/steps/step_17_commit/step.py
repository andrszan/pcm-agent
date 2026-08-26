from __future__ import annotations

import hashlib
import json
import os
import re
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

STEP = 17
NAME = "统一提交需求变更"
CURRENT_NODE = "requirement:17_commit"
NEXT_NODE = "requirement:18_merge"
PHASE = "phase_1_requirement_development"
SKILL_NAME = "commit-changes"

REPOSITORY_REPAIR_PROMPT = (
    "请继续处理权威仓库清单中尚未提交的已有变更；不得修改或丢弃文件内容来让检查通过。"
    "完成后重新核验清单内每个仓库的工作区和暂存区均干净。"
)

REQUIREMENT_COMMIT_DECISION_RULES = """- completed：权威仓库清单中的已有需求变更均已按仓库分别完成必要的本地提交；每个仓库仍位于指定需求分支，工作区和暂存区均干净，且没有剩余提交工作。
- continue：当前环境仍可继续完成清单内仓库的提交或核验时，给出明确的下一步指令；不得授权修改或丢弃文件内容、扩大仓库范围、切换分支、合并、改写历史或 push。
- blocked：只能用于缺少当前环境无法取得的合法 Git 作者身份、强制签名凭据、外部授权或其它不可替代外部条件。"""

_HEX_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_HISTORY_MARKERS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "REBASE_HEAD",
    "BISECT_HEAD",
)


class RequirementCommitBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        *,
        requirement_id: str,
        branch: str,
    ) -> None:
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.requirement_id = requirement_id
        self.branch = branch


def result(
    status: str,
    summary: str,
    *,
    requirement_id: str | None = None,
    branch: str | None = None,
    repositories: list[dict[str, Any]] | None = None,
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
        "branch": branch,
        "repositories": repositories or [],
    }


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _HEX_SHA.fullmatch(value) is not None


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
    position = _position(state)
    if state.get("phase") != PHASE or position not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于需求提交锚点")

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
        or not isinstance(active[0].get("title"), str)
        or not active[0]["title"].strip()
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
        or any(
            not isinstance(name, str)
            or not name
            or name.strip() != name
            or Path(name).name != name
            or name in {".", ".."}
            for name in names
        )
        or not isinstance(descriptors, list)
        or len(descriptors) != len(names)
        or not isinstance(recorded, dict)
        or set(recorded) != set(names)
    ):
        raise RuntimeError("活动需求仓库状态不符合约定")

    advanced = position == (STEP + 1, STEP + 1, NEXT_NODE)
    repositories: list[dict[str, Any]] = []
    bases: dict[str, str] = {}
    recorded_tips: dict[str, str] = {}
    for name, descriptor in zip(names, descriptors, strict=True):
        expected_path = workspace if name == "root" else workspace / name
        repository = recorded.get(name)
        expected_keys = {"base_sha", "tip_sha", "merged"} if advanced else {"base_sha"}
        if (
            not isinstance(descriptor, dict)
            or descriptor.get("name") != name
            or descriptor.get("path") != str(expected_path)
            or not isinstance(repository, dict)
            or set(repository) != expected_keys
            or not _is_sha(repository.get("base_sha"))
        ):
            raise RuntimeError("活动需求仓库基线不符合约定")
        if advanced:
            if not _is_sha(repository.get("tip_sha")) or repository.get("merged") is not False:
                raise RuntimeError("活动需求仓库提交状态不符合约定")
            recorded_tips[name] = repository["tip_sha"]
        repositories.append({"name": name, "path": expected_path})
        bases[name] = repository["base_sha"]

    development_session_id = cycle.get("development_session_id")
    saved = _read_json(
        requirement_step_result_path(run_dir, requirement_id, 16), "规则复盘结果不可读取"
    )
    expected_result_keys = {
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
        set(saved) != expected_result_keys
        or saved.get("step") != 16
        or saved.get("name") != "规则复盘"
        or saved.get("status") != "success"
        or not isinstance(saved.get("summary"), str)
        or not saved["summary"].strip()
        or saved.get("applicable") is not True
        or saved.get("outputs") != []
        or saved.get("blocked") is not None
        or saved.get("error") is not None
        or saved.get("requirement_id") != requirement_id
        or not isinstance(development_session_id, str)
        or not development_session_id
        or saved.get("development_session_id") != development_session_id
    ):
        raise RuntimeError("第 16 步没有当前活动需求的完整一致成功结果")

    return {
        "workspace": workspace,
        "requirement_id": requirement_id,
        "title": active[0]["title"],
        "branch": cycle["branch"],
        "cycle": cycle,
        "repositories": repositories,
        "names": names,
        "bases": bases,
        "recorded_tips": recorded_tips,
        "key": f"requirement_commit_{requirement_id}",
        "advanced": advanced,
    }


def _git_run(
    path: Path,
    *args: str,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=path,
            text=True,
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


def _git_hash(path: Path, content: bytes, *, relative: str | None = None) -> str:
    command = ["git", "hash-object"]
    if relative is not None:
        command.append(f"--path={relative}")
    command.append("--stdin")
    try:
        completed = subprocess.run(
            command,
            cwd=path,
            input=content,
            capture_output=True,
            timeout=120,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if completed.returncode != 0:
        raise RuntimeError("无法读取 Git 仓库状态")
    try:
        oid = completed.stdout.decode("ascii").strip()
    except UnicodeError as error:
        raise RuntimeError("Git 对象摘要不符合约定") from error
    if not _is_sha(oid):
        raise RuntimeError("Git 对象摘要不符合约定")
    return oid


def _z_paths(value: str) -> list[str]:
    if not value:
        return []
    records = value.split("\0")
    if records[-1] == "":
        records.pop()
    if any(not record or Path(record).is_absolute() or ".." in Path(record).parts for record in records):
        raise RuntimeError("Git 路径列表不符合约定")
    return records


def _worktree_entry(path: Path, relative: str, tracked_mode: str | None = None) -> tuple[str, str]:
    target = path / relative
    try:
        mode = target.lstat().st_mode
    except OSError as error:
        raise RuntimeError("Git 工作树内容不可读取") from error
    if stat.S_ISLNK(mode):
        try:
            content = os.fsencode(os.readlink(target))
        except OSError as error:
            raise RuntimeError("Git 工作树符号链接不可读取") from error
        return "120000", _git_hash(path, content)
    if stat.S_ISREG(mode):
        try:
            content = target.read_bytes()
        except OSError as error:
            raise RuntimeError("Git 工作树文件不可读取") from error
        git_mode = "100755" if mode & 0o111 else "100644"
        return git_mode, _git_hash(path, content, relative=relative)
    if stat.S_ISDIR(mode) and tracked_mode == "160000":
        oid = _git_read(target, "rev-parse", "HEAD")
        if not _is_sha(oid):
            raise RuntimeError("Git 子仓库引用不符合约定")
        return "160000", oid
    raise RuntimeError("Git 工作树包含不支持的节点类型")


def _tree_fingerprint(entries: dict[str, tuple[str, str]]) -> str:
    normalized = [
        {"path": path, "mode": mode, "oid": oid}
        for path, (mode, oid) in sorted(entries.items())
    ]
    raw = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _working_tree_fingerprint(path: Path) -> str:
    entries: dict[str, tuple[str, str]] = {}
    stage_records = _git_read(path, "ls-files", "--stage", "-z")
    for record in stage_records.split("\0") if stage_records else []:
        if not record:
            continue
        try:
            metadata, relative = record.split("\t", 1)
            mode, oid, stage = metadata.split(" ", 2)
        except ValueError as error:
            raise RuntimeError("Git index 列表不符合约定") from error
        if stage != "0" or not _is_sha(oid):
            raise RuntimeError("Git index 列表不符合约定")
        entries[relative] = (mode, oid)

    modified = _z_paths(_git_read(path, "diff", "--name-only", "-z"))
    for relative in modified:
        target = path / relative
        if target.exists() or target.is_symlink():
            tracked = entries.get(relative)
            entries[relative] = _worktree_entry(
                path, relative, tracked[0] if tracked is not None else None
            )
        else:
            entries.pop(relative, None)

    for relative in _z_paths(
        _git_read(path, "ls-files", "--others", "--exclude-standard", "-z")
    ):
        entries[relative] = _worktree_entry(path, relative)
    return _tree_fingerprint(entries)


def _head_tree_fingerprint(path: Path, reference: str) -> str:
    entries: dict[str, tuple[str, str]] = {}
    raw = _git_read(path, "ls-tree", "-r", "-z", "--full-tree", reference)
    for record in raw.split("\0") if raw else []:
        if not record:
            continue
        try:
            metadata, relative = record.split("\t", 1)
            mode, _kind, oid = metadata.split(" ", 2)
        except ValueError as error:
            raise RuntimeError("Git tree 列表不符合约定") from error
        if not _is_sha(oid):
            raise RuntimeError("Git tree 列表不符合约定")
        entries[relative] = (mode, oid)
    return _tree_fingerprint(entries)


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


def _history_in_progress(path: Path) -> bool:
    for marker in _HISTORY_MARKERS:
        if (
            _git_run(
                path,
                "rev-parse",
                "--quiet",
                "--verify",
                marker,
                allowed_returncodes=(0, 1),
            ).returncode
            == 0
        ):
            return True
    for name in ("rebase-merge", "rebase-apply"):
        git_path = Path(_git_read(path, "rev-parse", "--git-path", name))
        if not git_path.is_absolute():
            git_path = path / git_path
        if git_path.exists():
            return True
    return False


def _is_ancestor(path: Path, base: str, tip: str) -> bool:
    completed = _git_run(
        path,
        "merge-base",
        "--is-ancestor",
        base,
        tip,
        allowed_returncodes=(0, 1),
    )
    return completed.returncode == 0


def _trees_differ(path: Path, base: str, tip: str) -> bool:
    completed = _git_run(
        path,
        "diff",
        "--quiet",
        base,
        tip,
        "--",
        allowed_returncodes=(0, 1),
    )
    return completed.returncode == 1


def _has_merge_commit(path: Path, base: str, tip: str) -> bool:
    return bool(_git_read(path, "rev-list", "--min-parents=2", f"{base}..{tip}"))


def _repository_facts(context: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for repository in context["repositories"]:
        raw_path = repository["path"]
        if raw_path.is_symlink() or not raw_path.is_dir():
            raise RuntimeError("权威 Git 仓库路径不存在或是符号链接")
        path = raw_path.resolve()
        if Path(_git_read(path, "rev-parse", "--show-toplevel")).resolve() != path:
            raise RuntimeError("Git 仓库顶层目录与权威路径不一致")
        cached = _git_run(path, "diff", "--cached", "--quiet", allowed_returncodes=(0, 1))
        facts.append(
            {
                "name": repository["name"],
                "path": path,
                "branch": _git_read(path, "branch", "--show-current"),
                "head": _git_read(path, "rev-parse", "HEAD"),
                "main": _ref(path, "refs/heads/main"),
                "target": _ref(path, f"refs/heads/{context['branch']}"),
                "dirty": _git_read(path, "status", "--porcelain=v1", "--untracked-files=all")
                != "",
                "index_clean": cached.returncode == 0,
                "history_in_progress": _history_in_progress(path),
            }
        )
    return facts


def _verify_static_facts(context: dict[str, Any], facts: list[dict[str, Any]]) -> None:
    for fact in facts:
        base = context["bases"][fact["name"]]
        if fact["branch"] != context["branch"]:
            raise RuntimeError("权威仓库不在统一需求分支")
        if fact["main"] != base:
            raise RuntimeError("权威仓库 main 已偏离活动需求基线")
        if fact["target"] != fact["head"]:
            raise RuntimeError("权威仓库需求分支引用与 HEAD 不一致")
        if fact["history_in_progress"]:
            raise RuntimeError("权威仓库存在进行中的 Git 历史操作")


def _verify_fresh(context: dict[str, Any]) -> list[dict[str, Any]]:
    facts = _repository_facts(context)
    _verify_static_facts(context, facts)
    for fact in facts:
        base = context["bases"][fact["name"]]
        if fact["head"] != base or not fact["index_clean"]:
            raise RuntimeError("需求提交 fresh 入口的仓库基线不符合约定")
        fact["tree_sha256"] = _working_tree_fingerprint(fact["path"])
    return facts


def _preflight(state: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]] | None:
    section = state.get(context["key"])
    if section is None:
        return None
    if not isinstance(section, dict):
        raise RuntimeError("需求提交运行状态不符合约定")
    repositories = section.get("repositories")
    if not isinstance(repositories, list) or len(repositories) != len(context["names"]):
        raise RuntimeError("需求提交首次仓库状态不符合约定")
    for name, repository in zip(context["names"], repositories, strict=True):
        if (
            not isinstance(repository, dict)
            or set(repository) != {"name", "dirty", "tree_sha256"}
            or repository.get("name") != name
            or type(repository.get("dirty")) is not bool
            or not isinstance(repository.get("tree_sha256"), str)
            or len(repository["tree_sha256"]) != 64
            or set(repository["tree_sha256"]) - set("0123456789abcdef")
        ):
            raise RuntimeError("需求提交首次仓库状态不符合约定")
    return repositories


def _preflight_map(preflight: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {repository["name"]: repository for repository in preflight}


def _verify_content_fingerprints(
    facts: list[dict[str, Any]], preflight: list[dict[str, Any]]
) -> None:
    recorded = _preflight_map(preflight)
    for fact in facts:
        if _working_tree_fingerprint(fact["path"]) != recorded[fact["name"]]["tree_sha256"]:
            raise RuntimeError("需求提交过程中工作树内容发生变化")


def _conversation_path(context: dict[str, Any]) -> Path:
    return Path("conversations") / f"{context['key']}.json"


def _execution_artifacts_present(
    run_dir: Path, state: dict[str, Any], context: dict[str, Any]
) -> bool:
    sessions = state.get("claude_sessions")
    references = state.get("decision_conversations")
    return (
        context["key"] in state
        or isinstance(sessions, dict)
        and context["key"] in sessions
        or isinstance(references, dict)
        and context["key"] in references
        or (run_dir / _conversation_path(context)).exists()
        or (run_dir / _conversation_path(context)).is_symlink()
    )


def _resume_anchor(
    run_dir: Path,
    state: dict[str, Any],
    context: dict[str, Any],
    facts: list[dict[str, Any]],
) -> None:
    session = _session(state, context["key"])
    references = state.get("decision_conversations")
    reference = references.get(context["key"]) if isinstance(references, dict) else None
    conversation = run_dir / _conversation_path(context)
    if session is not None:
        if (
            not isinstance(reference, dict)
            or reference.get("path") != _conversation_path(context).as_posix()
            or conversation.is_symlink()
            or not conversation.is_file()
        ):
            raise RuntimeError("需求提交恢复缺少原决策历史")
    advanced = any(
        fact["head"] != context["bases"][fact["name"]] for fact in facts
    )
    if advanced and (
        session is None
        or not isinstance(reference, dict)
        or reference.get("path") != _conversation_path(context).as_posix()
        or conversation.is_symlink()
        or not conversation.is_file()
    ):
        raise RuntimeError("需求提交恢复缺少原 Claude session 或决策历史")


def _verify_committed_history(path: Path, base: str, tip: str) -> None:
    if not _is_ancestor(path, base, tip):
        raise RuntimeError("需求分支提交历史不再基于活动需求基线")
    if tip != base and _has_merge_commit(path, base, tip):
        raise RuntimeError("需求分支包含不允许的 merge commit")
    if tip != base and not _trees_differ(path, base, tip):
        raise RuntimeError("需求分支只产生了空或净零差异提交")


def _verify_resume(
    context: dict[str, Any], facts: list[dict[str, Any]], preflight: list[dict[str, Any]]
) -> None:
    _verify_static_facts(context, facts)
    _verify_content_fingerprints(facts, preflight)
    recorded = _preflight_map(preflight)
    for fact in facts:
        name = fact["name"]
        base = context["bases"][name]
        initial = recorded[name]
        if not initial["dirty"]:
            if fact["head"] != base or fact["dirty"] or not fact["index_clean"]:
                raise RuntimeError("初始 clean 仓库出现了需求提交变化")
            continue
        _verify_committed_history(fact["path"], base, fact["head"])
        if fact["head"] == base and not fact["dirty"]:
            raise RuntimeError("初始 dirty 仓库的待提交变更已消失")


def _completion_repair(
    context: dict[str, Any], preflight: list[dict[str, Any]]
) -> str | None:
    facts = _repository_facts(context)
    _verify_static_facts(context, facts)
    _verify_content_fingerprints(facts, preflight)
    recorded = _preflight_map(preflight)
    needs_repair = False
    for fact in facts:
        name = fact["name"]
        base = context["bases"][name]
        initial = recorded[name]
        if not initial["dirty"]:
            if fact["head"] != base or fact["dirty"] or not fact["index_clean"]:
                raise RuntimeError("初始 clean 仓库出现了需求提交变化")
            continue
        _verify_committed_history(fact["path"], base, fact["head"])
        if fact["dirty"] or not fact["index_clean"]:
            needs_repair = True
            continue
        if fact["head"] == base:
            raise RuntimeError("初始 dirty 仓库没有形成需求提交")
        if _head_tree_fingerprint(fact["path"], fact["head"]) != initial["tree_sha256"]:
            raise RuntimeError("需求提交没有完整保留首次工作树内容")
    return REPOSITORY_REPAIR_PROMPT if needs_repair else None


def _result_repositories(
    context: dict[str, Any], preflight: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if _completion_repair(context, preflight) is not None:
        raise RuntimeError("需求提交完成核验后仍有未提交变更")
    facts = _repository_facts(context)
    return [
        {
            "name": fact["name"],
            "path": "." if fact["name"] == "root" else fact["name"],
            "base_sha": context["bases"][fact["name"]],
            "tip_sha": fact["head"],
        }
        for fact in facts
    ]


def initial_prompt(context: dict[str, Any]) -> str:
    repositories = "\n".join(
        f"- {repository['name']}: @./{'' if repository['name'] == 'root' else repository['name']}"
        for repository in context["repositories"]
    )
    return f"""/commit-changes
请提交当前需求 `{context['requirement_id']} {context['title']}` 已经完成并验证的全部现有变更。

统一需求分支：`{context['branch']}`
权威仓库清单（集合和顺序均不可扩大）：
{repositories}

只在上述独立仓库中处理已有变更。每个 dirty 仓库按可独立理解的功能结果创建必要的本地提交；clean 仓库报告无需提交，不制造空提交。不得寻找或处理清单外 Git 仓库，不得修改或丢弃文件内容来让检查通过，不得创建或切换分支、merge、rebase、reset、amend、改写历史或 push。完成后确保清单内每个仓库仍在统一需求分支，且工作区和暂存区均干净。"""


def _saved_result(run_dir: Path, requirement_id: str) -> dict[str, Any] | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    if not path.exists() and not path.is_symlink():
        return None
    return _read_json(path, "需求提交结果不可读取")


def _validate_success(
    saved: Any,
    state: dict[str, Any],
    context: dict[str, Any],
    *,
    verify_git: bool,
) -> dict[str, Any]:
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
        "branch",
        "repositories",
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
        or saved.get("branch") != context["branch"]
        or not isinstance(saved.get("repositories"), list)
        or len(saved["repositories"]) != len(context["names"])
    ):
        raise RuntimeError("需求提交完整成功结果不符合约定")

    tips: dict[str, str] = {}
    for name, repository in zip(context["names"], saved["repositories"], strict=True):
        expected = {
            "name": name,
            "path": "." if name == "root" else name,
            "base_sha": context["bases"][name],
        }
        if (
            not isinstance(repository, dict)
            or set(repository) != {"name", "path", "base_sha", "tip_sha"}
            or {key: repository.get(key) for key in expected} != expected
            or not _is_sha(repository.get("tip_sha"))
        ):
            raise RuntimeError("需求提交仓库结果不符合约定")
        tips[name] = repository["tip_sha"]

    if context["advanced"]:
        if tips != context["recorded_tips"]:
            raise RuntimeError("需求提交结果与活动 cycle 不一致")
    elif verify_git:
        preflight = _preflight(state, context)
        if preflight is None:
            raise RuntimeError("需求提交完整成功结果缺少首次仓库状态")
        current = _result_repositories(context, preflight)
        if current != saved["repositories"]:
            raise RuntimeError("需求提交结果与当前 Git 事实不一致")
    return saved


def _advance(
    run_dir: Path, state: dict[str, Any], context: dict[str, Any], saved: dict[str, Any]
) -> dict[str, Any]:
    context["cycle"]["repositories"] = {
        repository["name"]: {
            "base_sha": repository["base_sha"],
            "tip_sha": repository["tip_sha"],
            "merged": False,
        }
        for repository in saved["repositories"]
    }
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
        advanced = _position(state) == (STEP + 1, STEP + 1, NEXT_NODE)
        context = _context(run_dir, state, require_workspace=not advanced)
        saved = _saved_result(run_dir, context["requirement_id"])
        _validate_success(saved, state, context, verify_git=not advanced)
    except (RuntimeError, ValueError, TypeError):
        return False
    return True


def failure_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, str] | None:
    try:
        context = _context(run_dir, state, require_workspace=False)
    except (RuntimeError, ValueError, TypeError):
        return None
    return {"requirement_id": context["requirement_id"], "branch": context["branch"]}


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
            raise RuntimeError("需求提交成功状态不符合约定")
        return _validate_success(saved, state, context, verify_git=False)

    if saved is not None:
        try:
            complete = _validate_success(saved, state, context, verify_git=True)
        except RuntimeError:
            pass
        else:
            return _advance(run_dir, state, context, complete)

    preflight = _preflight(state, context)
    if preflight is None:
        if _execution_artifacts_present(run_dir, state, context):
            raise RuntimeError("需求提交 fresh 入口不得包含既有执行产物")
        facts = _verify_fresh(context)
        preflight = [
            {
                "name": fact["name"],
                "dirty": fact["dirty"],
                "tree_sha256": fact["tree_sha256"],
            }
            for fact in facts
        ]
        state[context["key"]] = {"repositories": preflight}
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
    else:
        facts = _repository_facts(context)
        _verify_resume(context, facts, preflight)
        _resume_anchor(run_dir, state, context, facts)
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

    if not any(repository["dirty"] for repository in preflight):
        repositories = _result_repositories(context, preflight)
        success = result(
            "success",
            "权威仓库没有待提交变更，未制造空提交。",
            requirement_id=context["requirement_id"],
            branch=context["branch"],
            repositories=repositories,
        )
        write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
        return _advance(run_dir, state, context, success)

    decision_spec = AgentDecisionLoopSpec(
        key=context["key"],
        state_key=context["key"],
        skill_name=SKILL_NAME,
        max_decision_rounds=8,
        max_turns=48,
        max_budget_usd=16.0,
        decision_system_prompt=render_decision_system_prompt(
            REQUIREMENT_COMMIT_DECISION_RULES,
            {
                "当前需求": {
                    "id": context["requirement_id"],
                    "title": context["title"],
                    "branch": context["branch"],
                },
                "有序权威仓库": [
                    {
                        "name": repository["name"],
                        "path": "." if repository["name"] == "root" else repository["name"],
                    }
                    for repository in context["repositories"]
                ],
            },
        ),
    )
    decision = await run_agent_decision_loop(
        run_dir,
        state,
        context["workspace"],
        decision_spec,
        initial_prompt(context),
        lambda: _completion_repair(context, preflight),
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
    )

    if decision.verdict == "blocked":
        blocked = {"reason": decision.reason, "required_inputs": decision.required_inputs}
        blocked_result = result(
            "blocked",
            decision.reason,
            requirement_id=context["requirement_id"],
            branch=context["branch"],
            blocked=blocked,
        )
        write_requirement_step_result(
            run_dir, context["requirement_id"], STEP, blocked_result
        )
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
        raise RequirementCommitBlocked(
            decision.reason,
            decision.required_inputs,
            requirement_id=context["requirement_id"],
            branch=context["branch"],
        )
    if decision.verdict != "completed":
        raise RuntimeError("需求提交决策不符合约定")

    repositories = _result_repositories(context, preflight)
    success = result(
        "success",
        "已在权威仓库完成当前需求变更的本地提交并核验 Git 事实。",
        requirement_id=context["requirement_id"],
        branch=context["branch"],
        repositories=repositories,
    )
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, context, success)
