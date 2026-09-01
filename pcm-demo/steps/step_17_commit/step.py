from __future__ import annotations

import json
import os
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
MAX_DECISION_ROUNDS = 3
MAX_TURNS = 48
REPOSITORY_REPAIR_PROMPT = (
    "白名单仓库仍有未提交的定稿输入。不要重新开发或重新验收。"
    "只读取剩余的 Git status 和 diff，确认提交范围、真实秘密与意外文件，"
    "然后精确暂存、创建必要的本地提交并执行提交后 Git 核验。"
    "不得实现或修复代码、文档或测试，不得格式化、补充或执行测试，不得运行 lint、build、"
    "服务、浏览器、安全审查或代码审查；不得创建或修改 .gitignore，不得删除、移动、忽略或丢弃文件。"
    "若现有内容不能原样安全提交，停止并报告具体仓库、路径和原因。"
)
REQUIREMENT_COMMIT_DECISION_RULES = """- completed：只根据当前 Git 提交结果判断。白名单内已有需求变更均已完成必要的本地提交或原本无变更；每个仓库仍位于统一需求分支，且工作区和暂存区干净。不得重新判断实现正确性、测试充分性、安全设计或产品验收。
- continue：仅当仍可在不修改、删除、格式化或重新生成任何文件内容的前提下，通过读取 Git 状态和 diff、确认提交范围、精确暂存、创建本地提交或核验提交结果完成当前工作时使用。answer 只能包含这些 Git 提交动作。
- blocked：仅用于缺少合法 Git 作者身份、强制签名凭据、外部授权，或现有变更因真实秘密、范围归属冲突等原因无法在不修改内容的情况下安全提交。需要修改实现、文档、测试或生成物时，required_inputs 必须明确要求交由实现与验证任务处理，当前提交任务不得修改内容。

当前需求的实现、适用测试、真实验证、审查与规则复盘均已完成，这是不可重新打开的权威事实。不得实现或修复功能、修改文档、格式化文件、补充或执行测试、运行 lint 或 build、启动服务、进行浏览器验收、安全审查、代码审查或重新验收；不得创建或修改 .gitignore，也不得删除、移动、忽略或丢弃文件来获得 clean 状态。

不得授权扩大白名单、切换或创建分支、merge、rebase、reset、amend、改写历史、绕过检查或 push。"""
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


def _completion_repair(context: dict[str, Any]) -> str | None:
    facts = _facts(context)
    _verify_boundary(context, facts, fresh=False)
    return REPOSITORY_REPAIR_PROMPT if any(fact["dirty"] for fact in facts) else None


def initial_prompt(context: dict[str, Any]) -> str:
    repositories = "\n".join(f"- {item['name']}: `{'.' if item['name'] == 'root' else item['name']}`" for item in context["repositories"])
    return f"""/commit-changes
请提交当前需求 `{context['requirement_id']} {context['title']}` 已完成并验证的已有变更。

当前需求的实现、适用测试、真实验证、审查与规则复盘均已完成。当前工作树中的需求变更是定稿提交输入，不得重新打开实现或验收结论。

统一需求分支：`{context['branch']}`
适用仓库白名单（集合和顺序均不可扩大）：
{repositories}

只在白名单内的独立仓库处理已有 dirty 变更；clean 仓库不提交且不制造空提交。只为确认仓库边界、提交分组、文件归属、真实秘密和意外范围读取 Git 状态、完整 diff 及必要候选文件内容，然后精确暂存、创建本地提交并核验提交后的 Git 状态。

不得实现或修复代码、文档或测试，不得格式化文件、补充或执行测试，不得运行 lint、build、服务、浏览器、安全审查或代码审查；不得创建或修改 `.gitignore`，不得删除、移动、忽略或丢弃文件来让检查通过。不得处理白名单外仓库，不得创建或切换分支、merge、rebase、reset、amend、改写历史、绕过 hook 或 push。

若现有内容不能在上述边界内原样安全提交，停止并报告具体仓库、路径和原因。完成后确保每个白名单仓库仍在统一需求分支，且 `git status --porcelain` 为空。"""


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
    _verify_boundary(context, facts, fresh=False)
    _require(not any(fact["dirty"] for fact in facts), "白名单仓库仍有未提交变更")
    _require(saved is None or _repository_results(context, facts) == saved["repositories"], "需求提交结果与当前 Git 事实不一致")
    return facts


def _execution_scene(run_dir: Path, state: dict[str, Any], context: dict[str, Any]) -> bool:
    key, expected = context["key"], f"conversations/{context['key']}.json"
    sessions, references = state.get("claude_sessions"), state.get("decision_conversations")
    _require(sessions is None or isinstance(sessions, dict), "Claude session 状态不符合约定")
    _require(references is None or isinstance(references, dict), "决策历史引用不符合约定")
    conversation = run_dir / expected
    session_present = isinstance(sessions, dict) and key in sessions
    reference_present = isinstance(references, dict) and key in references
    started = key in state or session_present or reference_present or conversation.exists() or conversation.is_symlink() or state.get("status") == "blocked"
    if not started:
        return False
    session = sessions.get(key) if isinstance(sessions, dict) else None
    reference = references.get(key) if isinstance(references, dict) else None
    _require(isinstance(reference, dict) and reference.get("path") == expected, "需求提交恢复缺少原决策历史引用")
    _require(not conversation.is_symlink() and conversation.is_file(), "需求提交恢复缺少原决策历史")
    if session is None:
        _require(state.get("status") != "blocked", "需求提交恢复缺少原 Claude session")
        saved = _read_json(conversation, "需求提交恢复缺少原决策历史")
        messages = saved.get("messages")
        section = state.get(key)
        _require(
            isinstance(messages, list)
            and messages == [
                {"role": "system", "content": _decision_spec(context).decision_system_prompt},
                {"role": "assistant", "content": initial_prompt(context)},
            ]
            and (
                section is None
                or isinstance(section, dict)
                and "pending_agent_text" not in section
                and (
                    "last_agent_result" not in section
                    or isinstance(section["last_agent_result"], dict)
                    and not section["last_agent_result"].get("session_id")
                )
            ),
            "需求提交恢复缺少原 Claude session",
        )
        return True
    _require(isinstance(session, str) and bool(session), "需求提交恢复缺少原 Claude session")
    return True


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
        max_turns=MAX_TURNS,
        decision_system_prompt=render_decision_system_prompt(
            REQUIREMENT_COMMIT_DECISION_RULES,
            {
                "当前需求": {
                    "id": context["requirement_id"],
                    "title": context["title"],
                    "branch": context["branch"],
                },
                "既有完成事实": {
                    "实现与验证": "当前需求的实现、适用测试、真实验证和审查已经完成。",
                    "规则复盘": "当前需求的规则复盘已经完成。",
                    "当前任务": "只提交现有定稿变更，不重新开发或重新验收。",
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

    scene = _execution_scene(run_dir, state, context)
    facts = _facts(context)
    _verify_boundary(context, facts, fresh=not scene)
    if not scene and not any(fact["dirty"] for fact in facts):
        return _fresh_success(run_dir, state, context, facts)
    if state.get("status") != "blocked":
        _running(run_dir, state)

    spec = _decision_spec(context)
    decision = await run_agent_decision_loop(
        run_dir, state, context["workspace"], spec, initial_prompt(context),
        lambda: _completion_repair(context), agent_runner=agent_runner,
        decision_runner=decision_runner, config_loader=config_loader,
    )
    if decision.verdict == "blocked":
        _record_blocked(run_dir, state, context, decision.reason, decision.required_inputs)
        raise RequirementCommitBlocked(decision.reason, decision.required_inputs, requirement_id=context["requirement_id"], branch=context["branch"])
    _require(decision.verdict == "completed", "需求提交决策不符合约定")
    facts = _complete_facts(context)
    success = result("success", "已在权威仓库完成当前需求变更的本地提交并核验 Git 事实。", requirement_id=context["requirement_id"], branch=context["branch"], repositories=_repository_results(context, facts))
    write_requirement_step_result(run_dir, context["requirement_id"], STEP, success)
    return _advance(run_dir, state, context, success)
