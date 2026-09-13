from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from common.agent_decision_loop import (
    AgentDecisionLoopSpec,
    ResumeMessage,
    run_agent_decision_loop,
    validate_agent_decision_loop_scene,
)
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
MAX_DECISION_ROUNDS = 32
COMMIT_MAX_TURNS = 9999
REPOSITORY_REPAIR_PROMPT = "检测到白名单仓库仍有未提交变更。请按原提交授权只补做必要的精确暂存、提交或安全清理，并确认所有白名单仓库工作区与暂存区干净；只 commit，不 push。"
REQUIREMENT_COMMIT_DECISION_RULES = """- completed：已有变更均已提交或原本无变更；全部白名单仓库仍在统一需求分支，且工作区和暂存区干净。
- continue：仅当仍可在提交准备范围内继续时使用。提交准备范围只包括读取 Git 状态和候选 diff、确认提交范围、精确暂存、创建本地提交、必要时精确修改 .gitignore、核验归属和可再生性后逐路径清理非交付临时产物、hook 要求的纯格式修复，以及核验提交结果。
- blocked：仅用于缺少 Git 作者身份、签名凭据、外部授权，或在上述范围内无法安全完成提交的情况。
"""
_HEX = set("0123456789abcdef")
_RESULT_FIELDS = {"step", "name", "status", "summary", "applicable", "outputs", "blocked", "error", "requirement_id", "branch", "repositories"}


class RequirementCommitBlocked(RuntimeError):
    def __init__(
        self, reason: str, required_inputs: list[str], *, requirement_id: str, branch: str
    ) -> None:
        super().__init__(reason)
        self.reason = reason
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


def _context(run_dir: Path, state: dict[str, Any], *, advanced: bool) -> dict[str, Any]:
    _require(state.get("phase") == PHASE and _position(state) in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}, "运行状态不位于需求提交锚点")
    requirement_id, title, cycle = _active(state, require_title=not advanced)
    names = _names(state)
    bases, tips = _cycle_repositories(cycle, names, advanced=advanced)
    development_session_id = cycle.get("development_session_id")
    _require(
        isinstance(development_session_id, str) and bool(development_session_id),
        "活动需求缺少开发 session",
    )
    context = {
        "requirement_id": requirement_id,
        "title": title,
        "branch": cycle["branch"],
        "cycle": cycle,
        "names": names,
        "bases": bases,
        "tips": tips,
        "key": f"requirement_commit_{requirement_id}",
        "development_session_id": development_session_id,
    }
    if advanced:
        return context
    try:
        root, workspace = Path(state["workspace"]["root"]), Path(state["workspace"]["final_path"])
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    _require(root.is_absolute() and workspace.is_absolute() and not workspace.is_symlink() and workspace.resolve().parent == root.resolve() and workspace.is_dir(), "产品工作区路径与状态根目录不一致")
    workspace = workspace.resolve()
    descriptors = state.get("repositories")
    _require(isinstance(descriptors, list) and len(descriptors) == len(names), "活动需求仓库状态不符合约定")
    repositories = []
    for name, descriptor in zip(names, descriptors, strict=True):
        path = workspace if name == "root" else workspace / name
        descriptor_path = descriptor.get("path") if isinstance(descriptor, dict) else None
        _require(
            not path.is_symlink() and path.is_dir() and (name == "root" or path.resolve().parent == workspace)
            and isinstance(descriptor, dict) and descriptor.get("name") == name and isinstance(descriptor_path, str)
            and Path(descriptor_path).is_absolute() and Path(descriptor_path).resolve() == path.resolve(),
            "适用仓库描述不符合约定",
        )
        repositories.append({"name": name, "path": path.resolve()})
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


def _has_in_progress_operation(path: Path) -> bool:
    for reference in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if _git(path, "rev-parse", "-q", "--verify", reference, allowed=(0, 1)).returncode == 0:
            return True
    for name in ("rebase-merge", "rebase-apply", "BISECT_START"):
        progress = Path(_git_read(path, "rev-parse", "--git-path", name))
        if not progress.is_absolute():
            progress = path / progress
        if progress.exists():
            return True
    return False


def _facts(context: dict[str, Any]) -> list[dict[str, Any]]:
    facts = []
    for repository in context["repositories"]:
        name, path = repository["name"], repository["path"]
        _require(
            Path(_git_read(path, "rev-parse", "--show-toplevel")).resolve() == path.resolve(),
            f"权威仓库 {name}: Git 顶层目录与白名单路径不一致",
        )
        _require(not _has_in_progress_operation(path), f"权威仓库 {name}: 存在未完成的 Git 操作")
        facts.append({
            "name": name,
            "path": path,
            "branch": _git_read(path, "branch", "--show-current"),
            "head": _git_read(path, "rev-parse", "HEAD"),
            "main": _ref(path, "refs/heads/main"),
            "target": _ref(path, f"refs/heads/{context['branch']}"),
            "dirty": _git_read(path, "status", "--porcelain=v1", "--untracked-files=all") != "",
        })
    return facts


def _verify_boundary(context: dict[str, Any], facts: list[dict[str, Any]]) -> None:
    for fact in facts:
        name, path = fact["name"], fact["path"]
        base = context["bases"][name]
        _require(fact["branch"] == context["branch"], f"权威仓库 {name}: 当前分支不是统一需求分支")
        _require(
            all(_is_sha(value) for value in (fact["head"], fact["main"], fact["target"])),
            f"权威仓库 {name}: HEAD、main 或 target 引用不符合约定",
        )
        _require(fact["target"] == fact["head"], f"权威仓库 {name}: target 与 HEAD 不一致")
        try:
            base_before_main = _git(
                path, "merge-base", "--is-ancestor", base, fact["main"], allowed=(0, 1)
            ).returncode == 0
            main_before_head = _git(
                path, "merge-base", "--is-ancestor", fact["main"], fact["head"], allowed=(0, 1)
            ).returncode == 0
        except RuntimeError as error:
            raise RuntimeError(f"权威仓库 {name}: 无法校验 base、main 与 HEAD 的祖先关系") from error
        _require(base_before_main, f"权威仓库 {name}: base 不是 main 的祖先")
        _require(main_before_head, f"权威仓库 {name}: main 不是 HEAD 的祖先")
        current = {
            "branch": _git_read(path, "branch", "--show-current"),
            "head": _git_read(path, "rev-parse", "HEAD"),
            "main": _ref(path, "refs/heads/main"),
            "target": _ref(path, f"refs/heads/{context['branch']}"),
        }
        _require(
            all(current[key] == fact[key] for key in current),
            f"权威仓库 {name}: Git 引用在边界检查期间发生变化",
        )


def _repository_results(context: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": fact["name"], "path": "." if fact["name"] == "root" else fact["name"], "base_sha": context["bases"][fact["name"]], "tip_sha": fact["head"]} for fact in facts]


def _completion_repair(context: dict[str, Any]) -> str | None:
    facts = _facts(context)
    _verify_boundary(context, facts)
    return REPOSITORY_REPAIR_PROMPT if any(fact["dirty"] for fact in facts) else None


def initial_prompt(context: dict[str, Any]) -> str:
    repositories = "\n".join(f"- {item['name']}: `{'.' if item['name'] == 'root' else item['name']}`" for item in context["repositories"])
    return f"""/commit-changes
请提交当前已验收需求的变更，不重新开发或验收。

需求：`{context['requirement_id']} {context['title']}`
统一需求分支：`{context['branch']}`
有序权威仓库：
{repositories}

仅在上述白名单仓库和统一需求分支创建本地提交；不得切换或创建分支、merge、rebase、改写历史或 push。"""


def _fresh_success(
    run_dir: Path, state: dict[str, Any], context: dict[str, Any], facts: list[dict[str, Any]]
) -> dict[str, Any]:
    success = result(
        "success",
        "权威仓库没有待提交变更，未制造空提交。",
        requirement_id=context["requirement_id"],
        branch=context["branch"],
        repositories=_repository_results(context, facts),
    )
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, context, success)


def _saved_result(run_dir: Path, requirement_id: str) -> dict[str, Any] | None:
    path = requirement_step_result_path(run_dir, requirement_id, STEP)
    return None if not path.exists() else _read_json(path, "需求提交结果不可读取")


def _validate_success(saved: Any, context: dict[str, Any], *, advanced: bool) -> dict[str, Any]:
    _require(_valid_result(saved, step=STEP, name=NAME, requirement_id=context["requirement_id"], fields=_RESULT_FIELDS) and saved.get("branch") == context["branch"] and isinstance(saved.get("repositories"), list) and len(saved["repositories"]) == len(context["names"]), "需求提交完整成功结果不符合约定")
    for name, repository in zip(context["names"], saved["repositories"], strict=True):
        _require(isinstance(repository, dict) and set(repository) == {"name", "path", "base_sha", "tip_sha"} and repository.get("name") == name and repository.get("path") == ("." if name == "root" else name) and repository.get("base_sha") == context["bases"][name] and _is_sha(repository.get("tip_sha")) and (not advanced or repository["tip_sha"] == context["tips"][name]), "需求提交仓库结果不符合约定")
    return saved


def _complete_facts(context: dict[str, Any], saved: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    facts = _facts(context)
    _verify_boundary(context, facts)
    for index, fact in enumerate(facts):
        _require(not fact["dirty"], f"权威仓库 {fact['name']}: 仍有未提交变更")
        _require(
            saved is None or _repository_results(context, [fact])[0] == saved["repositories"][index],
            f"权威仓库 {fact['name']}: 需求提交结果与当前 Git 事实不一致",
        )
    return facts


def _execution_scene(
    run_dir: Path,
    state: dict[str, Any],
    context: dict[str, Any],
    spec: AgentDecisionLoopSpec,
) -> bool:
    sessions = state.get("claude_sessions")
    if (
        isinstance(sessions, dict)
        and sessions.get(context["key"]) == context["development_session_id"]
    ):
        raise RuntimeError(
            "需求提交仍使用旧开发 session 别名，需要先显式迁移为独立提交 session"
        )
    return validate_agent_decision_loop_scene(run_dir, state, spec)


def _decision_spec(context: dict[str, Any]) -> AgentDecisionLoopSpec:
    repositories = [
        {
            "name": repository["name"],
            "path": "." if repository["name"] == "root" else repository["name"],
        }
        for repository in context["repositories"]
    ]
    return AgentDecisionLoopSpec(
        key=context["key"],
        state_key=context["key"],
        skill_name=SKILL_NAME,
        max_decision_rounds=MAX_DECISION_ROUNDS,
        max_turns=COMMIT_MAX_TURNS,
        task="requirement_commit",
        decision_system_prompt=render_decision_system_prompt(
            REQUIREMENT_COMMIT_DECISION_RULES,
            {
                "当前需求": {
                    "id": context["requirement_id"],
                    "title": context["title"],
                    "branch": context["branch"],
                },
                "有序权威仓库": repositories,
            },
        ),
    )


def _record_blocked(
    run_dir: Path, state: dict[str, Any], context: dict[str, Any], reason: str, required_inputs: list[str]
) -> None:
    blocked = {"reason": reason, "required_inputs": required_inputs}
    write_requirement_step_result(
        run_dir,
        context["requirement_id"],
        STEP,
        result("blocked", reason, requirement_id=context["requirement_id"], branch=context["branch"], blocked=blocked),
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


def _running(run_dir: Path, state: dict[str, Any]) -> None:
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


def _advance(run_dir: Path, state: dict[str, Any], context: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    context["cycle"]["repositories"] = {
        item["name"]: {
            "base_sha": item["base_sha"],
            "tip_sha": item["tip_sha"],
            "merged": False,
        }
        for item in saved["repositories"]
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
        context = _context(run_dir, state, advanced=advanced)
        saved = _validate_success(_saved_result(run_dir, context["requirement_id"]), context, advanced=advanced)
        if not advanced:
            _complete_facts(context, saved)
    except (RuntimeError, TypeError, ValueError):
        return False
    return True


def failure_scope(_run_dir: Path, state: dict[str, Any]) -> dict[str, str] | None:
    if state.get("phase") != PHASE or _position(state) != (STEP, STEP, CURRENT_NODE):
        return None
    try:
        requirement_id, _title, cycle = _active(state, require_title=False)
    except (RuntimeError, TypeError, ValueError):
        return None
    return {"requirement_id": requirement_id, "branch": cycle["branch"]}


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
    resume_message: ResumeMessage | None = None,
) -> dict[str, Any]:
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

    spec = _decision_spec(context)
    scene = _execution_scene(run_dir, state, context, spec)
    facts = _facts(context)
    _verify_boundary(context, facts)
    if not scene and not any(fact["dirty"] for fact in facts):
        return _fresh_success(run_dir, state, context, facts)
    if state.get("status") != "blocked":
        _running(run_dir, state)

    decision = await run_agent_decision_loop(
        run_dir, state, context["workspace"], spec, initial_prompt(context),
        lambda: _completion_repair(context), agent_runner=agent_runner,
        decision_runner=decision_runner, config_loader=config_loader,
        resume_message=resume_message,
    )
    if decision.verdict == "blocked":
        _record_blocked(run_dir, state, context, decision.reason, decision.required_inputs)
        raise RequirementCommitBlocked(decision.reason, decision.required_inputs, requirement_id=context["requirement_id"], branch=context["branch"])
    _require(decision.verdict == "completed", "需求提交决策不符合约定")
    facts = _complete_facts(context)
    success = result("success", "已在权威仓库完成当前需求变更的本地提交并核验 Git 事实。", requirement_id=context["requirement_id"], branch=context["branch"], repositories=_repository_results(context, facts))
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, context, success)
