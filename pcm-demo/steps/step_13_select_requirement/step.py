from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from common.state import (
    requirement_step_result_path,
    write_requirement_step_result,
    write_state,
)
from steps.step_12_initialize_requirement_registry.step import (
    has_complete_success as has_registry_success,
    validate_catalog,
)

STEP = 13
NAME = "选择需求并建立统一需求分支"
CURRENT_NODE = "phase_1:select_requirement"
NEXT_NODE = "requirement:14_trd_design"
PHASE = "phase_1_requirement_development"

_HEX_SHA = re.compile(r"^[0-9a-f]{40,64}$")


class NoPendingRequirements(RuntimeError):
    """需求注册表已无 pending 项，留待后续阶段处理。"""


def result(
    status: str,
    summary: str,
    *,
    requirement_id: str | None = None,
    branch: str | None = None,
    repositories: list[dict[str, Any]] | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": [],
        "blocked": None,
        "error": error,
        "requirement_id": requirement_id,
        "branch": branch,
        "repositories": repositories or [],
    }


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


def _read_json(path: Path, message: str) -> Any:
    if path.is_symlink():
        raise RuntimeError(message)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(message) from error


def _workspace_from_state(state: dict[str, Any]) -> Path:
    try:
        root_value = state["workspace"]["root"]
        workspace_value = state["workspace"]["final_path"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    if not isinstance(root_value, str) or not isinstance(workspace_value, str):
        raise RuntimeError("工作区状态记录不完整")
    root = Path(root_value)
    workspace = Path(workspace_value)
    if not root.is_absolute() or not workspace.is_absolute() or workspace.is_symlink():
        raise RuntimeError("工作区状态路径不符合约定")
    root = root.resolve()
    workspace = workspace.resolve()
    if workspace.parent != root or not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    return workspace


def _repository_handoff(run_dir: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    workspace = _workspace_from_state(state)
    saved = _read_json(run_dir / "steps" / "08.json", "第 8 步成功结果不可读取")
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
        "applicable_repositories",
        "repositories",
    }
    if (
        not isinstance(saved, dict)
        or set(saved) != expected_keys
        or type(saved.get("step")) is not int
        or saved.get("step") != 8
        or saved.get("name") != "首次提交适用仓库"
        or saved.get("status") != "success"
        or not isinstance(saved.get("summary"), str)
        or not saved["summary"].strip()
        or saved.get("applicable") is not True
        or saved.get("outputs") != []
        or saved.get("blocked") is not None
        or saved.get("error") is not None
        or not isinstance(saved.get("applicable_repositories"), list)
        or not isinstance(saved.get("repositories"), list)
    ):
        raise RuntimeError("第 8 步成功结果不符合约定")
    names = saved["applicable_repositories"]
    if (
        not names
        or names[0] != "root"
        or any(
            not isinstance(name, str)
            or not name
            or name.strip() != name
            or Path(name).name != name
            or name in {".", ".."}
            for name in names
        )
        or len(set(names)) != len(names)
        or len(saved["repositories"]) != len(names)
    ):
        raise RuntimeError("第 8 步适用仓库清单不符合约定")
    for name, repository in zip(names, saved["repositories"], strict=True):
        if repository != {
            "name": name,
            "path": "." if name == "root" else name,
            "branch": "main",
            "worktree_clean": True,
        }:
            raise RuntimeError("第 8 步仓库描述不符合约定")

    state_names = state.get("applicable_repositories")
    state_repositories = state.get("repositories")
    if state_names != names or not isinstance(state_repositories, list) or len(state_repositories) != len(names):
        raise RuntimeError("运行状态中的适用仓库与第 8 步不一致")
    repositories: list[dict[str, Any]] = []
    for name, repository in zip(names, state_repositories, strict=True):
        expected_path = workspace if name == "root" else workspace / name
        if (
            not isinstance(repository, dict)
            or set(repository) != {"name", "path", "branch", "worktree_clean"}
            or repository.get("name") != name
            or repository.get("path") != str(expected_path)
            or repository.get("branch") != "main"
            or repository.get("worktree_clean") is not True
        ):
            raise RuntimeError("运行状态中的仓库描述不符合约定")
        repositories.append({"name": name, "path": Path(repository["path"])})
    return repositories


def _registry_handoff(
    run_dir: Path, state: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    saved = _read_json(run_dir / "steps" / "12.json", "第 12 步成功结果不可读取")
    if not has_registry_success(saved):
        raise RuntimeError("第 12 步没有完整成功结果")
    source = saved["source"]
    catalog = validate_catalog(saved["requirement_catalog"])
    registry = state.get("requirement_registry")
    registry_keys = {"schema_version", "source", "requirements"}
    if (
        not isinstance(registry, dict)
        or not registry_keys.issubset(registry)
        or type(registry.get("schema_version")) is not int
        or registry.get("schema_version") != 1
        or registry.get("source") != source
        or not isinstance(registry.get("requirements"), list)
        or len(registry["requirements"]) != len(catalog)
    ):
        raise RuntimeError("需求注册表与第 12 步不一致")

    requirements = registry["requirements"]
    requirement_keys = {"id", "title", "order", "depends_on", "status", "completion"}
    for expected, requirement in zip(catalog, requirements, strict=True):
        if (
            not isinstance(requirement, dict)
            or not requirement_keys.issubset(requirement)
            or {key: requirement.get(key) for key in ("id", "title", "order", "depends_on")} != expected
            or requirement.get("status") not in {"pending", "active", "completed"}
            or (
                requirement.get("status") in {"pending", "active"}
                and requirement.get("completion") is not None
            )
            or (
                requirement.get("status") == "completed"
                and requirement.get("completion") is None
            )
        ):
            raise RuntimeError("需求注册表动态字段不符合约定")
    return catalog, requirements


def _cycle(
    state: dict[str, Any], repositories: list[dict[str, Any]], requirement_id: str
) -> tuple[str, dict[str, str]]:
    cycle = state.get("requirement_cycle")
    expected_branch = f"req/{requirement_id.lower()}"
    required_keys = {
        "requirement_id",
        "branch",
        "repositories",
        "return_node_after_completion",
    }
    if (
        not isinstance(cycle, dict)
        or not required_keys.issubset(cycle)
        or cycle.get("requirement_id") != requirement_id
        or cycle.get("branch") != expected_branch
        or cycle.get("return_node_after_completion") != CURRENT_NODE
        or not isinstance(cycle.get("repositories"), dict)
    ):
        raise RuntimeError("活动需求 cycle 不符合约定")
    recorded = cycle["repositories"]
    names = [repository["name"] for repository in repositories]
    if set(recorded) != set(names):
        raise RuntimeError("活动需求 cycle 仓库集合不符合约定")
    bases: dict[str, str] = {}
    for name in names:
        value = recorded[name]
        if (
            not isinstance(value, dict)
            or "base_sha" not in value
            or not isinstance(value.get("base_sha"), str)
            or not _HEX_SHA.fullmatch(value["base_sha"])
        ):
            raise RuntimeError("活动需求 cycle 仓库基线不符合约定")
        bases[name] = value["base_sha"]
    return expected_branch, bases


def _context(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    repositories = _repository_handoff(run_dir, state)
    catalog, requirements = _registry_handoff(run_dir, state)
    active = state.get("active_requirement")
    cycle = state.get("requirement_cycle")
    active_entries = [requirement for requirement in requirements if requirement["status"] == "active"]
    if active is None and cycle is None:
        if active_entries:
            raise RuntimeError("需求注册表存在未记录的活动需求")
        return {
            "mode": "fresh",
            "repositories": repositories,
            "catalog": catalog,
            "requirements": requirements,
        }
    if not isinstance(active, str) or active not in {requirement["id"] for requirement in catalog}:
        raise RuntimeError("活动需求不符合需求注册表")
    requirement_step_result_path(run_dir, active, STEP)
    if len(active_entries) != 1 or active_entries[0]["id"] != active:
        raise RuntimeError("活动需求与需求注册表状态不一致")
    branch, bases = _cycle(state, repositories, active)
    return {
        "mode": "recovery",
        "repositories": repositories,
        "catalog": catalog,
        "requirements": requirements,
        "requirement_id": active,
        "branch": branch,
        "bases": bases,
    }


def _select(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    pending = [requirement for requirement in requirements if requirement["status"] == "pending"]
    if not pending:
        raise NoPendingRequirements("没有待处理需求，当前步骤不负责转入后续阶段")
    statuses = {requirement["id"]: requirement["status"] for requirement in requirements}
    ready = [
        requirement
        for requirement in pending
        if all(statuses[dependency] == "completed" for dependency in requirement["depends_on"])
    ]
    if not ready:
        raise RuntimeError("需求注册表没有依赖已完成的待处理需求")
    return min(ready, key=lambda requirement: requirement["order"])


def _git(path: Path, *args: str, allowed_returncodes: tuple[int, ...] = (0,)) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=path,
            text=True,
            capture_output=True,
            timeout=120,
            env={
                key: value for key, value in os.environ.items() if not key.startswith("GIT_")
            },
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if completed.returncode not in allowed_returncodes:
        raise RuntimeError("无法读取或切换 Git 仓库状态")
    if completed.returncode != 0:
        return None
    return completed.stdout.rstrip("\n")


def _ref(path: Path, reference: str) -> str | None:
    exists = _git(
        path,
        "show-ref",
        "--verify",
        "--quiet",
        reference,
        allowed_returncodes=(0, 1),
    )
    if exists is None:
        return None
    return _git(path, "show-ref", "--verify", "--hash", reference)


def _has_in_progress_operation(path: Path) -> bool:
    for reference in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if _git(
            path,
            "rev-parse",
            "-q",
            "--verify",
            reference,
            allowed_returncodes=(0, 1),
        ) is not None:
            return True
    for directory in ("rebase-merge", "rebase-apply"):
        value = _git(path, "rev-parse", "--git-path", directory)
        if isinstance(value, str):
            progress = Path(value)
            if not progress.is_absolute():
                progress = path / progress
            if progress.is_dir():
                return True
    return False


def _repository_facts(repository: dict[str, Any], branch: str) -> dict[str, Any]:
    raw_path = repository["path"]
    if raw_path.is_symlink() or not raw_path.is_dir():
        raise RuntimeError("权威 Git 仓库路径不存在或是符号链接")
    path = raw_path.resolve()
    top_level = _git(path, "rev-parse", "--show-toplevel")
    if top_level is None or Path(top_level).resolve() != path:
        raise RuntimeError("Git 仓库顶层目录与权威仓库路径不一致")
    if _has_in_progress_operation(path):
        raise RuntimeError("Git 仓库存在未完成的合并、变基、拣选或还原操作")
    head = _git(path, "rev-parse", "HEAD")
    main = _ref(path, "refs/heads/main")
    target = _ref(path, f"refs/heads/{branch}")
    current = _git(path, "branch", "--show-current")
    clean = _git(path, "status", "--porcelain=v1", "--untracked-files=all") == ""
    if not isinstance(head, str) or not _HEX_SHA.fullmatch(head):
        raise RuntimeError("Git 仓库 HEAD 不符合约定")
    if main is not None and not _HEX_SHA.fullmatch(main):
        raise RuntimeError("Git 仓库 main 引用不符合约定")
    if target is not None and not _HEX_SHA.fullmatch(target):
        raise RuntimeError("Git 仓库需求分支引用不符合约定")
    return {
        "path": path,
        "current": current,
        "clean": clean,
        "head": head,
        "main": main,
        "target": target,
    }


def _verify_on_main(repository: dict[str, Any], branch: str, base_sha: str, *, target_absent: bool) -> None:
    facts = _repository_facts(repository, branch)
    if (
        facts["current"] != "main"
        or not facts["clean"]
        or facts["head"] != base_sha
        or facts["main"] != base_sha
        or target_absent
        and facts["target"] is not None
    ):
        raise RuntimeError("Git 仓库不是记录的 clean main 基线")


def _verify_on_target(repository: dict[str, Any], branch: str, base_sha: str) -> None:
    facts = _repository_facts(repository, branch)
    if (
        facts["current"] != branch
        or not facts["clean"]
        or facts["head"] != base_sha
        or facts["main"] != base_sha
        or facts["target"] != base_sha
    ):
        raise RuntimeError("Git 仓库需求分支与记录基线不一致")


def _verify_branch_name(run_dir: Path, branch: str) -> None:
    if _git(run_dir, "check-ref-format", "--branch", branch) != branch:
        raise RuntimeError("需求分支名不符合 Git 引用约定")


def _create_branch(repository: dict[str, Any], branch: str, base_sha: str) -> None:
    _verify_on_main(repository, branch, base_sha, target_absent=True)
    _git(repository["path"], "switch", "-c", branch, base_sha)
    _verify_on_target(repository, branch, base_sha)


def _recover_branch(repository: dict[str, Any], branch: str, base_sha: str) -> None:
    facts = _repository_facts(repository, branch)
    if facts["target"] is None:
        _create_branch(repository, branch, base_sha)
        return
    if facts["target"] != base_sha:
        raise RuntimeError("已有需求分支不指向记录基线")
    if facts["current"] == branch:
        _verify_on_target(repository, branch, base_sha)
        return
    if facts["current"] != "main":
        raise RuntimeError("恢复时 Git 仓库不在 main 或记录的需求分支")
    _verify_on_main(repository, branch, base_sha, target_absent=False)
    _git(repository["path"], "switch", branch)
    _verify_on_target(repository, branch, base_sha)


def _saved_result(run_dir: Path, requirement_id: str) -> Any | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    if not path.exists() and not path.is_symlink():
        return None
    return _read_json(path, "需求选择结果不可读取")


def _result_repositories(context: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "name": repository["name"],
            "path": "." if repository["name"] == "root" else repository["name"],
            "base_sha": context["bases"][repository["name"]],
        }
        for repository in context["repositories"]
    ]


def _validate_success(saved: Any, context: dict[str, Any]) -> dict[str, Any]:
    expected_repositories = _result_repositories(context)
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
        or type(saved.get("step")) is not int
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
        or saved.get("repositories") != expected_repositories
    ):
        raise RuntimeError("需求选择完整成功结果不符合约定")
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


def _verify_advanced(state: dict[str, Any], context: dict[str, Any], saved: Any) -> dict[str, Any]:
    if (
        state.get("status") != "success"
        or state.get("phase") != PHASE
        or _position(state) != (STEP + 1, STEP + 1, NEXT_NODE)
        or state.get("blocked") is not None
        or state.get("error") is not None
    ):
        raise RuntimeError("第 13 步成功状态不符合约定")
    return _validate_success(saved, context)


def has_complete_success(run_dir: Path, state: dict[str, Any]) -> bool:
    try:
        context = _context(run_dir, state)
        if context["mode"] != "recovery":
            return False
        saved = _saved_result(run_dir, context["requirement_id"])
        _validate_success(saved, context)
    except (RuntimeError, ValueError, TypeError):
        return False
    return True


def failure_scope(run_dir: Path, state: dict[str, Any]) -> tuple[str, str] | None:
    try:
        context = _context(run_dir, state)
    except (RuntimeError, ValueError, TypeError):
        return None
    if context["mode"] != "recovery":
        return None
    return context["requirement_id"], context["branch"]


def run(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("phase") != PHASE:
        raise RuntimeError("运行状态不位于需求选择锚点")
    context = _context(run_dir, state)
    position = _position(state)
    if position == (STEP + 1, STEP + 1, NEXT_NODE):
        if context["mode"] != "recovery":
            raise RuntimeError("第 13 步成功状态缺少活动需求")
        saved = _saved_result(run_dir, context["requirement_id"])
        return _verify_advanced(state, context, saved)
    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于需求选择锚点")

    if context["mode"] == "fresh":
        selected = _select(context["requirements"])
        requirement_id = selected["id"]
        requirement_step_result_path(run_dir, requirement_id, STEP)
        branch = f"req/{requirement_id.lower()}"
        _verify_branch_name(run_dir, branch)
        bases: dict[str, str] = {}
        for repository in context["repositories"]:
            facts = _repository_facts(repository, branch)
            if (
                facts["current"] != "main"
                or not facts["clean"]
                or facts["main"] is None
                or facts["head"] != facts["main"]
                or facts["target"] is not None
            ):
                raise RuntimeError("fresh 需求选择要求全部权威仓库位于 clean main 基线")
            bases[repository["name"]] = facts["head"]
        selected["status"] = "active"
        state.update(
            {
                "status": "running",
                "phase": PHASE,
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "active_requirement": requirement_id,
                "requirement_cycle": {
                    "requirement_id": requirement_id,
                    "branch": branch,
                    "repositories": {
                        repository["name"]: {"base_sha": bases[repository["name"]]}
                        for repository in context["repositories"]
                    },
                    "return_node_after_completion": CURRENT_NODE,
                },
                "blocked": None,
                "error": None,
            }
        )
        write_state(run_dir, state)
        context.update(
            {
                "mode": "recovery",
                "requirement_id": requirement_id,
                "branch": branch,
                "bases": bases,
            }
        )
    else:
        saved = _saved_result(run_dir, context["requirement_id"])
        if saved is not None:
            try:
                _validate_success(saved, context)
            except RuntimeError:
                pass
            else:
                for repository in context["repositories"]:
                    _verify_on_target(
                        repository,
                        context["branch"],
                        context["bases"][repository["name"]],
                    )
                return _advance(run_dir, state, saved)
        _verify_branch_name(run_dir, context["branch"])

    for repository in context["repositories"]:
        base_sha = context["bases"][repository["name"]]
        _recover_branch(repository, context["branch"], base_sha)

    saved = result(
        "success",
        "已选择依赖已完成且 order 最小的需求，并建立统一需求分支。",
        requirement_id=context["requirement_id"],
        branch=context["branch"],
        repositories=_result_repositories(context),
    )
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, saved)
    return _advance(run_dir, state, saved)
