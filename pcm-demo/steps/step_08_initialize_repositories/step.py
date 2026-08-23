from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.state import write_state, write_step_result
from config import LLMConfig
from steps.step_01_create_workspace.workspace import git, inspect_repository
from steps.step_04_assemble_foundation.step import (
    load_selection,
    temporary_root,
    verify_existing_assembly,
)
from steps.step_06_project_bootstrap.step import (
    coverage_artifact_repair,
    load_assembly,
    verify_existing_bootstrap_success,
)
from steps.step_07_solution_design.step import (
    DESIGN_PATH,
    design_present,
    verify_existing_solution_success,
)

STEP = 8
NAME = "首次提交适用仓库"
CURRENT_NODE = "project:08_initialize_repositories"
NEXT_NODE = "project:09_engineering_architecture"
CONVERSATION_KEY = "initialize_repositories"
SKILL_NAME = "commit-changes"
MAX_DECISION_ROUNDS = 8
INITIALIZE_REPOSITORIES_MAX_TURNS = 48
INITIALIZE_REPOSITORIES_MAX_BUDGET_USD = 16.0
SHA_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
INITIAL_COMMITS_PREFIX = "INITIAL_COMMITS_JSON="
INITIAL_COMMITS_REPAIR_PROMPT = (
    "请重新核验权威仓库清单。仍未创建初始基线提交的仓库应按既定约束完成提交；"
    "不得改写已有提交或修改文件来规避核验。最终回复最后一个非空行必须严格为 "
    "INITIAL_COMMITS_JSON={\"repositories\":[{\"name\":\"root\",\"sha\":\"完整SHA\"},...]}，"
    "其中仓库名称和顺序必须与权威清单完全一致。"
)

INITIALIZE_REPOSITORIES_DECISION_RULES = """- completed：权威仓库清单中的每个独立仓库均已有恰好一个无父提交的初始基线提交，工作区干净，根仓未纳入子仓或 gitlink，且最终回复最后一个非空行给出了完整、严格的 INITIAL_COMMITS_JSON 声明。
- continue：提交、核验或最终声明尚不完整，但可继续使用当前项目事实完成。
- blocked：只能用于缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务、合法 Git 作者身份、强制签名凭据或线下动作。

Agent 请求可由当前项目事实和既定约束决定的确认或授权时，你必须直接在 answer 中作出明确决定，不得要求另一个调用方再提供授权文本；也不得授权修改工作树、改写历史或绕过检查来完成提交。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key="initialize_repositories",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=INITIALIZE_REPOSITORIES_MAX_TURNS,
    max_budget_usd=INITIALIZE_REPOSITORIES_MAX_BUDGET_USD,
    decision_system_prompt=render_decision_system_prompt(
        INITIALIZE_REPOSITORIES_DECISION_RULES, {}
    ),
)


class InitialCommitEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    sha: str = Field(pattern=SHA_PATTERN)


class InitialCommitsMarker(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    repositories: list[InitialCommitEntry] = Field(min_length=1)


class InitializeRepositoriesBlocked(RuntimeError):
    def __init__(
        self, reason: str, required_inputs: list[str], applicable_repositories: list[str]
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.required_inputs = required_inputs
        self.applicable_repositories = applicable_repositories


def result(
    status: str,
    summary: str,
    *,
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    applicable_repositories: list[str] | None = None,
    initial_commits: dict[str, str] | None = None,
    repositories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    saved: dict[str, Any] = {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": [],
        "blocked": blocked,
        "error": error,
    }
    if status == "success":
        saved.update(
            {
                "applicable_repositories": applicable_repositories or [],
                "initial_commits": initial_commits or {},
                "repositories": repositories or [],
            }
        )
    return saved


def _root_repository_evidence(workspace: Path, state: dict[str, Any]) -> None:
    expected = {"path": str(workspace.resolve()), "branch": "main", "head": None}
    if state.get("root_repository") != expected:
        raise RuntimeError("产品根 Git 初始化证据与运行状态不一致")


def _workspace_from_state(state: dict[str, Any]) -> Path:
    try:
        workspace = Path(state["workspace"]["final_path"]).resolve()
        root = Path(state["workspace"]["root"]).resolve()
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    if workspace.parent != root or workspace.is_symlink() or not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    _root_repository_evidence(workspace, state)
    return workspace


def _applicable_repositories(outputs: list[str]) -> list[str]:
    if any(not isinstance(output, str) or output not in {"frontend", "backend"} for output in outputs):
        raise RuntimeError("第 4 步适用工程目录不符合约定")
    if len(set(outputs)) != len(outputs):
        raise RuntimeError("第 4 步适用工程目录重复")
    return ["root", *outputs]


def validate_inputs(run_dir: Path, state: dict[str, Any]) -> tuple[Path, dict[str, Any], list[str]]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于仓库初始化锚点")
    workspace = _workspace_from_state(state)
    selection = load_selection(run_dir)
    assembly = load_assembly(run_dir)
    verify_existing_assembly(
        workspace,
        selection,
        assembly,
        temporary_root(workspace, str(state.get("run_id", ""))),
    )
    outputs = assembly.get("outputs")
    if not isinstance(outputs, list):
        raise RuntimeError("第 4 步适用工程目录不符合约定")
    names = _applicable_repositories(outputs)
    verify_existing_bootstrap_success(run_dir, outputs)
    verify_existing_solution_success(run_dir)
    if not design_present(workspace):
        raise RuntimeError("第 7 步总体技术方案不存在或为空")
    return workspace, assembly, names


def _repository_path(workspace: Path, name: str) -> Path:
    return workspace if name == "root" else workspace / name


def _head(path: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
            cwd=path,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if completed.returncode == 1:
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("无法读取 Git HEAD")
    return completed.stdout.strip()


def _repository_snapshot(path: Path, *, require_clean_index: bool) -> dict[str, str | None]:
    head = _head(path)
    return inspect_repository(
        path,
        expected_head="present" if head else "unborn",
        require_clean_index=require_clean_index,
    )


def _require_clean_worktree(path: Path) -> None:
    if git("status", "--porcelain", cwd=path):
        raise RuntimeError("已有初始提交的 Git 仓库工作区或暂存区不干净")


def _require_single_initial_commit(path: Path) -> str:
    snapshot = _repository_snapshot(path, require_clean_index=True)
    head = snapshot["head"]
    if head is None:
        raise RuntimeError("Git 仓库尚未创建初始提交")
    _require_clean_worktree(path)
    shallow = Path(git("rev-parse", "--git-path", "shallow", cwd=path))
    if not shallow.is_absolute():
        shallow = path / shallow
    if shallow.exists() or shallow.is_symlink():
        raise RuntimeError("Git 仓库不得使用浅历史作为初始基线")
    if git("for-each-ref", "--format=%(refname)", "refs/replace", cwd=path):
        raise RuntimeError("Git 仓库不得使用 replace 引用改写初始基线")
    if git("--no-replace-objects", "rev-list", "--count", "HEAD", cwd=path) != "1":
        raise RuntimeError("Git 仓库必须恰好包含一个初始基线提交")
    headers = git("--no-replace-objects", "cat-file", "-p", "HEAD", cwd=path).partition("\n\n")[0]
    if any(line.startswith("parent ") for line in headers.splitlines()):
        raise RuntimeError("Git 初始基线提交不得包含父提交或合并历史")
    return head


def _require_root_tree_boundary(workspace: Path) -> None:
    for args in (
        ("ls-tree", "HEAD", "--", "frontend", "backend"),
        ("ls-tree", "-r", "--name-only", "HEAD", "--", "frontend", "backend"),
    ):
        if git(*args, cwd=workspace):
            raise RuntimeError("根仓初始提交不得纳入 frontend、backend 或 gitlink")


def _completed_facts(workspace: Path, names: list[str]) -> dict[str, str]:
    commits: dict[str, str] = {}
    for name in names:
        path = _repository_path(workspace, name)
        commits[name] = _require_single_initial_commit(path)
    _require_root_tree_boundary(workspace)
    _root_ignores_children(workspace, names)
    return commits


def _ensure_initial_repositories(workspace: Path, names: list[str]) -> None:
    for name in names:
        inspect_repository(
            _repository_path(workspace, name), expected_head="unborn", require_clean_index=True
        )


def _validate_resumable_repositories(workspace: Path, names: list[str]) -> None:
    for name in names:
        path = _repository_path(workspace, name)
        if _head(path) is None:
            _repository_snapshot(path, require_clean_index=False)
        else:
            _require_single_initial_commit(path)
    if _head(workspace) is not None:
        _require_root_tree_boundary(workspace)


def _root_ignores_children(workspace: Path, names: list[str]) -> None:
    children = [name for name in names if name != "root"]
    if not children:
        return
    ignore_file = workspace / ".gitignore"
    if ignore_file.is_symlink() or not ignore_file.is_file():
        raise RuntimeError("产品根 .gitignore 必须忽略每个适用子仓路径")
    for child in children:
        try:
            matched = git("check-ignore", "--no-index", "-v", "--", child, cwd=workspace)
        except RuntimeError as error:
            raise RuntimeError("产品根 .gitignore 必须忽略每个适用子仓路径") from error
        source = matched.split("\t", 1)[0].split(":", 1)[0]
        if source not in {".gitignore", "./.gitignore"}:
            raise RuntimeError("产品根 .gitignore 必须忽略每个适用子仓路径")


def _latest_agent_text(run_dir: Path) -> str:
    try:
        conversation = json.loads(
            (run_dir / "conversations" / f"{CONVERSATION_KEY}.json").read_text(encoding="utf-8")
        )
        messages = conversation["messages"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError("仓库初始化对话记录不可读取") from error
    if not isinstance(messages, list):
        raise RuntimeError("仓库初始化对话记录不符合约定")
    for message in reversed(messages):
        if (
            isinstance(message, dict)
            and message.get("role") == "user"
            and isinstance(message.get("content"), str)
        ):
            return message["content"]
    raise RuntimeError("仓库初始化对话缺少 Agent 最终回复")


def _parse_marker(text: str, names: list[str]) -> dict[str, str]:
    nonempty_lines = [line for line in text.splitlines() if line.strip()]
    if not nonempty_lines:
        raise ValueError("Agent 最终回复缺少初始提交声明")
    line = nonempty_lines[-1]
    if not line.startswith(INITIAL_COMMITS_PREFIX):
        raise ValueError("Agent 最终回复末行不是初始提交声明")
    raw = line.removeprefix(INITIAL_COMMITS_PREFIX)
    if not raw.startswith("{") or not raw.endswith("}"):
        raise ValueError("初始提交声明格式无效")
    try:
        data = json.loads(raw)
        marker = InitialCommitsMarker.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as error:
        raise ValueError("初始提交声明格式无效") from error
    entries = marker.repositories
    if [entry.name for entry in entries] != names:
        raise ValueError("初始提交声明的仓库集合或顺序不一致")
    return {entry.name: entry.sha for entry in entries}


def _result_repositories(workspace: Path, names: list[str], commits: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "path": "." if name == "root" else name,
            "branch": "main",
            "head": commits[name],
            "worktree_clean": True,
        }
        for name in names
    ]


def _state_repositories(workspace: Path, names: list[str], commits: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "path": str(_repository_path(workspace, name).resolve()),
            "branch": "main",
            "head": commits[name],
            "worktree_clean": True,
        }
        for name in names
    ]


def _has_success_result(path: Path) -> bool:
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(existing, dict) and existing.get("status") == "success"


def verify_existing_success(
    run_dir: Path, state: dict[str, Any], workspace: Path, names: list[str]
) -> tuple[dict[str, Any], dict[str, str]]:
    try:
        existing = json.loads((run_dir / "steps" / "08.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 8 步成功结果不可读取") from error
    commits = _completed_facts(workspace, names)
    expected_repositories = _result_repositories(workspace, names, commits)
    if (
        existing.get("step") != STEP
        or existing.get("status") != "success"
        or existing.get("applicable") is not True
        or existing.get("outputs") != []
        or existing.get("applicable_repositories") != names
        or existing.get("initial_commits") != commits
        or existing.get("repositories") != expected_repositories
        or existing.get("blocked") is not None
        or existing.get("error") is not None
    ):
        raise RuntimeError("第 8 步成功结果不可复用")
    if (state.get("step"), state.get("current_step"), state.get("current_node")) == (
        STEP + 1,
        STEP + 1,
        NEXT_NODE,
    ) and (
        state.get("applicable_repositories") != names
        or state.get("initial_commits") != commits
        or state.get("repositories") != _state_repositories(workspace, names, commits)
    ):
        raise RuntimeError("第 8 步成功状态不可复用")
    return existing, commits


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    workspace: Path,
    names: list[str],
    commits: dict[str, str],
) -> dict[str, Any]:
    saved = result(
        "success",
        "已为产品根和适用基础工程分别创建唯一初始基线提交。",
        applicable_repositories=names,
        initial_commits=commits,
        repositories=_result_repositories(workspace, names, commits),
    )
    write_step_result(run_dir, STEP, saved)
    state.update(
        {
            "status": "success",
            "phase": "project_initialization",
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "applicable_repositories": names,
            "initial_commits": commits,
            "repositories": _state_repositories(workspace, names, commits),
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return saved


def prompt_assembly(assembly: dict[str, Any]) -> dict[str, Any]:
    visible: dict[str, Any] = {}
    for target, entry in (assembly.get("assembly") or {}).items():
        if entry is None:
            visible[target] = None
        elif isinstance(entry, dict):
            visible[target] = {
                key: entry.get(key)
                for key in ("target", "id", "default_branch", "path", "branch", "commit_sha")
            }
        else:
            raise RuntimeError("第 4 步组装来源不符合约定")
    return visible


def initial_prompt(assembly: dict[str, Any], names: list[str]) -> str:
    repository_lines = "\n".join(
        f"- {name}: @./{'.' if name == 'root' else name}" for name in names
    )
    assembly_json = json.dumps(prompt_assembly(assembly), ensure_ascii=False, indent=2)
    return f"""/commit-changes
调用方已授权你直接完成当前产品的初始基线提交。

权威仓库清单（集合和顺序均不可改变）：
{repository_lines}

组装事实：
```json
{assembly_json}
```

请在同一任务中，对清单中每个彼此独立的仓库分别完整执行 commit-changes 的单仓合同，并以 `expected_head=unborn` 核验提交基线。每个仓库当前全部合法变更必须作为该仓唯一的初始基线结果提交；根仓只可提交根拥有的内容，不能包含 frontend、backend 或任何 gitlink。

不得创建或切换分支、merge、amend、reset、rebase、push；不得修改文件来通过检查；不得将多个仓库混为一次提交；不得泄露秘密。完成后核验每仓均在 main、工作区干净且只有一个无父提交。最终完整回复可先给出摘要，但最后一个非空行必须严格为 INITIAL_COMMITS_JSON={{"repositories":[{{"name":"root","sha":"完整SHA"}},...]}}，其中每个 sha 为完整 SHA，仓库集合和顺序必须与权威清单完全一致。"""


def _has_session(state: dict[str, Any]) -> bool:
    sessions = state.get("claude_sessions")
    if sessions is None:
        return False
    if not isinstance(sessions, dict):
        raise RuntimeError("Claude session 状态不符合约定")
    value = sessions.get(CONVERSATION_KEY)
    if value is None:
        return False
    if not isinstance(value, str) or not value:
        raise RuntimeError("Claude session ID 不符合约定")
    return True


def _observed_heads(workspace: Path, names: list[str]) -> dict[str, str | None]:
    return {name: _head(_repository_path(workspace, name)) for name in names}


def _initialize_observed_heads(
    run_dir: Path, state: dict[str, Any], names: list[str]
) -> None:
    section = state.setdefault(DECISION_LOOP_SPEC.state_key, {})
    if not isinstance(section, dict):
        raise RuntimeError("仓库初始化运行状态不符合约定")
    section["observed_heads"] = {name: None for name in names}
    write_state(run_dir, state)


def _require_observed_heads(workspace: Path, state: dict[str, Any], names: list[str]) -> None:
    section = state.get(DECISION_LOOP_SPEC.state_key)
    if not isinstance(section, dict):
        raise RuntimeError("仓库初始化缺少最近 Agent 回合的提交记录")
    observed = section.get("observed_heads")
    if (
        not isinstance(observed, dict)
        or set(observed) != set(names)
        or any(value is not None and not isinstance(value, str) for value in observed.values())
    ):
        raise RuntimeError("仓库初始化缺少最近 Agent 回合的提交记录")
    if observed != _observed_heads(workspace, names):
        raise RuntimeError("Git HEAD 与最近 Agent 回合记录不一致")


def _observing_agent_runner(
    run_dir: Path,
    state: dict[str, Any],
    workspace: Path,
    names: list[str],
    agent_runner: Any,
):
    async def runner(*args: Any, **kwargs: Any) -> Any:
        value = await agent_runner(*args, **kwargs)
        if isinstance(value, ClaudeRunResult) and value.result_subtype is not None:
            section = state.setdefault(DECISION_LOOP_SPEC.state_key, {})
            if not isinstance(section, dict):
                raise RuntimeError("仓库初始化运行状态不符合约定")
            section["observed_heads"] = _observed_heads(workspace, names)
            write_state(run_dir, state)
        return value

    return runner


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    workspace, assembly, names = validate_inputs(run_dir, state)
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        existing, _ = verify_existing_success(run_dir, state, workspace, names)
        return existing
    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于仓库初始化锚点")

    result_path = run_dir / "steps" / "08.json"
    if result_path.is_file() and _has_success_result(result_path):
        _, commits = verify_existing_success(run_dir, state, workspace, names)
        return advance_success(run_dir, state, workspace, names, commits)

    coverage_repair = coverage_artifact_repair(workspace, names[1:])
    if coverage_repair is not None:
        raise RuntimeError("基础工程仍包含未删除或未忽略的 .coverage 覆盖率数据库")
    if _has_session(state):
        _validate_resumable_repositories(workspace, names)
        _require_observed_heads(workspace, state, names)
    else:
        _ensure_initial_repositories(workspace, names)
        _initialize_observed_heads(run_dir, state, names)
    _root_ignores_children(workspace, names)

    if state.get("status") != "blocked":
        state.update({"current_step": STEP, "status": "running", "blocked": None, "error": None})
        write_state(run_dir, state)

    def completion_verifier() -> str | None:
        verified_workspace, _, verified_names = validate_inputs(run_dir, state)
        has_unborn = False
        for name in verified_names:
            path = _repository_path(verified_workspace, name)
            if _head(path) is None:
                _repository_snapshot(path, require_clean_index=False)
                has_unborn = True
        if has_unborn:
            _validate_resumable_repositories(verified_workspace, verified_names)
            return INITIAL_COMMITS_REPAIR_PROMPT
        commits = _completed_facts(verified_workspace, verified_names)
        try:
            declared = _parse_marker(_latest_agent_text(run_dir), verified_names)
        except ValueError:
            return INITIAL_COMMITS_REPAIR_PROMPT
        return None if declared == commits else INITIAL_COMMITS_REPAIR_PROMPT

    decision_spec = replace(
        DECISION_LOOP_SPEC,
        decision_system_prompt=render_decision_system_prompt(
            INITIALIZE_REPOSITORIES_DECISION_RULES,
            {
                "有序仓库": [
                    {"name": name, "path": "." if name == "root" else name}
                    for name in names
                ],
                "组装白名单事实": prompt_assembly(assembly),
                "初始仓库基线": (
                    "每个独立仓库使用 main；初始基线完成条件是每仓只有一个无父提交，"
                    "工作区保持干净，根仓不包含子仓。"
                ),
            },
        ),
    )
    decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        decision_spec,
        initial_prompt(assembly, names),
        completion_verifier,
        agent_runner=_observing_agent_runner(run_dir, state, workspace, names, agent_runner),
        decision_runner=decision_runner,
        config_loader=config_loader,
    )
    if decision.verdict == "blocked":
        _require_observed_heads(workspace, state, names)
        _validate_resumable_repositories(workspace, names)
        _root_ignores_children(workspace, names)
        if coverage_artifact_repair(workspace, names[1:]) is not None:
            raise RuntimeError("基础工程仍包含未删除或未忽略的 .coverage 覆盖率数据库")
        blocked = {
            "reason": decision.reason,
            "required_inputs": decision.required_inputs,
            "applicable_repositories": names,
        }
        state.update(
            {
                "status": "blocked",
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": blocked,
                "error": None,
            }
        )
        write_state(run_dir, state)
        raise InitializeRepositoriesBlocked(decision.reason, decision.required_inputs, names)
    commits = _completed_facts(workspace, names)
    return advance_success(run_dir, state, workspace, names, commits)
