from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import AgentDecision, count_decisions, parse_agent_decision, request_decision
from common.files import write_json
from common.state import write_state
from config import LLMConfig

BLOCKED_RESUME_PROMPT = (
    "此前任务因缺少外部输入而阻塞。请在所需输入已具备后重新核验当前事实并继续；"
    "如仍缺少不可替代输入，请明确说明。"
)
RECOVERABLE_RESULT_PROMPT = "请继续完成工作，并在正常结束后报告结果。"
_SAFE_EXCEPTION_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}\Z")
_RECOVERABLE_SUBTYPES = {"error_max_turns", "error_max_budget_usd"}
_NORMAL_TERMINAL_REASONS = {None, "completed"}
_ABORTED_TERMINAL_REASONS = {"aborted_streaming", "aborted_tools"}


@dataclass(frozen=True)
class AgentDecisionLoopSpec:
    key: str
    state_key: str
    skill_name: str
    max_decision_rounds: int
    max_turns: int
    max_budget_usd: float
    decision_system_prompt: str
    legacy_completion_messages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (("key", self.key), ("state_key", self.state_key)):
            if (
                not isinstance(value, str)
                or not value
                or Path(value).name != value
                or value in {".", ".."}
            ):
                raise ValueError(f"{field_name} 必须是安全的非空名称")
        if not isinstance(self.skill_name, str) or not self.skill_name:
            raise ValueError("skill_name 不能为空")
        if (
            not isinstance(self.max_decision_rounds, int)
            or isinstance(self.max_decision_rounds, bool)
            or self.max_decision_rounds < 0
        ):
            raise ValueError("max_decision_rounds 必须是非负整数")
        if (
            not isinstance(self.max_turns, int)
            or isinstance(self.max_turns, bool)
            or self.max_turns <= 0
        ):
            raise ValueError("max_turns 必须是正整数")
        if (
            not isinstance(self.max_budget_usd, (int, float))
            or isinstance(self.max_budget_usd, bool)
            or self.max_budget_usd <= 0
        ):
            raise ValueError("max_budget_usd 必须是正数")
        if not isinstance(self.decision_system_prompt, str) or not self.decision_system_prompt:
            raise ValueError("decision_system_prompt 不能为空")
        if any(not isinstance(message, str) or not message for message in self.legacy_completion_messages):
            raise ValueError("legacy_completion_messages 必须由非空字符串组成")


# 便于调用方在命名上保持简短。
AgentDecisionSpec = AgentDecisionLoopSpec


def conversation_path(spec: AgentDecisionLoopSpec) -> Path:
    return Path("conversations") / f"{spec.key}.json"


def _state_section(state: dict[str, Any], spec: AgentDecisionLoopSpec) -> dict[str, Any]:
    section = state.setdefault(spec.state_key, {})
    if not isinstance(section, dict):
        raise RuntimeError("Agent 决策运行状态不符合约定")
    return section


def _session(state: dict[str, Any], spec: AgentDecisionLoopSpec) -> str | None:
    sessions = state.get("claude_sessions")
    if sessions is None:
        return None
    if not isinstance(sessions, dict):
        raise RuntimeError("Claude session 状态不符合约定")
    value = sessions.get(spec.key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeError("Claude session ID 不符合约定")
    return value


def _conversation_reference(
    state: dict[str, Any], spec: AgentDecisionLoopSpec
) -> dict[str, Any] | None:
    references = state.get("decision_conversations")
    if references is None:
        return None
    if not isinstance(references, dict):
        raise RuntimeError("决策历史引用不符合约定")
    reference = references.get(spec.key)
    if reference is None:
        return None
    if not isinstance(reference, dict) or set(reference) not in ({"path"}, {"path", "turn"}):
        raise RuntimeError("决策历史引用不符合约定")
    if reference.get("path") != conversation_path(spec).as_posix():
        raise RuntimeError("决策历史引用路径不符合约定")
    return reference


def _validate_messages(messages: Any, spec: AgentDecisionLoopSpec) -> list[dict[str, str]]:
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("决策历史内容不符合约定")
    normalized: list[dict[str, str]] = []
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message.get("role") not in {"system", "assistant", "user"}
            or not isinstance(message.get("content"), str)
        ):
            raise RuntimeError("决策历史消息不符合约定")
        normalized.append({"role": message["role"], "content": message["content"]})
    if normalized[0]["role"] != "system":
        raise RuntimeError("决策历史首条消息必须是 system")
    return normalized


def _load_conversation(
    run_dir: Path, state: dict[str, Any], spec: AgentDecisionLoopSpec
) -> list[dict[str, str]]:
    reference = _conversation_reference(state, spec)
    path = run_dir / conversation_path(spec)
    if reference is None and not path.exists():
        return [{"role": "system", "content": spec.decision_system_prompt}]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RuntimeError("决策历史不可读取") from None
    if not isinstance(data, dict) or set(data) != {"messages"}:
        raise RuntimeError("决策历史内容不符合约定")
    messages = _validate_messages(data["messages"], spec)
    if reference is None:
        references = state.setdefault("decision_conversations", {})
        if not isinstance(references, dict):
            raise RuntimeError("决策历史引用不符合约定")
        references[spec.key] = {"path": conversation_path(spec).as_posix()}
        write_state(run_dir, state)
    return messages


def _save_conversation(
    run_dir: Path,
    state: dict[str, Any],
    spec: AgentDecisionLoopSpec,
    messages: list[dict[str, str]],
) -> None:
    path = run_dir / conversation_path(spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"messages": messages})
    references = state.setdefault("decision_conversations", {})
    if not isinstance(references, dict):
        raise RuntimeError("决策历史引用不符合约定")
    # 新协议只保存 path；旧 turn 由可解析的历史决定数替代。
    references[spec.key] = {"path": conversation_path(spec).as_posix()}
    write_state(run_dir, state)


def _safe_exception_type(value: ClaudeRunResult) -> str | None:
    if not value.exception:
        return None
    if isinstance(value.exception_type, str) and _SAFE_EXCEPTION_TYPE.fullmatch(value.exception_type):
        return value.exception_type
    return "AgentSDKError"


def _safe_agent_result(value: ClaudeRunResult) -> dict[str, Any]:
    return {
        "subtype": value.result_subtype,
        "is_error": value.is_error,
        "stop_reason": value.stop_reason,
        "session_id": value.session_id,
        "num_turns": value.num_turns,
        "total_cost_usd": value.total_cost_usd,
        "api_error_status": value.api_error_status,
        "terminal_reason": value.terminal_reason,
        "has_errors": value.has_errors,
        "exception_type": _safe_exception_type(value),
    }


def _last_agent_finished_normally(state: dict[str, Any], spec: AgentDecisionLoopSpec) -> bool:
    result = _state_section(state, spec).get("last_agent_result")
    return (
        isinstance(result, dict)
        and result.get("subtype") == "success"
        and result.get("is_error") is False
        and result.get("has_errors") is False
        and result.get("api_error_status") is None
        and result.get("exception_type") is None
        and result.get("terminal_reason") in _NORMAL_TERMINAL_REASONS
    )


def _last_agent_requires_normal_completion(
    state: dict[str, Any], spec: AgentDecisionLoopSpec
) -> bool:
    result = _state_section(state, spec).get("last_agent_result")
    return isinstance(result, dict) and not _last_agent_finished_normally(state, spec)


def _save_agent_update(
    run_dir: Path,
    state: dict[str, Any],
    spec: AgentDecisionLoopSpec,
    value: ClaudeRunResult,
) -> None:
    previous_session = _session(state, spec)
    if value.session_id is not None and (
        not isinstance(value.session_id, str) or not value.session_id
    ):
        raise RuntimeError("Agent SDK 返回的 session ID 不符合约定")
    if previous_session and value.session_id and previous_session != value.session_id:
        raise RuntimeError("恢复 session ID 不一致")
    if value.session_id:
        sessions = state.setdefault("claude_sessions", {})
        if not isinstance(sessions, dict):
            raise RuntimeError("Claude session 状态不符合约定")
        sessions[spec.key] = value.session_id

    section = _state_section(state, spec)
    if value.init is not None:
        if not isinstance(value.init, dict):
            raise RuntimeError("Agent SDK init 信息不符合约定")
        skills = {str(item) for item in value.init.get("skills") or []}
        commands = {str(item) for item in value.init.get("slash_commands") or []}
        section["skill_loaded"] = spec.skill_name in skills
        section["slash_command_loaded"] = spec.skill_name in commands
        section["init"] = {
            key: value.init.get(key)
            for key in ("cwd", "model", "permissionMode", "claude_code_version")
            if key in value.init
        }
    if value.result_subtype is not None:
        section["last_agent_result"] = _safe_agent_result(value)
        if isinstance(value.text, str):
            section["pending_agent_text"] = value.text
    write_state(run_dir, state)


def _clear_pending_agent_text(
    run_dir: Path, state: dict[str, Any], spec: AgentDecisionLoopSpec
) -> None:
    _state_section(state, spec).pop("pending_agent_text", None)
    write_state(run_dir, state)


def _discard_legacy_pending_prompt(
    run_dir: Path, state: dict[str, Any], spec: AgentDecisionLoopSpec
) -> None:
    section = _state_section(state, spec)
    if "pending_agent_prompt" in section:
        section.pop("pending_agent_prompt")
        write_state(run_dir, state)


def _append_pending_agent_text(
    run_dir: Path,
    state: dict[str, Any],
    spec: AgentDecisionLoopSpec,
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    pending = _state_section(state, spec).get("pending_agent_text")
    if pending is None:
        return messages
    if not isinstance(pending, str) or not pending.strip():
        raise RuntimeError("待恢复 Agent 回复不符合约定")
    tail = messages[-1]
    if tail == {"role": "user", "content": pending}:
        _clear_pending_agent_text(run_dir, state, spec)
        return messages
    if tail["role"] == "assistant":
        try:
            parse_agent_decision(tail["content"])
        except ValidationError:
            messages.append({"role": "user", "content": pending})
            _save_conversation(run_dir, state, spec, messages)
        else:
            if len(messages) >= 2 and messages[-2] == {"role": "user", "content": pending}:
                # 结构化决定已消费该回复，只清理中断时遗留的恢复锚点。
                _clear_pending_agent_text(run_dir, state, spec)
                return messages
            messages.append({"role": "user", "content": pending})
            _save_conversation(run_dir, state, spec, messages)
    else:
        raise RuntimeError("待恢复 Agent 回复与决策历史尾部冲突")
    _clear_pending_agent_text(run_dir, state, spec)
    return messages


def _require_decision_capacity(messages: list[dict[str, str]], spec: AgentDecisionLoopSpec) -> None:
    if count_decisions(messages) >= spec.max_decision_rounds:
        raise RuntimeError("Agent 决策循环达到上限仍未完成")


def _tail_decision(messages: list[dict[str, str]]) -> AgentDecision | None:
    tail = messages[-1]
    if tail["role"] != "assistant":
        return None
    try:
        return parse_agent_decision(tail["content"])
    except ValidationError:
        return None


def _legacy_completion(messages: list[dict[str, str]], spec: AgentDecisionLoopSpec) -> bool:
    tail = messages[-1]
    return tail["role"] == "assistant" and tail["content"] in spec.legacy_completion_messages


def _validate_agent_result(
    run_dir: Path,
    state: dict[str, Any],
    workspace: Path,
    spec: AgentDecisionLoopSpec,
    value: ClaudeRunResult,
) -> None:
    def fail(message: str) -> None:
        _clear_pending_agent_text(run_dir, state, spec)
        raise RuntimeError(message)

    if value.result_subtype is None:
        fail("Agent SDK 未返回 ResultMessage")
    if value.api_error_status is not None:
        fail("Agent SDK API 请求失败")
    if value.terminal_reason in _ABORTED_TERMINAL_REASONS:
        fail("Agent SDK 执行已取消")
    if value.result_subtype == "success" and value.terminal_reason not in _NORMAL_TERMINAL_REASONS:
        fail("Agent SDK 正常结果包含不支持的终止原因")
    if value.result_subtype not in {"success", *_RECOVERABLE_SUBTYPES}:
        fail("Agent SDK 返回了不支持的终止结果")
    if value.exception and value.result_subtype not in _RECOVERABLE_SUBTYPES:
        fail("Agent SDK 执行异常")
    if value.is_error and value.result_subtype not in _RECOVERABLE_SUBTYPES:
        fail("Agent SDK 执行失败")
    if not isinstance(value.text, str) or not value.text.strip():
        fail("Agent SDK 未返回非空完整回复")
    if value.result_subtype in _RECOVERABLE_SUBTYPES and not _session(state, spec):
        fail("Agent SDK 可恢复终止缺少 session 或回复")
    if not isinstance(value.init, dict):
        fail("Agent SDK 未返回 init 信息")
    init_cwd = value.init.get("cwd")
    if not isinstance(init_cwd, str) or Path(init_cwd).resolve() != workspace.resolve():
        fail("Agent SDK 实际工作目录与产品项目根不一致")
    skills = {str(item) for item in value.init.get("skills") or []}
    if spec.skill_name not in skills:
        fail("Agent SDK 未加载所需 Skill")
    commands = {str(item) for item in value.init.get("slash_commands") or []}
    if spec.skill_name not in commands:
        fail("Agent SDK 未加载所需 slash command")
    if not _session(state, spec):
        fail("Agent 未返回可恢复的 session ID")


async def _run_agent(
    run_dir: Path,
    state: dict[str, Any],
    workspace: Path,
    spec: AgentDecisionLoopSpec,
    prompt: str,
    agent_runner: Callable[..., Any],
) -> list[dict[str, str]]:
    _require_decision_capacity(_load_conversation(run_dir, state, spec), spec)
    try:
        value = await agent_runner(
            prompt,
            cwd=workspace,
            resume_session_id=_session(state, spec),
            max_turns=spec.max_turns,
            max_budget_usd=spec.max_budget_usd,
            on_update=lambda update: _save_agent_update(run_dir, state, spec, update),
        )
    except asyncio.CancelledError:
        raise RuntimeError("Agent SDK 执行已取消") from None
    except Exception:
        raise RuntimeError("Agent SDK 执行异常") from None
    if not isinstance(value, ClaudeRunResult):
        raise RuntimeError("Agent SDK 返回结果不符合约定")
    _save_agent_update(run_dir, state, spec, value)
    _validate_agent_result(run_dir, state, workspace, spec, value)
    messages = _load_conversation(run_dir, state, spec)
    return _append_pending_agent_text(run_dir, state, spec, messages)


async def _request_next_decision(
    run_dir: Path,
    state: dict[str, Any],
    spec: AgentDecisionLoopSpec,
    messages: list[dict[str, str]],
    decision_runner: Callable[..., Any],
    config_loader: Callable[[], LLMConfig],
) -> AgentDecision:
    _require_decision_capacity(messages, spec)
    try:
        data, _attempts, raw = await decision_runner(
            messages,
            config_loader(),
            system_prompt=messages[0]["content"],
        )
        decision = parse_agent_decision(data)
        raw_decision = parse_agent_decision(raw)
    except asyncio.CancelledError:
        raise RuntimeError("AI-compatible 决策已取消") from None
    except (Exception, ValidationError):
        raise RuntimeError("AI-compatible 决策失败") from None
    if not isinstance(raw, str) or decision != raw_decision:
        raise RuntimeError("AI-compatible 决策返回不一致")
    messages.append({"role": "assistant", "content": raw})
    _save_conversation(run_dir, state, spec, messages)
    return decision


async def _verify_completed(
    completion_verifier: Callable[[], str | None],
) -> str | None:
    try:
        repair = completion_verifier()
        if inspect.isawaitable(repair):
            repair = await repair
    except asyncio.CancelledError:
        raise RuntimeError("完成核验已取消") from None
    except Exception:
        raise RuntimeError("完成核验失败") from None
    if repair is None:
        return None
    if not isinstance(repair, str) or not repair.strip():
        raise RuntimeError("完成核验返回无效的修复提示")
    return repair


async def run_agent_decision_loop(
    run_dir: Path,
    state: dict[str, Any],
    workspace: Path,
    spec: AgentDecisionLoopSpec,
    initial_prompt: str,
    completion_verifier: Callable[[], str | None],
    *,
    agent_runner: Callable[..., Any] = run_claude,
    decision_runner: Callable[..., Any] = request_decision,
    config_loader: Callable[[], LLMConfig] = LLMConfig.load,
) -> AgentDecision:
    """运行并恢复 Claude Agent 与结构化决策模型的公共对话循环。"""

    if not run_dir.is_dir():
        raise RuntimeError("运行目录不存在")
    if not isinstance(state, dict):
        raise RuntimeError("运行状态必须是对象")
    if not workspace.is_dir():
        raise RuntimeError("产品工作区不存在")
    if not isinstance(initial_prompt, str) or not initial_prompt.strip():
        raise RuntimeError("初始 Agent 提示不能为空")

    _discard_legacy_pending_prompt(run_dir, state, spec)
    messages = _load_conversation(run_dir, state, spec)
    messages = _append_pending_agent_text(run_dir, state, spec, messages)
    initial_tail_decision = _tail_decision(messages)
    blocked_resume_pending = (
        state.get("status") == "blocked"
        and initial_tail_decision is not None
        and initial_tail_decision.verdict == "blocked"
    )

    while True:
        if _legacy_completion(messages, spec):
            repair = await _verify_completed(completion_verifier)
            if repair is None:
                return AgentDecision(
                    verdict="completed",
                    answer="",
                    reason="已识别既有完成记录并通过核验",
                    required_inputs=[],
                )
            messages.append({"role": "assistant", "content": repair})
            _save_conversation(run_dir, state, spec, messages)
            messages = await _run_agent(
                run_dir, state, workspace, spec, repair, agent_runner
            )
            continue

        decision = _tail_decision(messages)
        if decision is not None:
            if decision.verdict == "blocked":
                if not blocked_resume_pending:
                    return decision
                blocked_resume_pending = False
                messages.append({"role": "assistant", "content": BLOCKED_RESUME_PROMPT})
                _save_conversation(run_dir, state, spec, messages)
                messages = await _run_agent(
                    run_dir, state, workspace, spec, BLOCKED_RESUME_PROMPT, agent_runner
                )
                continue
            if decision.verdict == "completed":
                if _last_agent_requires_normal_completion(state, spec):
                    messages.append({"role": "assistant", "content": RECOVERABLE_RESULT_PROMPT})
                    _save_conversation(run_dir, state, spec, messages)
                    messages = await _run_agent(
                        run_dir, state, workspace, spec, RECOVERABLE_RESULT_PROMPT, agent_runner
                    )
                    continue
                repair = await _verify_completed(completion_verifier)
                if repair is None:
                    return decision
                messages.append({"role": "assistant", "content": repair})
                _save_conversation(run_dir, state, spec, messages)
                messages = await _run_agent(
                    run_dir, state, workspace, spec, repair, agent_runner
                )
                continue
            messages = await _run_agent(
                run_dir, state, workspace, spec, decision.answer, agent_runner
            )
            continue

        tail = messages[-1]
        if tail["role"] == "user":
            await _request_next_decision(
                run_dir,
                state,
                spec,
                messages,
                decision_runner,
                config_loader,
            )
            continue
        if tail["role"] == "system":
            prompt = initial_prompt
            messages.append({"role": "assistant", "content": prompt})
            _save_conversation(run_dir, state, spec, messages)
        else:
            prompt = tail["content"]
        messages = await _run_agent(run_dir, state, workspace, spec, prompt, agent_runner)
