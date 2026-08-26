from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentExecutionFailure, persist_agent_failure
from common.claude_agent import ClaudeRunResult, run_claude
from common.state import (
    is_valid_requirement_id,
    requirement_step_result_path,
    write_requirement_step_result,
    write_state,
)

STEP = 17
NAME = "统一提交需求变更"
CURRENT_NODE = "requirement:17_commit"
NEXT_NODE = "requirement:18_merge"
PHASE = "phase_1_requirement_development"
MAX_TURNS = 48
MAX_BUDGET_USD = 16.0
_HEX = set("0123456789abcdef")
_RESULT_FIELDS = {"step", "name", "status", "summary", "applicable", "outputs", "blocked", "error", "requirement_id", "branch", "repositories"}


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
        "step": STEP, "name": NAME, "status": status, "summary": summary, "applicable": True,
        "outputs": [], "blocked": blocked, "error": error, "requirement_id": requirement_id,
        "branch": branch, "repositories": repositories or [],
    }


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and set(value) <= _HEX


def _read_json(path: Path, message: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(message) from error
    _require(isinstance(value, dict), message)
    return value


def _names(state: dict[str, Any]) -> list[str]:
    names = state.get("applicable_repositories")
    _require(
        isinstance(names, list) and bool(names) and names[0] == "root" and len(set(names)) == len(names)
        and all(isinstance(name, str) and name and name.strip() == name and Path(name).name == name and name not in {".", ".."} for name in names),
        "适用仓库白名单不符合约定",
    )
    return names


def _active(state: dict[str, Any], *, require_title: bool) -> tuple[str, str | None, dict[str, Any]]:
    requirement_id, registry, cycle = state.get("active_requirement"), state.get("requirement_registry"), state.get("requirement_cycle")
    _require(
        is_valid_requirement_id(requirement_id) and isinstance(registry, dict) and isinstance(registry.get("requirements"), list)
        and isinstance(cycle, dict) and cycle.get("requirement_id") == requirement_id and cycle.get("branch") == f"req/{requirement_id.lower()}",
        "活动需求上下文不符合约定",
    )
    active = [item for item in registry["requirements"] if isinstance(item, dict) and item.get("status") == "active"]
    _require(
        len(active) == 1 and active[0].get("id") == requirement_id and active[0].get("completion") is None
        and (not require_title or isinstance(active[0].get("title"), str) and bool(active[0]["title"].strip())),
        "活动需求与需求注册表不一致",
    )
    return requirement_id, active[0].get("title"), cycle


def _cycle_repositories(cycle: dict[str, Any], names: list[str], *, advanced: bool) -> tuple[dict[str, str], dict[str, str]]:
    recorded = cycle.get("repositories")
    _require(isinstance(recorded, dict) and set(recorded) == set(names), "活动需求仓库状态不符合约定")
    bases, tips = {}, {}
    expected = {"base_sha", "tip_sha", "merged"} if advanced else {"base_sha"}
    for name in names:
        repository = recorded[name]
        _require(isinstance(repository, dict) and set(repository) == expected and _is_sha(repository.get("base_sha")), "活动需求仓库基线不符合约定")
        bases[name] = repository["base_sha"]
        if advanced:
            _require(_is_sha(repository.get("tip_sha")) and repository.get("merged") is False, "活动需求仓库提交状态不符合约定")
            tips[name] = repository["tip_sha"]
    return bases, tips


def _valid_result(saved: Any, *, step: int, name: str, requirement_id: str, fields: set[str]) -> bool:
    return (
        isinstance(saved, dict) and set(saved) == fields and saved.get("step") == step and saved.get("name") == name
        and saved.get("status") == "success" and isinstance(saved.get("summary"), str) and bool(saved["summary"].strip())
        and saved.get("applicable") is True and saved.get("outputs") == [] and saved.get("blocked") is None
        and saved.get("error") is None and saved.get("requirement_id") == requirement_id
    )


def _step_sixteen_success(run_dir: Path, requirement_id: str, cycle: dict[str, Any]) -> None:
    saved = _read_json(requirement_step_result_path(run_dir, requirement_id, 16), "规则复盘结果不可读取")
    session_id = cycle.get("development_session_id")
    _require(
        _valid_result(saved, step=16, name="规则复盘", requirement_id=requirement_id, fields=(_RESULT_FIELDS - {"branch", "repositories"}) | {"development_session_id"})
        and isinstance(session_id, str) and bool(session_id) and saved.get("development_session_id") == session_id,
        "第 16 步没有当前活动需求的完整一致成功结果",
    )


def _context(run_dir: Path, state: dict[str, Any], *, advanced: bool) -> dict[str, Any]:
    _require(state.get("phase") == PHASE and _position(state) in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}, "运行状态不位于需求提交锚点")
    requirement_id, title, cycle = _active(state, require_title=not advanced)
    names = _names(state)
    bases, tips = _cycle_repositories(cycle, names, advanced=advanced)
    context = {"requirement_id": requirement_id, "title": title, "branch": cycle["branch"], "cycle": cycle, "names": names, "bases": bases, "tips": tips, "key": f"requirement_commit_{requirement_id}"}
    if advanced:
        return context
    try:
        root, workspace = Path(state["workspace"]["root"]), Path(state["workspace"]["final_path"])
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    _require(
        root.is_absolute()
        and workspace.is_absolute()
        and not workspace.is_symlink()
        and workspace.resolve().parent == root.resolve()
        and workspace.is_dir(),
        "产品工作区路径与状态根目录不一致",
    )
    workspace = workspace.resolve()
    descriptors = state.get("repositories")
    _require(isinstance(descriptors, list) and len(descriptors) == len(names), "活动需求仓库状态不符合约定")
    repositories = []
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
    _step_sixteen_success(run_dir, requirement_id, cycle)
    return {**context, "workspace": workspace, "repositories": repositories}


def _git(path: Path, *args: str, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(["git", *args], cwd=path, text=True, capture_output=True, timeout=120, env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")})
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    except OSError as error:
        raise RuntimeError("无法读取 Git 仓库状态") from error
    if completed.returncode not in allowed:
        raise RuntimeError("无法读取 Git 仓库状态")
    return completed


def _git_read(path: Path, *args: str) -> str:
    return _git(path, *args).stdout.rstrip("\n")


def _ref(path: Path, reference: str) -> str | None:
    return None if _git(path, "show-ref", "--verify", "--quiet", reference, allowed=(0, 1)).returncode else _git_read(path, "show-ref", "--verify", "--hash", reference)


def _facts(context: dict[str, Any]) -> list[dict[str, Any]]:
    facts = []
    for repository in context["repositories"]:
        path = repository["path"]
        _require(Path(_git_read(path, "rev-parse", "--show-toplevel")).resolve() == path.resolve(), "Git 仓库顶层目录与白名单路径不一致")
        facts.append({"name": repository["name"], "branch": _git_read(path, "branch", "--show-current"), "head": _git_read(path, "rev-parse", "HEAD"), "main": _ref(path, "refs/heads/main"), "target": _ref(path, f"refs/heads/{context['branch']}"), "dirty": _git_read(path, "status", "--porcelain=v1", "--untracked-files=all") != ""})
    return facts


def _verify_boundary(context: dict[str, Any], facts: list[dict[str, Any]], *, fresh: bool) -> None:
    for fact in facts:
        base = context["bases"][fact["name"]]
        _require(
            all(_is_sha(value) for value in (fact["head"], fact["main"], fact["target"])) and fact["branch"] == context["branch"]
            and fact["main"] == base and fact["target"] == fact["head"] and (not fresh or fact["head"] == base),
            "权威仓库 Git 边界不符合约定",
        )


def _repository_results(context: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": fact["name"], "path": "." if fact["name"] == "root" else fact["name"], "base_sha": context["bases"][fact["name"]], "tip_sha": fact["head"]} for fact in facts]


def initial_prompt(context: dict[str, Any]) -> str:
    repositories = "\n".join(f"- {item['name']}: `{'.' if item['name'] == 'root' else item['name']}`" for item in context["repositories"])
    return f"""/commit-changes
请提交当前需求 `{context['requirement_id']} {context['title']}` 已完成并验证的已有变更。

统一需求分支：`{context['branch']}`
适用仓库白名单（集合和顺序均不可扩大）：
{repositories}

只在白名单内的独立仓库处理已有 dirty 变更；clean 仓库不提交且不制造空提交。不得修改或丢弃文件内容来让检查通过，不得处理白名单外仓库，不得创建或切换分支、merge、rebase、reset、amend、改写历史或 push。完成后确保每个白名单仓库仍在统一需求分支，且 `git status --porcelain` 为空。"""


def resume_prompt(context: dict[str, Any]) -> str:
    return f"""请继续完成当前需求 `{context['requirement_id']}` 的本地提交。

统一需求分支：`{context['branch']}`；适用仓库白名单：{'、'.join(context['names'])}。只提交白名单内已有 dirty 变更；clean 仓库不制造空提交。不得修改或丢弃文件内容来让检查通过，不得扩大范围，不得创建或切换分支、merge、rebase、reset、amend、改写历史或 push。完成后确保每个白名单仓库的 `git status --porcelain` 为空。"""


def _saved_result(run_dir: Path, requirement_id: str) -> dict[str, Any] | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    return None if not path.exists() else _read_json(path, "需求提交结果不可读取")


def _validate_success(saved: Any, context: dict[str, Any], *, advanced: bool) -> dict[str, Any]:
    _require(_valid_result(saved, step=STEP, name=NAME, requirement_id=context["requirement_id"], fields=_RESULT_FIELDS) and saved.get("branch") == context["branch"] and isinstance(saved.get("repositories"), list) and len(saved["repositories"]) == len(context["names"]), "需求提交完整成功结果不符合约定")
    for name, repository in zip(context["names"], saved["repositories"], strict=True):
        _require(
            isinstance(repository, dict) and set(repository) == {"name", "path", "base_sha", "tip_sha"} and repository.get("name") == name
            and repository.get("path") == ("." if name == "root" else name) and repository.get("base_sha") == context["bases"][name]
            and _is_sha(repository.get("tip_sha")) and (not advanced or repository["tip_sha"] == context["tips"][name]),
            "需求提交仓库结果不符合约定",
        )
    return saved


def _complete_facts(context: dict[str, Any], saved: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    facts = _facts(context)
    _verify_boundary(context, facts, fresh=False)
    _require(not any(fact["dirty"] for fact in facts), "白名单仓库仍有未提交变更")
    _require(saved is None or _repository_results(context, facts) == saved["repositories"], "需求提交结果与当前 Git 事实不一致")
    return facts


def _session(state: dict[str, Any], key: str) -> str | None:
    sessions = state.get("claude_sessions")
    _require(sessions is None or isinstance(sessions, dict), "Claude session 状态不符合约定")
    value = sessions.get(key) if sessions else None
    _require(value is None or isinstance(value, str) and bool(value), "Claude session ID 不符合约定")
    return value


def _save_session(run_dir: Path, state: dict[str, Any], key: str, session_id: str | None) -> None:
    if session_id is None:
        return
    _require(isinstance(session_id, str) and bool(session_id), "Claude session ID 不符合约定")
    sessions = state.setdefault("claude_sessions", {})
    _require(isinstance(sessions, dict), "Claude session 状态不符合约定")
    recorded = sessions.get(key)
    _require(recorded is None or isinstance(recorded, str) and bool(recorded), "Claude session ID 不符合约定")
    _require(recorded in {None, session_id}, "Claude session ID 不一致")
    if key not in sessions:
        sessions[key] = session_id
        write_state(run_dir, state)


def _running(run_dir: Path, state: dict[str, Any]) -> None:
    state.update({"status": "running", "phase": PHASE, "step": STEP, "current_step": STEP, "current_node": CURRENT_NODE, "blocked": None, "error": None})
    write_state(run_dir, state)


def _advance(run_dir: Path, state: dict[str, Any], context: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    context["cycle"]["repositories"] = {item["name"]: {"base_sha": item["base_sha"], "tip_sha": item["tip_sha"], "merged": False} for item in saved["repositories"]}
    state.update({"status": "success", "phase": PHASE, "step": STEP + 1, "current_step": STEP + 1, "current_node": NEXT_NODE, "blocked": None, "error": None})
    write_state(run_dir, state)
    return saved


def has_complete_success(run_dir: Path, state: dict[str, Any]) -> bool:
    try:
        advanced = _position(state) == (STEP + 1, STEP + 1, NEXT_NODE)
        context = _context(run_dir, state, advanced=advanced)
        saved = _validate_success(_saved_result(run_dir, context["requirement_id"]), context, advanced=advanced)
        if not advanced:
            _complete_facts(context, saved)
    except (RuntimeError, TypeError, ValueError):
        return False
    return True


def failure_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, str] | None:
    if state.get("phase") != PHASE or _position(state) != (STEP, STEP, CURRENT_NODE):
        return None
    try:
        requirement_id, _title, cycle = _active(state, require_title=False)
    except (RuntimeError, TypeError, ValueError):
        return None
    return {"requirement_id": requirement_id, "branch": cycle["branch"]}


def _agent_succeeded(value: Any) -> bool:
    return isinstance(value, ClaudeRunResult) and value.result_subtype == "success" and value.is_error is False and value.has_errors is False and value.exception is None and value.exception_type is None and value.api_error_status is None and value.terminal_reason in {None, "completed"}


async def run(run_dir: Path, state: dict[str, Any], *, agent_runner=run_claude) -> dict[str, Any]:
    advanced = _position(state) == (STEP + 1, STEP + 1, NEXT_NODE)
    context = _context(run_dir, state, advanced=advanced)
    saved = _saved_result(run_dir, context["requirement_id"])
    if advanced:
        _require(state.get("status") == "success" and state.get("blocked") is None and state.get("error") is None, "需求提交成功状态不符合约定")
        return _validate_success(saved, context, advanced=True)
    if saved is not None and saved.get("status") == "success":
        complete = _validate_success(saved, context, advanced=False)
        _complete_facts(context, complete)
        return _advance(run_dir, state, context, complete)
    session_id = _session(state, context["key"])
    facts = _facts(context)
    _verify_boundary(context, facts, fresh=session_id is None)
    if session_id is None and not any(fact["dirty"] for fact in facts):
        success = result("success", "权威仓库没有待提交变更，未制造空提交。", requirement_id=context["requirement_id"], branch=context["branch"], repositories=_repository_results(context, facts))
        write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
        return _advance(run_dir, state, context, success)
    _running(run_dir, state)
    def on_update(update: ClaudeRunResult) -> None:
        _save_session(run_dir, state, context["key"], update.session_id)
    try:
        agent = await agent_runner(
            initial_prompt(context) if session_id is None else resume_prompt(context),
            cwd=context["workspace"],
            resume_session_id=session_id,
            max_turns=MAX_TURNS,
            max_budget_usd=MAX_BUDGET_USD,
            on_update=on_update,
        )
    except Exception as error:
        failure = persist_agent_failure(
            run_dir,
            state,
            key=context["key"],
            state_key=None,
            error=error,
            context={
                "operation": "requirement_commit",
                "requirement": context["requirement_id"],
                "node": CURRENT_NODE,
            },
        )
        raise AgentExecutionFailure(f"Claude Agent 执行异常：{failure}", failure.diagnostic_path) from error
    if isinstance(agent, ClaudeRunResult):
        _save_session(run_dir, state, context["key"], agent.session_id)
    _require(_session(state, context["key"]) is not None, "Claude Agent 未保存 session")
    facts = _facts(context)
    _verify_boundary(context, facts, fresh=False)
    if not _agent_succeeded(agent):
        failure = persist_agent_failure(
            run_dir,
            state,
            key=context["key"],
            state_key=None,
            value=agent if isinstance(agent, ClaudeRunResult) else None,
            context={
                "operation": "requirement_commit",
                "requirement": context["requirement_id"],
                "node": CURRENT_NODE,
            },
        )
        raise AgentExecutionFailure(f"需求提交未完成：{failure}", failure.diagnostic_path)
    _require(not any(fact["dirty"] for fact in facts), "需求提交未完成")
    success = result("success", "已在权威仓库完成当前需求变更的本地提交并核验 Git 事实。", requirement_id=context["requirement_id"], branch=context["branch"], repositories=_repository_results(context, facts))
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, context, success)
