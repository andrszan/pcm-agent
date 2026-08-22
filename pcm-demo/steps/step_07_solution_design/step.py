from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import request_decision
from common.files import resolve_workspace_output, write_json
from common.state import write_state, write_step_result
from config import LLMConfig
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
from steps.step_06_project_bootstrap.step import (
    load_assembly,
    verify_existing_bootstrap_success,
    verify_git_boundaries,
)

STEP = 7
NAME = "总体技术方案"
CURRENT_NODE = "project:07_solution_design"
NEXT_NODE = "project:08_initialize_repositories"
CONVERSATION_KEY = "solution_design"
SKILL_NAME = "solution-design"
CONVERSATION_PATH = Path("conversations/solution_design.json")
DESIGN_PATH = Path("docs/design/技术方案.md")
CHECKLIST = Path("docs/requirements/项目准备清单.md")
MAX_DECISION_ROUNDS = 8
SOLUTION_DESIGN_MAX_TURNS = 48
SOLUTION_DESIGN_MAX_BUDGET_USD = 16.0
COMPLETION_MESSAGE = "已完成 solution-design：总体技术方案已生成并通过完成条件与工程事实核验。"

SOLUTION_DESIGN_DECISION_SYSTEM_PROMPT = """判断最新一轮技术方案 Agent 完整回复是否已经满足当前任务的完成条件，并填写 verdict、answer、reason 和 required_inputs。

verdict 只允许：
- completed：Agent 已明确报告已创建或更新固定技术方案文档，并基于当前实际工程事实确认系统边界、主要技术选择、交付单元、跨单元协作、关键风险和未决事项。回复应说明已读取并核对相关产品定义、准备清单、工程和组装事实；风险、假设和待决事项可以存在，但不能把未核验内容伪装成当前事实。不得把业务实现、工程架构细化、完整需求设计或 Git 操作混入本次工作。
- continue：文档尚未落盘、方案范围不完整、工程事实尚未核对，或存在可以基于当前资料和工具解决的缺口。answer 必须给出明确且可执行的下一步，要求原 Agent session 继续完成和验证。
- blocked：只在缺少当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、付费服务或线下动作时使用，并在 required_inputs 中列出解除条件。

completed 和 continue 的 required_inputs 必须为空数组；continue 的 answer 不得为空；blocked 的 required_inputs 不得为空。技术取舍、资料歧义、架构判断和正常的未来待决事项不构成 blocked。不得用 Mock、假凭据、跳过工程核验或降低完成标准来判定 completed。输出必须是符合 Pydantic 模型的严格 JSON 对象，不得使用 YAML 键值行、Markdown 或代码围栏。"""


class SolutionDesignDecision(BaseModel):
    verdict: Literal["completed", "continue", "blocked"]
    answer: str
    reason: str
    required_inputs: list[str]


class SolutionDesignBlocked(RuntimeError):
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
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": outputs or [],
        "blocked": blocked,
        "error": error,
    }


def _redact_agent_text(text: str) -> str:
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)((?:[\"']?(?:api[-_ ]?key|token|password|secret|client[_-]?secret|access[_-]?token|refresh[_-]?token|authorization)[\"']?)\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)",
        r'\1"[REDACTED]"',
        text,
    )
    return re.sub(
        r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@",
        r"\1[REDACTED]:[REDACTED]@",
        text,
    )


def design_present(workspace: Path) -> bool:
    try:
        path = resolve_workspace_output(workspace, DESIGN_PATH.as_posix())
    except ValueError:
        return False
    current = workspace
    for part in DESIGN_PATH.parts:
        current /= part
        if current.is_symlink():
            return False
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        return False


def verify_existing_solution_success(run_dir: Path) -> dict[str, Any]:
    try:
        existing = json.loads((run_dir / "steps" / "07.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 7 步成功结果不可读取") from error
    if (
        existing.get("step") != STEP
        or existing.get("status") != "success"
        or existing.get("applicable") is not True
        or existing.get("outputs") != [DESIGN_PATH.as_posix()]
    ):
        raise RuntimeError("第 7 步成功结果不可复用")
    return existing


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], dict[str, Any], list[str]]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于总体技术方案锚点")
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
    verify_existing_bootstrap_success(run_dir, outputs)
    verify_git_boundaries(workspace, outputs)
    return workspace, product_outputs, assembly, outputs


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
    design = state.setdefault("solution_design", {})
    if run.init:
        skills = {str(item) for item in run.init.get("skills") or []}
        commands = {str(item) for item in run.init.get("slash_commands") or []}
        design["skill_loaded"] = SKILL_NAME in skills
        design["slash_command_loaded"] = SKILL_NAME in commands
        design["init"] = {
            key: run.init.get(key)
            for key in ("cwd", "model", "permissionMode", "claude_code_version")
        }
    if run.result_subtype:
        design["last_agent_result"] = safe_result(run)
        design["pending_agent_text"] = _redact_agent_text(run.text)
    write_state(run_dir, state)


def load_conversation(run_dir: Path, state: dict[str, Any]) -> list[dict[str, str]]:
    reference = state.get("decision_conversations", {}).get(CONVERSATION_KEY)
    if reference is None:
        return [{"role": "system", "content": SOLUTION_DESIGN_DECISION_SYSTEM_PROMPT}]
    if set(reference) != {"path", "turn"} or reference["path"] != str(CONVERSATION_PATH):
        raise RuntimeError("总体方案决策历史引用不符合约定")
    try:
        data = json.loads((run_dir / CONVERSATION_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("总体方案决策历史不可读取") from error
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("总体方案决策历史内容不符合约定")
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


def parse_solution_design_decision(content: str) -> dict[str, Any] | None:
    try:
        return SolutionDesignDecision.model_validate_json(content).model_dump()
    except ValueError:
        return None


def validate_decision(decision: dict[str, Any], raw: str) -> dict[str, Any]:
    try:
        validated = SolutionDesignDecision.model_validate(decision).model_dump()
        parsed_raw = SolutionDesignDecision.model_validate_json(raw).model_dump()
    except ValueError as error:
        raise RuntimeError("总体方案决策结果不符合约定") from error
    if validated != parsed_raw:
        raise RuntimeError("总体方案决策结果与原始结构化回复不一致")
    if validated["verdict"] == "continue":
        if not validated["answer"] or validated["required_inputs"]:
            raise RuntimeError("继续总体方案的决策缺少有效提示或包含外部输入")
    elif validated["verdict"] == "blocked":
        if not validated["required_inputs"]:
            raise RuntimeError("总体方案阻塞决定缺少解除条件")
    elif validated["required_inputs"]:
        raise RuntimeError("总体方案完成决定不能包含外部输入")
    return validated


def last_decision(messages: list[dict[str, str]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        decision = parse_solution_design_decision(message.get("content", ""))
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
        and parse_solution_design_decision(message.get("content", "")) is not None
    )


def decision_turn(state: dict[str, Any]) -> int:
    turn = (
        state.get("decision_conversations", {})
        .get(CONVERSATION_KEY, {})
        .get("turn", 0)
    )
    if not isinstance(turn, int) or turn < 0:
        raise RuntimeError("总体方案决策历史轮次不符合约定")
    return turn


def synchronize_decision_turn(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
) -> int:
    recorded = decision_turn(state)
    actual = decision_count(messages)
    if recorded > actual:
        raise RuntimeError("总体方案决策历史轮次与消息内容不一致")
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
        raise RuntimeError("solution-design 决策循环达到上限仍未完成")
    return turn


def ensure_agent_round_available(state: dict[str, Any]) -> None:
    if decision_turn(state) >= MAX_DECISION_ROUNDS:
        raise RuntimeError("solution-design 决策循环达到上限仍未完成")


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
        and parse_solution_design_decision(messages[-2].get("content", "")) is not None
        and parse_solution_design_decision(messages[-2]["content"])["verdict"] == "completed"  # type: ignore[index]
    )


def successful_agent(state: dict[str, Any]) -> bool:
    previous = state.get("solution_design", {}).get("last_agent_result", {})
    session_id = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    return isinstance(session_id, str) and bool(session_id) and previous.get("subtype") == "success" and previous.get("is_error") is False


def clear_pending(run_dir: Path, state: dict[str, Any]) -> None:
    design = state.setdefault("solution_design", {})
    design.pop("pending_agent_prompt", None)
    design.pop("pending_agent_text", None)
    write_state(run_dir, state)


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    append_completion(run_dir, state, messages)
    clear_pending(run_dir, state)
    saved = result(
        "success",
        "solution-design 已生成总体技术方案并完成工程事实核验。",
        outputs=[DESIGN_PATH.as_posix()],
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
    outputs: list[str],
) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    project_references = "\n".join(f"- @./{output}" for output in outputs)
    assembly_json = json.dumps(prompt_assembly(assembly), ensure_ascii=False, indent=2)
    return f"""/solution-design
调用方已明确要求并授权你直接在当前项目中创建或更新总体技术方案文档。请基于当前真实工程事实完成设计，不实现业务功能。

权威产品定义：
{product_references}

项目准备事实：
- @./{CHECKLIST.as_posix()}

实际适用工程：
{project_references}

实际组装来源：
```json
{assembly_json}
```

请先读取当前项目规则，以及各适用工程中的 README、manifest、锁文件、配置、代码、测试、运行说明和已有设计文档，再完成以下工作：

1. 创建或更新唯一固定产物 `docs/design/技术方案.md`。
2. 区分当前工程事实、已确认决定、目标状态、假设和待确认事项，不把依赖存在、模板声明或未来计划写成当前事实。
3. 明确系统上下文、系统边界、交付单元、职责、数据所有权、依赖方向、跨单元关键流程和协作方式。
4. 说明身份、权限、错误、状态、恢复、契约事实源、通信方式、数据持久化、一致性、迁移原则、安全、配置、日志和可诊断性边界。
5. 对真正影响长期维护的主要技术取舍给出理由、代价、替代方案和重新讨论条件；可以保留有影响范围和重新评估条件的风险、假设及未决事项。
6. 说明本地开发、测试、联调、发布和运行边界，但不要替代后续需求设计、工程架构设计或业务实现。
7. 方案必须与已经组装并完成项目化的实际工程一致，不重新选择模板，不重新组装工程。
8. 不修改业务代码、配置、迁移或基础设施；不初始化 Git，不暂存、提交、建分支、合并或推送。
9. 不在文档、回复、日志或提交文件中展示秘密具体值。

只有固定文档已经真实写入，且方案、事实核对、风险和待确认事项都已明确记录时，才报告完成。最终完整回复必须列出：文档路径；实际读取和核对的工程事实；已确认的系统边界、主要技术选择、交付单元和跨单元协作；关键风险、假设和未决事项；未验证范围；本轮没有执行的实现或 Git 操作。"""


def resume_prompt(product_outputs: list[str], outputs: list[str]) -> str:
    references = "、".join(f"@./{output}" for output in product_outputs)
    projects = "、".join(f"@./{output}" for output in outputs)
    return (
        f"请重新读取 {references}、@./{CHECKLIST.as_posix()}、{projects} 和当前已有技术方案文档，"
        "重新核对当前工程事实并继续完成总体技术方案。"
        "请补齐系统边界、技术选择、交付单元、跨单元协作、风险和待确认事项；"
        "不要实现业务功能、修改工程架构或执行任何 Git 写操作。"
    )


async def request_solution_design_decision(
    messages: list[dict[str, Any]], config: LLMConfig
) -> tuple[dict[str, Any], int, str]:
    for attempt in range(2):
        prompt = SOLUTION_DESIGN_DECISION_SYSTEM_PROMPT
        if attempt:
            prompt += "\n上一次响应不是有效 JSON；本次只返回严格 JSON 对象。"
        try:
            return await request_decision(
                messages,
                config,
                system_prompt=prompt,
                output_model=SolutionDesignDecision,
            )
        except ValidationError:
            if attempt:
                raise
    raise RuntimeError("总体方案决策未返回结构化结果")


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_solution_design_decision,
    config_loader=LLMConfig.load,
) -> dict[str, Any]:
    workspace, product_outputs, assembly, outputs = validate_inputs(run_dir, state)
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        messages = load_conversation(run_dir, state)
        if not successful_agent(state) or not completion_recorded(messages) or not design_present(workspace):
            raise RuntimeError("第 7 步成功现场不完整")
        verify_existing_solution_success(run_dir)
        clear_pending(run_dir, state)
        return result(
            "success",
            "solution-design 已生成总体技术方案，确认既有成功。",
            outputs=[DESIGN_PATH.as_posix()],
        )

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于总体技术方案锚点")

    messages = load_conversation(run_dir, state)
    synchronize_decision_turn(run_dir, state, messages)
    if successful_agent(state) and completion_recorded(messages) and design_present(workspace):
        if (run_dir / "steps" / "07.json").is_file():
            verify_existing_solution_success(run_dir)
        return advance_success(run_dir, state, messages)

    state.update({"current_step": STEP, "status": "running", "blocked": None, "error": None})
    write_state(run_dir, state)
    existing_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)

    pending_text = state.get("solution_design", {}).get("pending_agent_text")
    if pending_text is not None and not existing_session:
        raise RuntimeError("待恢复 Agent 回复缺少可恢复的 session ID")
    if pending_text is not None:
        if not isinstance(pending_text, str) or not pending_text:
            raise RuntimeError("待恢复 Agent 完整回复不符合约定")
        previous = state.get("solution_design", {}).get("last_agent_result", {})
        recoverable = {"success", "error_max_turns", "error_max_budget_usd"}
        if previous.get("subtype") not in recoverable:
            raise RuntimeError("Agent SDK 上次执行结果不可恢复")
        append_agent_reply(run_dir, state, messages, pending_text)
        state.setdefault("solution_design", {}).pop("pending_agent_text", None)
        write_state(run_dir, state)
        messages = load_conversation(run_dir, state)

    pending = state.get("solution_design", {}).pop("pending_agent_prompt", None)
    if pending is not None and (not isinstance(pending, str) or not pending):
        raise RuntimeError("待恢复总体方案提示不符合约定")

    if not pending and existing_session and messages[-1].get("role") == "user":
        current_turn = require_decision_round(run_dir, state, messages)
        try:
            decision, _, raw = await decision_runner(messages, config_loader())
        except Exception:
            raise RuntimeError("AI-compatible 总体方案完成判断失败") from None
        decision = validate_decision(decision, raw)
        messages.append({"role": "assistant", "content": raw})
        save_conversation(run_dir, state, messages, decision_turn=current_turn + 1)
        if decision["verdict"] == "blocked":
            raise SolutionDesignBlocked(decision["reason"], decision["required_inputs"], [DESIGN_PATH.as_posix()] if design_present(workspace) else [])
        if decision["verdict"] == "completed":
            if not successful_agent(state) or not design_present(workspace):
                raise RuntimeError("决策模型判定完成，但 Agent 或技术方案文档未满足完成条件")
            validate_inputs(run_dir, state)
            return advance_success(run_dir, state, messages)
        pending = decision["answer"]
        state.setdefault("solution_design", {})["pending_agent_prompt"] = pending
        write_state(run_dir, state)

    if not pending and existing_session:
        recovered_decision = last_decision(messages)
        if recovered_decision:
            if recovered_decision["verdict"] == "blocked":
                raise SolutionDesignBlocked(
                    recovered_decision["reason"],
                    recovered_decision["required_inputs"],
                    [DESIGN_PATH.as_posix()] if design_present(workspace) else [],
                )
            if recovered_decision["verdict"] == "completed":
                if not successful_agent(state) or not design_present(workspace):
                    raise RuntimeError("已保存完成决定缺少正常 Agent 结果或技术方案文档")
                return advance_success(run_dir, state, messages)
            pending = recovered_decision["answer"]
            state.setdefault("solution_design", {})["pending_agent_prompt"] = pending
            write_state(run_dir, state)

    if pending:
        ensure_agent_round_available(state)
        prompt = pending
    elif existing_session:
        prompt = resume_prompt(product_outputs, outputs)
    else:
        prompt = initial_prompt(product_outputs, assembly, outputs)
        append_initial_agent_prompt(run_dir, state, prompt)

    for _ in range(MAX_DECISION_ROUNDS):
        run_result = await agent_runner(
            prompt,
            cwd=workspace,
            resume_session_id=state.get("claude_sessions", {}).get(CONVERSATION_KEY),
            max_turns=SOLUTION_DESIGN_MAX_TURNS,
            max_budget_usd=SOLUTION_DESIGN_MAX_BUDGET_USD,
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
            raise RuntimeError("Agent SDK 未加载 solution-design Skill")
        if SKILL_NAME not in {str(item) for item in init.get("slash_commands") or []}:
            clear_pending(run_dir, state)
            raise RuntimeError("Agent SDK 未加载 solution-design slash command")

        messages = load_conversation(run_dir, state)
        agent_text = _redact_agent_text(run_result.text)
        append_agent_reply(run_dir, state, messages, agent_text)
        design = state.setdefault("solution_design", {})
        design.pop("pending_agent_prompt", None)
        design.pop("pending_agent_text", None)
        write_state(run_dir, state)
        messages = load_conversation(run_dir, state)
        current_turn = require_decision_round(run_dir, state, messages)
        try:
            decision, _, raw = await decision_runner(messages, config_loader())
        except Exception:
            raise RuntimeError("AI-compatible 总体方案完成判断失败") from None
        decision = validate_decision(decision, raw)
        messages.append({"role": "assistant", "content": raw})
        save_conversation(run_dir, state, messages, decision_turn=current_turn + 1)

        if decision["verdict"] == "blocked":
            raise SolutionDesignBlocked(
                decision["reason"],
                decision["required_inputs"],
                [DESIGN_PATH.as_posix()] if design_present(workspace) else [],
            )
        if decision["verdict"] == "completed":
            if not successful_agent(state):
                raise RuntimeError("决策模型判定完成，但 Agent 未正常结束或缺少 session ID")
            if not design_present(workspace):
                raise RuntimeError("决策模型判定完成，但技术方案文档不存在或为空")
            validate_inputs(run_dir, state)
            return advance_success(run_dir, state, messages)

        ensure_agent_round_available(state)
        session_id = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
        if not session_id:
            raise RuntimeError("Agent 未完成且没有可恢复的 session ID")
        prompt = decision["answer"]
        design["pending_agent_prompt"] = prompt
        write_state(run_dir, state)

    raise RuntimeError("solution-design 决策循环达到上限仍未完成")
