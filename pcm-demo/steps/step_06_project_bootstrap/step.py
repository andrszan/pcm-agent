from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import request_decision
from common.files import write_json
from common.state import write_state, write_step_result
from config import LLMConfig
from steps.step_01_create_workspace.workspace import git
from steps.step_04_assemble_foundation.step import (
    temporary_root,
    verify_existing_success,
    workspace_from_state,
)
from steps.step_05_project_readiness.step import (
    checklist_present,
    load_product_outputs,
    load_selection,
    verify_existing_readiness_success,
)

STEP = 6
NAME = "项目化基础工程"
CURRENT_NODE = "project:06_bootstrap_foundation"
NEXT_NODE = "project:07_solution_design"
CONVERSATION_KEY = "project_bootstrap"
SKILL_NAME = "project-bootstrap"
CONVERSATION_PATH = Path("conversations/project_bootstrap.json")
CHECKLIST = Path("docs/requirements/项目准备清单.md")
MAX_DECISION_ROUNDS = 8
PROJECT_BOOTSTRAP_MAX_TURNS = 48
PROJECT_BOOTSTRAP_MAX_BUDGET_USD = 16.0
COMPLETION_MESSAGE = "已完成 project-bootstrap：基础工程已完成项目化并通过完成条件与工程边界核验。"

BOOTSTRAP_DECISION_SYSTEM_PROMPT = """判断最新一轮项目化 Agent 完整回复是否已经满足当前任务的完成条件，并填写 verdict、answer、reason 和 required_inputs。

verdict 只允许：
- completed：Agent 已明确报告完成产品根 README、各适用工程的项目身份、基础配置、文档和必要模板残留处理；所有适用工程的依赖安装、静态或类型检查、测试、构建、启动和基础联调均已真实通过或明确不适用；涉及 UI 时已使用真实浏览器读取代表性页面并检查阻断性控制台和网络错误；没有项目化范围内的失败、未验证项或未决事项；没有实施业务功能、总体技术方案、Git 初始化、暂存、提交、分支、合并或推送。
- continue：Agent 尚在计划、请求确认、执行中、验证未完成，或回复缺少足够完成证据。answer 必须给出基于现有输入即可执行的明确下一步，要求其在原 session 中继续完成和验证。
- blocked：只在缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务或线下动作时使用，并在 required_inputs 中列出解除条件。

存在多个合理的项目化方案、模板残留取舍或局部技术修正时，应选择最小且符合现有工程事实的方案并使用 continue，不要因此 blocked。不得用 Mock、假凭据、跳过检查或降低完成标准来判定 completed。completed 和 continue 的 required_inputs 必须为空数组；continue 的 answer 不得为空。输出必须是符合 Pydantic 模型的严格 JSON 对象，不得使用 YAML 键值行、Markdown 或代码围栏。"""


class BootstrapDecision(BaseModel):
    verdict: Literal["completed", "continue", "blocked"]
    answer: str
    reason: str
    required_inputs: list[str]


class ProjectBootstrapBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        outputs: list[str] | None = None,
    ):
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.outputs = outputs or []


def result(
    status: str,
    summary: str,
    *,
    applicable: bool = True,
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": applicable,
        "outputs": outputs or [],
        "blocked": blocked,
        "error": error,
    }


def load_assembly(run_dir: Path) -> dict[str, Any]:
    try:
        assembly = json.loads((run_dir / "steps" / "04.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 4 步组装结果不可读取") from error
    return assembly


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], dict[str, Any], str]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于基础工程项目化锚点")
    workspace = workspace_from_state(state)
    product_outputs = load_product_outputs(run_dir, workspace)
    selection, _ = load_selection(run_dir)
    assembly = load_assembly(run_dir)
    verify_existing_success(
        workspace,
        selection,
        assembly,
        temporary_root(workspace, str(state.get("run_id", ""))),
    )
    verify_existing_readiness_success(run_dir)
    if not checklist_present(workspace):
        raise RuntimeError("第 5 步项目准备清单不存在或不可读取")
    outputs = assembly.get("outputs")
    if not isinstance(outputs, list) or any(
        not isinstance(output, str) or not output for output in outputs
    ):
        raise RuntimeError("第 4 步适用工程目录不符合约定")
    return workspace, product_outputs, assembly, CHECKLIST.as_posix()


def verify_git_boundaries(workspace: Path, outputs: list[str]) -> None:
    staged = git("diff", "--cached", "--name-only", cwd=workspace)
    if staged:
        raise RuntimeError("项目化过程不得暂存文件")
    for output in outputs:
        path = workspace / output
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError(f"适用工程目录不存在或无效：{output}")
        if (path / ".git").exists() or (path / ".git").is_symlink():
            raise RuntimeError(f"适用工程不得提前初始化 Git 仓库：{output}")


def verify_existing_bootstrap_success(
    run_dir: Path, expected_outputs: list[str]
) -> dict[str, Any]:
    try:
        existing = json.loads((run_dir / "steps" / "06.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 6 步成功结果不可读取") from error
    if (
        existing.get("step") != STEP
        or existing.get("status") != "success"
        or existing.get("applicable") != bool(expected_outputs)
        or existing.get("outputs") != expected_outputs
    ):
        raise RuntimeError("第 6 步成功结果不可复用")
    return existing


def safe_result(run: ClaudeRunResult) -> dict[str, Any]:
    return {
        "subtype": run.result_subtype,
        "is_error": run.is_error,
        "stop_reason": run.stop_reason,
        "session_id": run.session_id,
        "num_turns": run.num_turns,
        "total_cost_usd": run.total_cost_usd,
        "exception": "Agent SDK 返回异常" if run.exception else None,
    }


def save_agent_update(run_dir: Path, state: dict[str, Any], run: ClaudeRunResult) -> None:
    previous_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    if previous_session and run.session_id and previous_session != run.session_id:
        raise RuntimeError(
            f"恢复 session ID 不一致：期望 {previous_session}，实际 {run.session_id}"
        )
    if run.session_id:
        state.setdefault("claude_sessions", {})[CONVERSATION_KEY] = run.session_id
    bootstrap = state.setdefault("project_bootstrap", {})
    if run.init:
        skills = {str(item) for item in run.init.get("skills") or []}
        commands = {str(item) for item in run.init.get("slash_commands") or []}
        bootstrap["skill_loaded"] = SKILL_NAME in skills
        bootstrap["slash_command_loaded"] = SKILL_NAME in commands
        bootstrap["init"] = {
            key: run.init.get(key)
            for key in ("cwd", "model", "permissionMode", "claude_code_version")
        }
    if run.result_subtype:
        bootstrap["last_agent_result"] = safe_result(run)
        bootstrap["pending_agent_text"] = run.text
    write_state(run_dir, state)


def load_conversation(run_dir: Path, state: dict[str, Any]) -> list[dict[str, str]]:
    reference = state.get("decision_conversations", {}).get(CONVERSATION_KEY)
    if reference is None:
        return [{"role": "system", "content": BOOTSTRAP_DECISION_SYSTEM_PROMPT}]
    if set(reference) != {"path", "turn"} or reference["path"] != str(CONVERSATION_PATH):
        raise RuntimeError("项目化决策历史引用不符合约定")
    try:
        data = json.loads((run_dir / CONVERSATION_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("项目化决策历史不可读取") from error
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("项目化决策历史内容不符合约定")
    return messages


def save_conversation(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    *,
    decision_turn: int | None = None,
) -> None:
    path = run_dir / CONVERSATION_PATH
    path.parent.mkdir(exist_ok=True)
    write_json(path, {"messages": messages})
    if decision_turn is None:
        decision_turn = (
            state.get("decision_conversations", {})
            .get(CONVERSATION_KEY, {})
            .get("turn", 0)
        )
    state.setdefault("decision_conversations", {})[CONVERSATION_KEY] = {
        "path": str(CONVERSATION_PATH),
        "turn": decision_turn,
    }
    write_state(run_dir, state)


def append_initial_agent_prompt(run_dir: Path, state: dict[str, Any], prompt: str) -> None:
    messages = load_conversation(run_dir, state)
    if len(messages) == 1:
        messages.append({"role": "assistant", "content": prompt})
        save_conversation(run_dir, state, messages)


def parse_bootstrap_decision(content: str) -> dict[str, Any] | None:
    try:
        return BootstrapDecision.model_validate_json(content).model_dump()
    except ValueError:
        return None


def validate_decision(decision: dict[str, Any], raw: str) -> dict[str, Any]:
    try:
        validated = BootstrapDecision.model_validate(decision).model_dump()
        parsed_raw = BootstrapDecision.model_validate_json(raw).model_dump()
    except ValueError as error:
        raise RuntimeError("项目化决策结果不符合约定") from error
    if validated != parsed_raw:
        raise RuntimeError("项目化决策结果与原始结构化回复不一致")
    if validated["verdict"] == "continue":
        if not validated["answer"] or validated["required_inputs"]:
            raise RuntimeError("继续项目化的决策缺少有效提示或包含外部输入")
    elif validated["verdict"] == "blocked":
        if not validated["required_inputs"]:
            raise RuntimeError("项目化阻塞决定缺少解除条件")
    elif validated["required_inputs"]:
        raise RuntimeError("项目化完成决定不能包含外部输入")
    return validated


def last_decision(messages: list[dict[str, str]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        decision = parse_bootstrap_decision(message.get("content", ""))
        if decision is not None:
            return decision
        if message.get("content") != COMPLETION_MESSAGE:
            return None
    return None


def decision_count(messages: list[dict[str, str]]) -> int:
    return sum(
        1
        for message in messages
        if message.get("role") == "assistant"
        and parse_bootstrap_decision(message.get("content", "")) is not None
    )


def decision_turn(state: dict[str, Any]) -> int:
    turn = (
        state.get("decision_conversations", {})
        .get(CONVERSATION_KEY, {})
        .get("turn", 0)
    )
    if not isinstance(turn, int) or turn < 0:
        raise RuntimeError("项目化决策历史轮次不符合约定")
    return turn


def synchronize_decision_turn(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
) -> int:
    recorded = decision_turn(state)
    actual = decision_count(messages)
    if recorded > actual:
        raise RuntimeError("项目化决策历史轮次与消息内容不一致")
    if actual > recorded:
        state.setdefault("decision_conversations", {})[CONVERSATION_KEY] = {
            "path": str(CONVERSATION_PATH),
            "turn": actual,
        }
        write_state(run_dir, state)
    return actual


def require_decision_round(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
) -> int:
    turn = synchronize_decision_turn(run_dir, state, messages)
    if turn >= MAX_DECISION_ROUNDS:
        raise RuntimeError("project-bootstrap 决策循环达到上限仍未完成")
    return turn


def ensure_agent_round_available(state: dict[str, Any]) -> None:
    if decision_turn(state) >= MAX_DECISION_ROUNDS:
        raise RuntimeError("project-bootstrap 决策循环达到上限仍未完成")


def append_agent_reply(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    agent_text: str,
) -> None:
    if not agent_text:
        raise RuntimeError("Agent 未返回可供完成判断的完整回复")
    if not messages or messages[-1] != {"role": "user", "content": agent_text}:
        messages.append({"role": "user", "content": agent_text})
        save_conversation(run_dir, state, messages)


def append_completion(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
) -> None:
    if not messages or messages[-1].get("content") != COMPLETION_MESSAGE:
        messages.append({"role": "assistant", "content": COMPLETION_MESSAGE})
        save_conversation(run_dir, state, messages)


def completion_recorded(messages: list[dict[str, str]]) -> bool:
    return (
        len(messages) >= 2
        and messages[-1] == {"role": "assistant", "content": COMPLETION_MESSAGE}
        and parse_bootstrap_decision(messages[-2].get("content", "")) is not None
        and parse_bootstrap_decision(messages[-2]["content"])["verdict"] == "completed"  # type: ignore[index]
    )


def successful_agent(state: dict[str, Any]) -> bool:
    previous = state.get("project_bootstrap", {}).get("last_agent_result", {})
    return previous.get("subtype") == "success" and previous.get("is_error") is False


def clear_pending(run_dir: Path, state: dict[str, Any]) -> None:
    bootstrap = state.setdefault("project_bootstrap", {})
    bootstrap.pop("pending_agent_prompt", None)
    bootstrap.pop("pending_agent_text", None)
    write_state(run_dir, state)


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    outputs: list[str],
) -> dict[str, Any]:
    append_completion(run_dir, state, messages)
    clear_pending(run_dir, state)
    saved = result(
        "success",
        "project-bootstrap 已完成基础工程项目化和验证。",
        applicable=bool(outputs),
        outputs=outputs,
    )
    write_step_result(run_dir, STEP, saved)
    state.update(
        {
            "status": "success",
            "phase": "project_initialization",
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return saved


def advance_not_applicable(
    run_dir: Path, state: dict[str, Any]
) -> dict[str, Any]:
    saved = result(
        "success",
        "当前没有适用的基础工程，项目化无副作用跳过。",
        applicable=False,
    )
    write_step_result(run_dir, STEP, saved)
    state.update(
        {
            "status": "success",
            "phase": "project_initialization",
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
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
            continue
        if not isinstance(entry, dict):
            raise RuntimeError("第 4 步组装来源不符合约定")
        visible[target] = {
            key: entry.get(key)
            for key in (
                "target",
                "id",
                "default_branch",
                "path",
                "branch",
                "commit_sha",
            )
        }
    return visible


def initial_prompt(
    product_outputs: list[str],
    assembly: dict[str, Any],
    checklist: str,
) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    project_references = "\n".join(
        f"- @./{output}" for output in assembly.get("outputs", [])
    )
    assembly_json = json.dumps(prompt_assembly(assembly), ensure_ascii=False, indent=2)
    return f"""/project-bootstrap
调用方已明确要求并授权你直接在当前项目中完成有限范围的工程项目化，并执行真实安装、构建、测试、启动和基础联调验证。

权威产品定义：
{product_references}

项目准备事实：
- @./{checklist}

实际适用工程：
{project_references}

实际组装来源：
```json
{assembly_json}
```

请先读取当前项目规则，以及各适用工程中的 README、manifest、锁文件、配置、代码、测试和 Git 事实，再完成以下工作：

1. 将产品根 README 和通用模板有限收口为当前具体项目，落实项目名称、应用名称、标题、描述、各适用工程 README、公开配置示例和必要的基础运行说明。
2. 保留仍有效的工程能力；对模板首页、示例文案、模板测试和专属残留先检查引用，只处理会误导后续开发且能够安全确认归属的内容。
3. 只落实产品定义中已经确认且属于共享基础的品牌、视觉和可访问性事实，不提前实现完整业务页面、导航、数据模型、业务接口、认证权限、迁移、状态机、初始化业务数据、总体技术方案或工程架构。
4. 按当前工程的锁文件和真实说明安装依赖，执行所有适用的格式检查、静态检查、类型检查、测试和构建。
5. 启动所有适用服务，验证后端健康与就绪入口；存在前端时使用真实浏览器读取代表性页面，检查阻断性控制台和失败网络请求；前后端同时适用时完成最小真实联调，不使用 Mock 或静态响应冒充通过。
6. 验证失败时，先修复属于本次项目化范围的问题并重新执行；只有缺少当前环境无法取得的不可替代外部资源时才明确报告阻塞。
7. 保护现有被忽略的开发配置、项目能力和 Plugin 快照，不在文档、回复、日志或可提交文件中展示秘密具体值。
8. 不执行 Git 初始化、暂存、提交、建分支、合并或推送。

只有项目身份和基础工程已经完成收口，所有适用安装、检查、测试、构建、启动及基础联调均通过，并且没有项目化范围内的未决失败或未验证项时，才明确报告完成。

最终完整回复必须列出：实际处理的工程目录；创建、修改、删除和保留的主要内容；每个适用工程执行的安装、检查、测试、构建和启动结果；基础联调与浏览器验证结果；未验证范围、阻塞或仍待后续处理的事项。不得省略失败结果，也不得泄露秘密。"""


def resume_prompt(product_outputs: list[str], checklist: str) -> str:
    references = "、".join(f"@./{output}" for output in product_outputs)
    return (
        f"请重新读取 {references}、@./{checklist} 和当前适用工程事实，继续完成有限范围项目化。"
        "请完成所有适用安装、检查、测试、构建、启动、真实浏览器检查和基础联调；修复本次范围内的问题后重跑验证。"
        "不要实现业务功能、初始化独立 Git 仓库或执行暂存、提交、分支、合并和推送。"
    )


async def request_bootstrap_decision(
    messages: list[dict[str, Any]], config: LLMConfig
) -> tuple[dict[str, Any], int, str]:
    for attempt in range(2):
        prompt = BOOTSTRAP_DECISION_SYSTEM_PROMPT
        if attempt:
            prompt += "\n上一次响应不是有效 JSON；本次只返回严格 JSON 对象。"
        try:
            return await request_decision(
                messages,
                config,
                system_prompt=prompt,
                output_model=BootstrapDecision,
            )
        except ValidationError:
            if attempt:
                raise
    raise RuntimeError("项目化决策未返回结构化结果")


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_bootstrap_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    workspace, product_outputs, assembly, checklist = validate_inputs(run_dir, state)
    outputs = assembly["outputs"]
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))

    verify_git_boundaries(workspace, outputs)
    if not outputs:
        if position == (STEP + 1, STEP + 1, NEXT_NODE):
            return verify_existing_bootstrap_success(run_dir, outputs)
        return advance_not_applicable(run_dir, state)

    messages = load_conversation(run_dir, state)
    synchronize_decision_turn(run_dir, state, messages)

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        if not successful_agent(state) or not completion_recorded(messages):
            raise RuntimeError("第 6 步成功现场不完整")
        verify_existing_bootstrap_success(run_dir, outputs)
        clear_pending(run_dir, state)
        return result(
            "success",
            "project-bootstrap 已完成基础工程项目化和验证，确认既有成功。",
            outputs=outputs,
        )

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于基础工程项目化锚点")

    if successful_agent(state) and completion_recorded(messages):
        if (run_dir / "steps" / "06.json").is_file():
            verify_existing_bootstrap_success(run_dir, outputs)
        return advance_success(run_dir, state, messages, outputs)

    state.update({"current_step": STEP, "status": "running", "blocked": None, "error": None})
    write_state(run_dir, state)
    existing_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)

    pending_text = state.get("project_bootstrap", {}).get("pending_agent_text")
    if pending_text is not None:
        if not isinstance(pending_text, str) or not pending_text:
            raise RuntimeError("待恢复 Agent 完整回复不符合约定")
        previous = state.get("project_bootstrap", {}).get("last_agent_result", {})
        recoverable = {"success", "error_max_turns", "error_max_budget_usd"}
        if previous.get("subtype") not in recoverable:
            raise RuntimeError("Agent SDK 上次执行结果不可恢复")
        append_agent_reply(run_dir, state, messages, pending_text)
        state.setdefault("project_bootstrap", {}).pop("pending_agent_text", None)
        write_state(run_dir, state)
        messages = load_conversation(run_dir, state)

    pending = state.get("project_bootstrap", {}).pop("pending_agent_prompt", None)
    if pending is not None and (not isinstance(pending, str) or not pending):
        raise RuntimeError("待恢复项目化提示不符合约定")

    if not pending and existing_session and messages[-1].get("role") == "user":
        current_turn = require_decision_round(run_dir, state, messages)
        try:
            decision, _, raw = await decision_runner(messages, config_loader())
        except Exception:
            raise RuntimeError("AI-compatible 项目化完成判断失败") from None
        decision = validate_decision(decision, raw)
        messages.append({"role": "assistant", "content": raw})
        save_conversation(run_dir, state, messages, decision_turn=current_turn + 1)
        if decision["verdict"] == "blocked":
            raise ProjectBootstrapBlocked(
                decision["reason"], decision["required_inputs"], outputs
            )
        if decision["verdict"] == "completed":
            if not successful_agent(state):
                raise RuntimeError("决策模型判定完成，但 Agent 未正常结束")
            validate_inputs(run_dir, state)
            verify_git_boundaries(workspace, outputs)
            return advance_success(run_dir, state, messages, outputs)
        pending = decision["answer"]
        state.setdefault("project_bootstrap", {})["pending_agent_prompt"] = pending
        write_state(run_dir, state)

    if not pending and existing_session:
        recovered_decision = last_decision(messages)
        if recovered_decision:
            if recovered_decision["verdict"] == "blocked":
                raise ProjectBootstrapBlocked(
                    recovered_decision["reason"],
                    recovered_decision["required_inputs"],
                    outputs,
                )
            if recovered_decision["verdict"] == "completed":
                if not successful_agent(state):
                    raise RuntimeError("已保存完成决定缺少正常 Agent 结果")
                verify_git_boundaries(workspace, outputs)
                return advance_success(run_dir, state, messages, outputs)
            pending = recovered_decision["answer"]
            state.setdefault("project_bootstrap", {})["pending_agent_prompt"] = pending
            write_state(run_dir, state)

    if pending:
        ensure_agent_round_available(state)
        prompt = pending
    elif existing_session:
        prompt = resume_prompt(product_outputs, checklist)
    else:
        prompt = initial_prompt(product_outputs, assembly, checklist)
        append_initial_agent_prompt(run_dir, state, prompt)

    for _ in range(MAX_DECISION_ROUNDS):
        run_result = await agent_runner(
            prompt,
            cwd=workspace,
            resume_session_id=state.get("claude_sessions", {}).get(CONVERSATION_KEY),
            max_turns=PROJECT_BOOTSTRAP_MAX_TURNS,
            max_budget_usd=PROJECT_BOOTSTRAP_MAX_BUDGET_USD,
            on_update=lambda update: save_agent_update(run_dir, state, update),
        )
        save_agent_update(run_dir, state, run_result)
        if not run_result.result_subtype:
            raise RuntimeError("Agent SDK 未返回 ResultMessage")
        recoverable_subtypes = {"error_max_turns", "error_max_budget_usd"}
        if run_result.exception and run_result.result_subtype not in recoverable_subtypes:
            clear_pending(run_dir, state)
            raise RuntimeError("Agent SDK 执行异常")
        if run_result.is_error and run_result.result_subtype not in recoverable_subtypes:
            clear_pending(run_dir, state)
            raise RuntimeError(f"Agent SDK 执行失败：{run_result.result_subtype}")
        init = run_result.init or {}
        init_cwd = init.get("cwd")
        if not isinstance(init_cwd, str) or Path(init_cwd).resolve() != workspace:
            clear_pending(run_dir, state)
            raise RuntimeError("Agent SDK 实际工作目录与产品项目根不一致")
        if SKILL_NAME not in {str(item) for item in init.get("skills") or []}:
            clear_pending(run_dir, state)
            raise RuntimeError("Agent SDK 未加载 project-bootstrap Skill")
        if SKILL_NAME not in {str(item) for item in init.get("slash_commands") or []}:
            clear_pending(run_dir, state)
            raise RuntimeError("Agent SDK 未加载 project-bootstrap slash command")

        messages = load_conversation(run_dir, state)
        append_agent_reply(run_dir, state, messages, run_result.text)
        bootstrap = state.setdefault("project_bootstrap", {})
        bootstrap.pop("pending_agent_prompt", None)
        bootstrap.pop("pending_agent_text", None)
        write_state(run_dir, state)
        messages = load_conversation(run_dir, state)
        current_turn = require_decision_round(run_dir, state, messages)
        try:
            decision, _, raw = await decision_runner(messages, config_loader())
        except Exception:
            raise RuntimeError("AI-compatible 项目化完成判断失败") from None
        decision = validate_decision(decision, raw)
        messages.append({"role": "assistant", "content": raw})
        save_conversation(run_dir, state, messages, decision_turn=current_turn + 1)

        if decision["verdict"] == "blocked":
            raise ProjectBootstrapBlocked(
                decision["reason"], decision["required_inputs"], outputs
            )
        if decision["verdict"] == "completed":
            if run_result.result_subtype != "success" or run_result.is_error:
                raise RuntimeError("决策模型判定完成，但 Agent 未正常结束")
            validate_inputs(run_dir, state)
            verify_git_boundaries(workspace, outputs)
            return advance_success(run_dir, state, messages, outputs)

        ensure_agent_round_available(state)
        session_id = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
        if not session_id:
            raise RuntimeError("Agent 未完成且没有可恢复的 session ID")
        prompt = decision["answer"]
        bootstrap["pending_agent_prompt"] = prompt
        write_state(run_dir, state)

    raise RuntimeError("project-bootstrap 决策循环达到上限仍未完成")
