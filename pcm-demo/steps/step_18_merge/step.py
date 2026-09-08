from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from common.state import (
    is_valid_requirement_id,
    requirement_step_result_path,
    write_requirement_step_result,
    write_state,
)

STEP = 18
NAME = "程序化合并并完成需求"
CURRENT_NODE = "requirement:18_merge"
NEXT_NODE = "phase_1:select_requirement"
PHASE = "phase_1_requirement_development"
_HEX = set("0123456789abcdef")
_RESULT_FIELDS = {
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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and set(value) <= _HEX


def _read_json(path: Path, message: str) -> dict[str, Any]:
    if path.is_symlink():
        raise RuntimeError(message)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(message) from error
    _require(isinstance(value, dict), message)
    return value


def _names(state: dict[str, Any]) -> list[str]:
    names = state.get("applicable_repositories")
    _require(
        isinstance(names, list)
        and bool(names)
        and names[0] == "root"
        and len(set(names)) == len(names)
        and all(
            isinstance(name, str)
            and bool(name)
            and name.strip() == name
            and Path(name).name == name
            and name not in {".", ".."}
            for name in names
        ),
        "适用仓库白名单不符合约定",
    )
    return names


def _active(state: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    requirement_id = state.get("active_requirement")
    registry = state.get("requirement_registry")
    cycle = state.get("requirement_cycle")
    _require(
        is_valid_requirement_id(requirement_id)
        and isinstance(registry, dict)
        and isinstance(registry.get("requirements"), list)
        and isinstance(cycle, dict)
        and cycle.get("requirement_id") == requirement_id
        and cycle.get("branch") == f"req/{requirement_id.lower()}"
        and cycle.get("return_node_after_completion") == NEXT_NODE,
        "活动需求上下文不符合约定",
    )
    active = [
        item
        for item in registry["requirements"]
        if isinstance(item, dict) and item.get("status") == "active"
    ]
    _require(
        len(active) == 1
        and active[0].get("id") == requirement_id
        and active[0].get("completion") is None,
        "活动需求与需求注册表不一致",
    )
    return requirement_id, active[0], cycle


def _cycle_repositories(
    cycle: dict[str, Any], names: list[str]
) -> tuple[dict[str, str], dict[str, str], dict[str, bool]]:
    recorded = cycle.get("repositories")
    _require(
        isinstance(recorded, dict) and set(recorded) == set(names),
        "活动需求仓库状态不符合约定",
    )
    bases: dict[str, str] = {}
    tips: dict[str, str] = {}
    merged: dict[str, bool] = {}
    for name in names:
        repository = recorded[name]
        _require(
            isinstance(repository, dict)
            and {"base_sha", "tip_sha", "merged"}.issubset(repository)
            and _is_sha(repository.get("base_sha"))
            and _is_sha(repository.get("tip_sha"))
            and type(repository.get("merged")) is bool,
            "活动需求仓库合并状态不符合约定",
        )
        bases[name] = repository["base_sha"]
        tips[name] = repository["tip_sha"]
        merged[name] = repository["merged"]
    return bases, tips, merged


def _workspace_repositories(state: dict[str, Any], names: list[str]) -> list[dict[str, Any]]:
    try:
        root = Path(state["workspace"]["root"])
        workspace = Path(state["workspace"]["final_path"])
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    _require(
        root.is_absolute()
        and workspace.is_absolute()
        and not workspace.is_symlink()
        and workspace.is_dir()
        and workspace.resolve().parent == root.resolve(),
        "产品工作区路径与状态根目录不一致",
    )
    workspace = workspace.resolve()
    descriptors = state.get("repositories")
    _require(
        isinstance(descriptors, list) and len(descriptors) == len(names),
        "适用仓库描述不符合约定",
    )
    repositories: list[dict[str, Any]] = []
    for name, descriptor in zip(names, descriptors, strict=True):
        path = workspace if name == "root" else workspace / name
        descriptor_path = descriptor.get("path") if isinstance(descriptor, dict) else None
        _require(
            not path.is_symlink()
            and path.is_dir()
            and (name == "root" or path.resolve().parent == workspace)
            and isinstance(descriptor, dict)
            and descriptor.get("name") == name
            and isinstance(descriptor_path, str)
            and Path(descriptor_path).is_absolute()
            and Path(descriptor_path).resolve() == path.resolve(),
            "适用仓库描述不符合约定",
        )
        repositories.append({"name": name, "path": path.resolve()})
    return repositories


def _context(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    _require(
        state.get("phase") == PHASE and _position(state) == (STEP, STEP, CURRENT_NODE),
        "运行状态不位于需求合并锚点",
    )
    requirement_id, active, cycle = _active(state)
    names = _names(state)
    bases, tips, merged = _cycle_repositories(cycle, names)
    repositories = _workspace_repositories(state, names)
    context = {
        "requirement_id": requirement_id,
        "active": active,
        "cycle": cycle,
        "branch": cycle["branch"],
        "names": names,
        "bases": bases,
        "tips": tips,
        "merged": merged,
        "repositories": repositories,
    }
    _commit_success(run_dir, context)
    return context


def _result_repositories(context: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "name": repository["name"],
            "path": "." if repository["name"] == "root" else repository["name"],
            "base_sha": context["bases"][repository["name"]],
            "tip_sha": context["tips"][repository["name"]],
        }
        for repository in context["repositories"]
    ]


def _repository_results_match(value: Any, context: dict[str, Any]) -> bool:
    expected = _result_repositories(context)
    return (
        isinstance(value, list)
        and len(value) == len(expected)
        and all(
            isinstance(repository, dict)
            and all(repository.get(key) == expected_repository[key] for key in expected_repository)
            for repository, expected_repository in zip(value, expected, strict=True)
        )
    )


def _commit_success(run_dir: Path, context: dict[str, Any]) -> None:
    saved = _read_json(
        requirement_step_result_path(run_dir, context["requirement_id"], 17),
        "需求提交结果不可读取",
    )
    _require(
        saved.get("step") == 17
        and saved.get("name") == "统一提交需求变更"
        and saved.get("status") == "success"
        and isinstance(saved.get("summary"), str)
        and bool(saved["summary"].strip())
        and saved.get("applicable") is True
        and saved.get("outputs") == []
        and saved.get("blocked") is None
        and saved.get("error") is None
        and saved.get("requirement_id") == context["requirement_id"]
        and saved.get("branch") == context["branch"]
        and _repository_results_match(saved.get("repositories"), context),
        "第 17 步没有当前活动需求的一致成功结果",
    )


def _git(
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
    except OSError as error:
        raise RuntimeError("无法执行 Git 命令") from error
    if completed.returncode not in allowed_returncodes:
        raise RuntimeError("无法读取 Git 仓库状态")
    return completed


def _git_read(path: Path, *args: str) -> str:
    return _git(path, *args).stdout.rstrip("\n")


def _git_write(path: Path, *args: str) -> None:
    allowed = args == ("switch", "main") or (
        len(args) == 3 and args[0] == "merge" and args[1] == "--ff-only"
    )
    if not allowed:
        allowed = len(args) == 3 and args[0] == "branch" and args[1] == "-d"
    _require(allowed, "不允许的 Git 写入命令")
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
    except OSError as error:
        raise RuntimeError("无法执行 Git 命令") from error
    if completed.returncode != 0:
        raise RuntimeError("Git 写入操作失败")


def _ref(path: Path, reference: str) -> str | None:
    completed = _git(
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


def _has_in_progress_operation(path: Path) -> bool:
    for reference in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        completed = _git(
            path,
            "rev-parse",
            "-q",
            "--verify",
            reference,
            allowed_returncodes=(0, 1),
        )
        if completed.returncode == 0:
            return True
    for name in ("rebase-merge", "rebase-apply", "BISECT_START"):
        raw = _git_read(path, "rev-parse", "--git-path", name)
        progress = Path(raw)
        if not progress.is_absolute():
            progress = path / progress
        if progress.exists():
            return True
    return False


def _facts(repository: dict[str, Any], branch: str) -> dict[str, Any]:
    name = repository["name"]
    path = repository["path"]
    _require(
        isinstance(path, Path) and not path.is_symlink() and path.is_dir(),
        f"权威仓库 {name}: Git 路径不存在或是符号链接",
    )
    path = path.resolve()
    _require(
        Path(_git_read(path, "rev-parse", "--show-toplevel")).resolve() == path,
        f"权威仓库 {name}: Git 顶层目录与白名单路径不一致",
    )
    _require(not _has_in_progress_operation(path), f"权威仓库 {name}: 存在未完成的 Git 操作")
    status = _git_read(path, "status", "--porcelain=v1", "--untracked-files=all")
    facts = {
        "path": path,
        "current": _git_read(path, "branch", "--show-current"),
        "head": _git_read(path, "rev-parse", "HEAD"),
        "main": _ref(path, "refs/heads/main"),
        "target": _ref(path, f"refs/heads/{branch}"),
        "status": status,
        "clean": status == "",
    }
    _require(
        _is_sha(facts["head"])
        and (facts["main"] is None or _is_sha(facts["main"]))
        and (facts["target"] is None or _is_sha(facts["target"])),
        f"权威仓库 {name}: Git 引用不符合约定",
    )
    return facts


def _verify_ancestry(context: dict[str, Any], name: str, facts: dict[str, Any]) -> None:
    base, tip, main = context["bases"][name], context["tips"][name], facts["main"]
    _require(main is not None, f"权威仓库 {name}: main 引用不存在")
    try:
        base_before_main = _git(
            facts["path"], "merge-base", "--is-ancestor", base, main,
            allowed_returncodes=(0, 1),
        ).returncode == 0
        main_before_tip = _git(
            facts["path"], "merge-base", "--is-ancestor", main, tip,
            allowed_returncodes=(0, 1),
        ).returncode == 0
    except RuntimeError as error:
        raise RuntimeError(f"权威仓库 {name}: 无法校验 base、main 与 saved tip 的祖先关系") from error
    _require(base_before_main, f"权威仓库 {name}: base 不是 main 的祖先")
    _require(main_before_tip, f"权威仓库 {name}: main 不是 saved tip 的祖先")


def _only_untracked(status: Any) -> bool:
    return isinstance(status, str) and bool(status) and all(
        line.startswith("?? ") for line in status.splitlines()
    )


def _merge_facts(context: dict[str, Any], repository: dict[str, Any]) -> dict[str, Any]:
    name = repository["name"]
    facts = _facts(repository, context["branch"])
    _require(
        facts["current"] in {"main", context["branch"]},
        f"权威仓库 {name}: 当前分支不是 main 或统一需求分支",
    )
    _require(facts["main"] is not None, f"权威仓库 {name}: main 引用不存在")
    _require(facts["target"] == context["tips"][name], f"权威仓库 {name}: target 与 saved tip 不一致")
    _require(facts["clean"], f"权威仓库 {name}: 工作区或暂存区不干净")
    if facts["current"] == "main":
        _require(facts["head"] == facts["main"], f"权威仓库 {name}: main 与 HEAD 不一致")
    else:
        _require(facts["head"] == context["tips"][name], f"权威仓库 {name}: 需求分支 HEAD 与 saved tip 不一致")
    _verify_ancestry(context, name, facts)
    return facts


def _mark_merged(run_dir: Path, state: dict[str, Any], context: dict[str, Any], name: str) -> None:
    if context["cycle"]["repositories"][name]["merged"] is False:
        context["cycle"]["repositories"][name]["merged"] = True
        context["merged"][name] = True
        write_state(run_dir, state)


def _merge_repository(run_dir: Path, state: dict[str, Any], context: dict[str, Any], repository: dict[str, Any]) -> None:
    name = repository["name"]
    facts = _merge_facts(context, repository)
    tip = context["tips"][name]
    captured_main = facts["main"]
    merged = context["merged"][name]

    if captured_main == tip:
        _mark_merged(run_dir, state, context, name)
        return
    _require(merged is False, f"权威仓库 {name}: 已记录合并但 main 尚未到达 saved tip")
    if facts["current"] != "main":
        _git_write(repository["path"], "switch", "main")
    facts = _facts(repository, context["branch"])
    _require(facts["current"] == "main", f"权威仓库 {name}: switch 后未处于 main")
    _require(
        facts["head"] == captured_main and facts["main"] == captured_main,
        f"权威仓库 {name}: switch 后 main 或 HEAD 不再等于 captured main",
    )
    _require(facts["target"] == tip, f"权威仓库 {name}: switch 后 target 与 saved tip 不一致")
    _require(
        facts["clean"] or _only_untracked(facts["status"]),
        f"权威仓库 {name}: fast-forward 前工作区或暂存区不干净",
    )
    _verify_ancestry(context, name, facts)
    _git_write(repository["path"], "merge", "--ff-only", tip)
    facts = _merge_facts(context, repository)
    _require(
        facts["current"] == "main"
        and facts["head"] == tip
        and facts["main"] == tip
        and facts["target"] == tip,
        f"权威仓库 {name}: fast-forward 合并后未精确到达 saved tip",
    )
    _mark_merged(run_dir, state, context, name)


def _verify_all_merged(context: dict[str, Any]) -> None:
    _require(all(context["merged"].values()), "并非全部权威仓库已记录为已合并")
    for repository in context["repositories"]:
        name = repository["name"]
        facts = _facts(repository, context["branch"])
        _verify_ancestry(context, name, facts)
        _require(
            facts["current"] in {"main", context["branch"]}
            and facts["head"] == context["tips"][name]
            and facts["main"] == context["tips"][name]
            and facts["target"] in {None, context["tips"][name]}
            and facts["clean"]
            and (facts["target"] is not None or facts["current"] == "main"),
            f"权威仓库 {name}: 未精确完成到 saved tip 的 fast-forward 合并",
        )


def _cleanup_facts(context: dict[str, Any], repository: dict[str, Any]) -> dict[str, Any]:
    name = repository["name"]
    facts = _facts(repository, context["branch"])
    _verify_ancestry(context, name, facts)
    _require(
        facts["current"] in {"main", context["branch"]}
        and facts["main"] == context["tips"][name]
        and facts["clean"]
        and facts["target"] in {None, context["tips"][name]},
        f"权威仓库 {name}: 分支清理前未精确处于 saved tip",
    )
    if facts["target"] is None:
        _require(
            facts["current"] == "main" and facts["head"] == facts["main"],
            f"权威仓库 {name}: 分支清理恢复状态不符合约定",
        )
    else:
        _require(facts["head"] == context["tips"][name], f"权威仓库 {name}: 分支清理前 HEAD 不是 saved tip")
    return facts


def _cleanup_repository(context: dict[str, Any], repository: dict[str, Any]) -> None:
    name = repository["name"]
    facts = _cleanup_facts(context, repository)
    if facts["target"] is not None:
        if facts["current"] != "main":
            _git_write(repository["path"], "switch", "main")
        facts = _cleanup_facts(context, repository)
        _require(
            facts["current"] == "main"
            and facts["head"] == context["tips"][name]
            and facts["target"] == context["tips"][name],
            f"权威仓库 {name}: 删除需求分支前状态不符合约定",
        )
        _git_write(repository["path"], "branch", "-d", context["branch"])
    _final_facts(context, repository)


def _final_facts(context: dict[str, Any], repository: dict[str, Any]) -> None:
    name = repository["name"]
    facts = _facts(repository, context["branch"])
    _verify_ancestry(context, name, facts)
    _require(
        facts["current"] == "main"
        and facts["head"] == context["tips"][name]
        and facts["main"] == context["tips"][name]
        and facts["target"] is None
        and facts["clean"],
        f"权威仓库 {name}: 最终状态未精确处于 saved tip",
    )


def _final_facts_all(context: dict[str, Any]) -> None:
    for repository in context["repositories"]:
        _final_facts(context, repository)


def _ordered_repositories(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [*context["repositories"][1:], context["repositories"][0]]


def _saved_result(run_dir: Path, requirement_id: str) -> dict[str, Any] | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    if not path.exists() and not path.is_symlink():
        return None
    saved = _read_json(path, "需求合并结果不可读取")
    return saved if saved.get("status") == "success" else None


def _validate_success(saved: Any, context: dict[str, Any]) -> dict[str, Any]:
    _require(
        isinstance(saved, dict)
        and _RESULT_FIELDS.issubset(saved)
        and saved.get("step") == STEP
        and saved.get("name") == NAME
        and saved.get("status") == "success"
        and isinstance(saved.get("summary"), str)
        and bool(saved["summary"].strip())
        and saved.get("applicable") is True
        and saved.get("outputs") == []
        and saved.get("blocked") is None
        and saved.get("error") is None
        and saved.get("requirement_id") == context["requirement_id"]
        and saved.get("branch") == context["branch"]
        and _repository_results_match(saved.get("repositories"), context),
        "需求合并完整成功结果不符合约定",
    )
    return saved


def _advance(run_dir: Path, state: dict[str, Any], context: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    _require(
        context["cycle"].get("return_node_after_completion") == NEXT_NODE,
        "活动需求 cycle 缺少完成后的返回节点",
    )
    context["active"]["status"] = "completed"
    context["active"]["completion"] = {"step": STEP}
    state.update(
        {
            "status": "success",
            "phase": PHASE,
            "step": 13,
            "current_step": 13,
            "current_node": NEXT_NODE,
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return saved


def has_complete_success(run_dir: Path, state: dict[str, Any]) -> bool:
    if _position(state) != (STEP, STEP, CURRENT_NODE):
        return False
    try:
        context = _context(run_dir, state)
        _validate_success(_saved_result(run_dir, context["requirement_id"]), context)
        _final_facts_all(context)
    except (RuntimeError, TypeError, ValueError):
        return False
    return True


def failure_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, str] | None:
    if _position(state) != (STEP, STEP, CURRENT_NODE):
        return None
    try:
        context = _context(run_dir, state)
    except (RuntimeError, TypeError, ValueError):
        return None
    return {"requirement_id": context["requirement_id"], "branch": context["branch"]}


def run(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    context = _context(run_dir, state)
    saved = _saved_result(run_dir, context["requirement_id"])
    if saved is not None:
        complete = _validate_success(saved, context)
        _final_facts_all(context)
        return _advance(run_dir, state, context, complete)

    if not all(context["merged"].values()):
        for repository in _ordered_repositories(context):
            _merge_repository(run_dir, state, context, repository)

    _verify_all_merged(context)
    for repository in _ordered_repositories(context):
        _cleanup_repository(context, repository)

    success = result(
        "success",
        "已完成全部权威仓库的 fast-forward 合并、需求分支清理和 Git 事实核验。",
        requirement_id=context["requirement_id"],
        branch=context["branch"],
        repositories=_result_repositories(context),
    )
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, context, success)
