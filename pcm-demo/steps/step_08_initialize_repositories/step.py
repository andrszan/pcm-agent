from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, ResumeMessage, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import parse_agent_decision, render_decision_system_prompt, request_decision
from common.files import write_json
from common.state import write_state, write_step_result
from config import LLMConfig

STEP = 8
NAME = "首次提交适用仓库"
CURRENT_NODE = "project:08_initialize_repositories"
NEXT_NODE = "project:09_engineering_architecture"
CONVERSATION_KEY = "initialize_repositories"
SKILL_NAME = "commit-changes"
MAX_DECISION_ROUNDS = 32
INITIALIZE_REPOSITORIES_MAX_TURNS = 9999
REPOSITORY_REPAIR_PROMPT = "请只处理权威仓库清单中的未提交变更；工作区根从权威能力模板取得的 `.agents/`、`.claude/` 和 `plugins-lock.json` 是已定稿的只读提交输入，只可读取、核对 Git 状态、精确暂存并原样提交，不得创建、修改、删除、移动、格式化、清理、忽略或重写；除可确认的真实秘密或凭据外，不得因版本、许可证、测试产物判断或权限安全偏好要求修复或阻塞，其中 `.claude/settings.json` 的无人值守权限合同必须原样保留，不得收紧为交互授权模式；完成后重新核验每个仓库的工作区和暂存区均干净。"

INITIALIZE_REPOSITORIES_DECISION_RULES = """- completed：权威仓库清单中的每个独立仓库均处于 main 分支，且工作区和暂存区干净。
- continue：仍有可在当前项目中完成的仓库变更或核验工作。
- blocked：只能用于缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务、合法 Git 作者身份、强制签名凭据或线下动作。
- 工作区根从权威能力模板取得的 `.agents/`、`.claude/` 和 `plugins-lock.json` 是已定稿的只读提交输入，只可读取、核对 Git 状态、精确暂存并原样提交，不得创建、修改、删除、移动、格式化、清理、忽略或重写；除可确认的真实秘密或凭据外，不得因版本、许可证、测试产物判断或权限安全偏好要求修复或阻塞，其中 `.claude/settings.json` 的无人值守权限合同必须原样保留，不得收紧为交互授权模式或视为缺少外部授权。

Agent 请求可由当前项目事实和既定约束决定的确认或授权时，你必须直接在 answer 中作出明确决定；但不得授权改写历史、切换分支或绕过检查。"""

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
                "repositories": repositories or [],
            }
        )
    return saved


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
    if not root.is_absolute() or not workspace.is_absolute():
        raise RuntimeError("工作区状态路径必须为绝对路径")
    if workspace.is_symlink():
        raise RuntimeError("产品工作区不得是符号链接")
    root = root.resolve()
    workspace = workspace.resolve()
    if workspace.parent != root or not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    return workspace


def _applicable_repositories(run_dir: Path) -> list[str]:
    try:
        step_four = json.loads((run_dir / "steps" / "04.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 4 步成功结果不可读取") from error
    outputs = step_four.get("outputs") if isinstance(step_four, dict) else None
    if not isinstance(step_four, dict) or step_four.get("status") != "success" or not isinstance(outputs, list):
        raise RuntimeError("第 4 步适用工程目录不符合约定")
    if any(not isinstance(name, str) or name not in {"frontend", "backend"} for name in outputs):
        raise RuntimeError("第 4 步适用工程目录不符合约定")
    if len(set(outputs)) != len(outputs):
        raise RuntimeError("第 4 步适用工程目录重复")
    return ["root", *outputs]


def validate_inputs(run_dir: Path, state: dict[str, Any]) -> tuple[Path, list[str]]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于仓库提交锚点")
    return _workspace_from_state(state), _applicable_repositories(run_dir)


def _repository_path(workspace: Path, name: str) -> Path:
    return workspace if name == "root" else workspace / name


def _git_read(path: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=path,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if completed.returncode != 0:
        raise RuntimeError("无法读取 Git 仓库状态")
    return completed.stdout.strip()


def _repository_facts(workspace: Path, names: list[str]) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    for name in names:
        repository_path = _repository_path(workspace, name)
        if repository_path.is_symlink() or not repository_path.is_dir():
            raise RuntimeError("权威 Git 仓库路径不存在或是符号链接")
        path = repository_path.resolve()
        top_level = Path(_git_read(path, "rev-parse", "--show-toplevel")).resolve()
        if top_level != path:
            raise RuntimeError("Git 仓库顶层目录与权威仓库路径不一致")
        if _git_read(path, "branch", "--show-current") != "main":
            raise RuntimeError("Git 仓库分支不是 main")
        repositories.append(
            {
                "name": name,
                "path": str(path),
                "branch": "main",
                "worktree_clean": _git_read(path, "status", "--porcelain") == "",
            }
        )
    return repositories


def _all_clean(repositories: list[dict[str, Any]]) -> bool:
    return all(repository["worktree_clean"] is True for repository in repositories)


def _result_repositories(repositories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": repository["name"],
            "path": "." if repository["name"] == "root" else repository["name"],
            "branch": repository["branch"],
            "worktree_clean": repository["worktree_clean"],
        }
        for repository in repositories
    ]


def _require_resume_anchor(run_dir: Path, state: dict[str, Any]) -> None:
    if state.get("status") not in {"blocked", "failed"}:
        return
    expected_path = f"conversations/{CONVERSATION_KEY}.json"
    sessions = state.get("claude_sessions")
    references = state.get("decision_conversations")
    section = state.get("initialize_repositories")
    session = sessions.get(CONVERSATION_KEY) if isinstance(sessions, dict) else None
    reference = references.get(CONVERSATION_KEY) if isinstance(references, dict) else None
    conversation_file = run_dir / expected_path
    started = (
        state.get("status") == "blocked"
        or session is not None
        or reference is not None
        or conversation_file.exists()
        or isinstance(section, dict)
        and any(key in section for key in ("last_agent_result", "pending_agent_text"))
    )
    if not started:
        return
    if not isinstance(session, str) or not session:
        raise RuntimeError("仓库提交恢复缺少原 Claude session")
    if not isinstance(reference, dict) or reference.get("path") != expected_path:
        raise RuntimeError("仓库提交恢复缺少原决策历史引用")
    if conversation_file.is_symlink() or not conversation_file.is_file():
        raise RuntimeError("仓库提交恢复缺少原决策历史")
    if state.get("status") != "blocked":
        return
    try:
        conversation = json.loads(conversation_file.read_text(encoding="utf-8"))
        messages = conversation["messages"]
        tail = messages[-1]
        if (
            not isinstance(messages, list)
            or not isinstance(tail, dict)
            or tail.get("role") != "assistant"
            or not isinstance(tail.get("content"), str)
        ):
            raise ValueError
        decision = parse_agent_decision(tail["content"])
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ):
        raise RuntimeError("仓库提交恢复缺少有效的 blocked 决策历史") from None
    if decision.verdict != "blocked":
        raise RuntimeError("仓库提交恢复历史尾部不是 blocked 决策")


def _record_recovered_completion(run_dir: Path, state: dict[str, Any]) -> None:
    relative_path = f"conversations/{CONVERSATION_KEY}.json"
    conversation_path = run_dir / relative_path
    if not conversation_path.exists():
        return
    try:
        conversation = json.loads(conversation_path.read_text(encoding="utf-8"))
        messages = conversation["messages"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as error:
        raise RuntimeError("仓库提交恢复对话不可读取") from error
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("仓库提交恢复对话不符合约定")
    tail = messages[-1]
    if isinstance(tail, dict) and tail.get("role") == "assistant":
        try:
            decision = parse_agent_decision(tail.get("content"))
        except (TypeError, ValueError):
            pass
        else:
            if decision.verdict == "completed":
                return
    messages.append(
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "verdict": "completed",
                    "answer": "",
                    "reason": "权威仓库已由 PCM 确定性恢复核验为 main 分支且工作区和暂存区干净。",
                    "required_inputs": [],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
    )
    write_json(conversation_path, {"messages": messages})
    references = state.setdefault("decision_conversations", {})
    if not isinstance(references, dict):
        raise RuntimeError("决策历史引用不符合约定")
    reference = references.get(CONVERSATION_KEY)
    if reference is None:
        references[CONVERSATION_KEY] = {"path": relative_path}
    elif not isinstance(reference, dict) or reference.get("path") != relative_path:
        raise RuntimeError("仓库提交决策历史引用不符合约定")


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    names: list[str],
    repositories: list[dict[str, Any]],
) -> dict[str, Any]:
    _record_recovered_completion(run_dir, state)
    saved = result(
        "success",
        "已完成首次全仓提交检查，权威仓库均位于 main 分支且工作树干净。",
        applicable_repositories=names,
        repositories=_result_repositories(repositories),
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
            "repositories": repositories,
            "blocked": None,
            "error": None,
        }
    )
    state.pop("initial_commits", None)
    initialize_state = state.get("initialize_repositories")
    if isinstance(initialize_state, dict):
        initialize_state.pop("observed_heads", None)
    write_state(run_dir, state)
    return saved


def initial_prompt(names: list[str]) -> str:
    repository_lines = "\n".join(
        f"- {name}: @./{'.' if name == 'root' else name}" for name in names
    )
    return f"""/commit-changes
权威仓库清单（集合和顺序均不可改变）：
{repository_lines}

只在上述独立仓库中处理已有变更；各仓分别完成必要的提交。工作区根从权威能力模板取得的 `.agents/`、`.claude/` 和 `plugins-lock.json` 是已定稿的只读提交输入，只可读取、核对 Git 状态、精确暂存并原样提交，不得创建、修改、删除、移动、格式化、清理、忽略或重写；除可确认的真实秘密或凭据外，不得因版本、许可证、测试产物判断或权限安全偏好要求修复或阻塞，其中 `.claude/settings.json` 的无人值守权限合同必须原样保留，不得收紧为交互授权模式。不得处理清单外的路径、创建或切换分支、改写历史或 push。完成后确保每个仓库都在 main 分支，且工作区和暂存区干净。"""


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
    resume_message: ResumeMessage | None = None,
) -> dict[str, Any]:
    workspace, names = validate_inputs(run_dir, state)
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    repositories = _repository_facts(workspace, names)

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        if not _all_clean(repositories):
            raise RuntimeError("第 8 步成功后权威仓库出现未提交修改")
        return advance_success(run_dir, state, names, repositories)
    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于仓库提交锚点")

    if _all_clean(repositories):
        return advance_success(run_dir, state, names, repositories)

    _require_resume_anchor(run_dir, state)
    if state.get("status") != "blocked":
        state.update({"current_step": STEP, "status": "running", "blocked": None, "error": None})
        write_state(run_dir, state)

    decision_spec = AgentDecisionLoopSpec(
        key=CONVERSATION_KEY,
        state_key="initialize_repositories",
        skill_name=SKILL_NAME,
        max_decision_rounds=MAX_DECISION_ROUNDS,
        max_turns=INITIALIZE_REPOSITORIES_MAX_TURNS,
        model_tier="medium",
        effort="medium",
        decision_system_prompt=render_decision_system_prompt(
            INITIALIZE_REPOSITORIES_DECISION_RULES,
            {
                "有序仓库": [
                    {"name": repository["name"], "path": repository["path"]}
                    for repository in repositories
                ]
            },
        ),
    )

    def completion_verifier() -> str | None:
        verified_repositories = _repository_facts(workspace, names)
        return None if _all_clean(verified_repositories) else REPOSITORY_REPAIR_PROMPT

    decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        decision_spec,
        initial_prompt(names),
        completion_verifier,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
        resume_message=resume_message,
    )
    repositories = _repository_facts(workspace, names)
    if decision.verdict == "blocked":
        if _all_clean(repositories):
            return advance_success(run_dir, state, names, repositories)
        blocked = {
            "reason": decision.reason,
            "required_inputs": decision.required_inputs,
            "applicable_repositories": names,
        }
        saved = result("blocked", decision.reason, blocked=blocked)
        write_step_result(run_dir, STEP, saved)
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
    if not _all_clean(repositories):
        raise RuntimeError("完成核验后权威仓库仍有未提交修改")
    return advance_success(run_dir, state, names, repositories)
