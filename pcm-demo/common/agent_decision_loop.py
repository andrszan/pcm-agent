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

from common.claude_agent import (
    ClaudeRunResult,
    is_retryable_claude_sdk_error,
    run_claude,
)
from common.decision import AgentDecision, DecisionMessage, count_decisions, parse_agent_decision, request_decision
from common.error_diagnostics import exception_diagnostics, redact_text, write_diagnostic
from common.files import write_json
from common.openai_responses import ResponsesFailure
from common.state import write_state
from common.timing import beijing_now, run_timed_agent
from config import LLMConfig
from model_policy import get_agent_profile

BLOCKED_RESUME_PROMPT = (
    "此前任务因缺少外部输入而阻塞。请在所需输入已具备后重新核验当前事实并继续；"
    "如仍缺少不可替代输入，请明确说明。"
)
RECOVERABLE_RESULT_PROMPT = "请继续完成工作，并在正常结束后报告结果。"
_SAFE_EXCEPTION_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}\Z")
_RECOVERABLE_SUBTYPES = {"error_max_turns", "error_max_budget_usd"}
_NORMAL_TERMINAL_REASONS = {None, "completed"}
_ABORTED_TERMINAL_REASONS = {"aborted_streaming", "aborted_tools"}
_RETRYABLE_TERMINAL_REASONS = {"api_error", "blocking_limit"}
_DECISION_FAILURE_MESSAGES = {
    "configuration": "AI-compatible 裁决配置不可用",
    "transport": "AI-compatible 裁决服务连接或请求超时",
    "http": "AI-compatible 裁决服务 HTTP 请求失败",
    "response": "AI-compatible 裁决响应不符合合同",
    "internal": "AI-compatible 裁决本地处理失败",
}


class AIDecisionFailure(RuntimeError):
    def __init__(
        self,
        diagnostic: dict[str, str | int],
        *,
        message: str | None = None,
        diagnostic_path: str | None = None,
    ) -> None:
        self.diagnostic = dict(diagnostic)
        self.diagnostic_path = diagnostic_path
        kind = self.diagnostic["kind"]
        base = _DECISION_FAILURE_MESSAGES[str(kind)]
        if "http_status" in self.diagnostic:
            base = f"{base}（HTTP {self.diagnostic['http_status']}）"
        detail = message or self.diagnostic.get("provider_message")
        super().__init__(f"{base}：{detail}" if isinstance(detail, str) and detail else base)

    def as_error(self) -> dict[str, Any]:
        error = {
            "type": type(self).__name__,
            "message": str(self),
            "decision_failure": dict(self.diagnostic),
        }
        if self.diagnostic_path:
            error["diagnostic_path"] = self.diagnostic_path
        return error


class AgentExecutionFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        diagnostic_path: str,
        *,
        retry_requested: bool = False,
    ) -> None:
        self.diagnostic_path = diagnostic_path
        self.retry_requested = retry_requested
        super().__init__(message)

    def as_error(self) -> dict[str, str]:
        return {
            "type": type(self).__name__,
            "message": str(self),
            "diagnostic_path": self.diagnostic_path,
        }


@dataclass(frozen=True)
class AgentDecisionLoopSpec:
    key: str
    state_key: str
    skill_name: str
    max_decision_rounds: int
    max_turns: int
    task: str
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
        if not isinstance(self.task, str) or not self.task:
            raise ValueError("task 必须是非空任务标识")
        if not isinstance(self.decision_system_prompt, str) or not self.decision_system_prompt:
            raise ValueError("decision_system_prompt 不能为空")
        if any(not isinstance(message, str) or not message for message in self.legacy_completion_messages):
            raise ValueError("legacy_completion_messages 必须由非空字符串组成")


# 便于调用方在命名上保持简短。
AgentDecisionSpec = AgentDecisionLoopSpec


@dataclass
class ResumeMessage:
    target_key: str
    content: str
    consumed: bool = False


_RESUME_STEP_NODES = {
    2: "project:02_intake",
    5: "project:05_verify_readiness",
    6: "project:06_bootstrap_foundation",
    7: "project:07_solution_design",
    8: "project:08_initialize_repositories",
    9: "project:09_engineering_architecture",
    10: "project:10_ui_ux_framework",
    11: "project:11_requirement_breakdown",
    14: "requirement:14_trd_design",
    15: "requirement:15_development",
    16: "requirement:16_rule_retrospective",
    17: "requirement:17_commit",
}
_RESUME_STATIC_KEYS = {
    2: ("project_intake",),
    5: ("project_readiness",),
    6: ("project_bootstrap", "tailwind_theme", "brand_assets"),
    7: ("solution_design",),
    8: ("initialize_repositories",),
    9: ("engineering_architecture",),
    10: ("ui_ux_framework",),
    11: ("requirement_breakdown",),
}
_RESUME_REQUIREMENT_PREFIXES = {
    14: "trd_design",
    15: "development",
    16: "rule_retrospective",
    17: "requirement_commit",
}


def _decision_at(
    messages: list[dict[str, str]], index: int
) -> AgentDecision | None:
    normalized = index if index >= 0 else len(messages) + index
    if normalized <= 0 or normalized >= len(messages):
        return None
    message = messages[normalized]
    if message["role"] != "assistant" or messages[normalized - 1]["role"] != "user":
        return None
    try:
        return parse_agent_decision(message["content"])
    except ValidationError:
        return None


def _resume_anchor(messages: list[dict[str, str]]) -> bool:
    last_user = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if messages[index]["role"] == "user"
        ),
        -1,
    )
    decision = _decision_at(messages, last_user + 1)
    return (
        decision is not None
        and decision.verdict == "blocked"
        and all(message["role"] == "assistant" for message in messages[last_user + 1 :])
    )


def _resume_keys(step: int, state: dict[str, Any]) -> tuple[str, ...]:
    static = _RESUME_STATIC_KEYS.get(step)
    if static is not None:
        return static
    prefix = _RESUME_REQUIREMENT_PREFIXES.get(step)
    requirement_id = state.get("active_requirement")
    if prefix is None or not isinstance(requirement_id, str) or not requirement_id:
        return ()
    return (f"{prefix}_{requirement_id}",)


def validate_resume_target(
    run_dir: Path,
    state: dict[str, Any],
    step: int,
) -> str:
    """在步骤锁内选择当前 blocked 节点唯一可恢复的原对话。"""

    expected_node = _RESUME_STEP_NODES.get(step)
    if expected_node is None:
        raise ValueError(f"第 {step} 步不支持负责人消息恢复")
    if (
        state.get("status") != "blocked"
        or (state.get("step"), state.get("current_step"), state.get("current_node"))
        != (step, step, expected_node)
    ):
        raise ValueError("负责人消息只能用于当前 blocked 节点")

    sessions = state.get("claude_sessions")
    references = state.get("decision_conversations")
    if not isinstance(sessions, dict) or not isinstance(references, dict):
        raise ValueError("当前 blocked 节点没有可恢复的原 Agent 对话")

    matches: list[str] = []
    for key in _resume_keys(step, state):
        session_id = sessions.get(key)
        reference = references.get(key)
        expected_path = f"conversations/{key}.json"
        if (
            not isinstance(session_id, str)
            or not session_id
            or not isinstance(reference, dict)
            or set(reference) not in ({"path"}, {"path", "turn"})
            or reference.get("path") != expected_path
        ):
            continue
        conversation = run_dir / expected_path
        try:
            data = json.loads(conversation.read_bytes().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or set(data) != {"messages"}:
            continue
        try:
            messages = _validate_messages(data["messages"])
        except RuntimeError:
            continue
        if _resume_anchor(messages):
            matches.append(key)

    if len(matches) != 1:
        raise ValueError("当前 blocked 节点没有唯一可恢复的原 Agent 对话")
    return matches[0]


def prepare_resume_message(
    path: Path,
    run_dir: Path,
    state: dict[str, Any],
    step: int,
) -> ResumeMessage:
    """读取一次负责人恢复消息并绑定已校验的原对话。"""

    target_key = validate_resume_target(run_dir, state, step)
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("负责人消息文件不存在或不是普通文件")
    try:
        content = resolved.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("负责人消息文件不可读取或不是有效 UTF-8 文本") from error
    if not content.strip():
        raise ValueError("负责人消息文件不能为空")
    return ResumeMessage(target_key, content)


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


def conversation_message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content, "timestamp": beijing_now()}


def _validate_messages(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("决策历史内容不符合约定")
    normalized: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise RuntimeError("决策历史消息不符合约定")
        try:
            DecisionMessage.model_validate(message)
        except ValidationError as error:
            raise RuntimeError("决策历史消息不符合约定") from error
        # 验证后复制原字段；旧消息不补时间，新时间不在加载时刷新。
        normalized.append(dict(message))
    if normalized[0]["role"] != "system":
        raise RuntimeError("决策历史首条消息必须是 system")
    return normalized


def validate_agent_decision_loop_scene(
    run_dir: Path, state: dict[str, Any], spec: AgentDecisionLoopSpec
) -> bool:
    """确认已有决策循环具备可安全恢复的完整锚点。"""

    sessions = state.get("claude_sessions")
    references = state.get("decision_conversations")
    session_present = isinstance(sessions, dict) and spec.key in sessions
    reference_present = isinstance(references, dict) and spec.key in references
    session = _session(state, spec)
    reference = _conversation_reference(state, spec)
    path = run_dir / conversation_path(spec)
    section = state.get(spec.state_key)
    started = (
        spec.state_key in state
        or session_present
        or reference_present
        or path.exists()
        or path.is_symlink()
        or state.get("status") == "blocked"
    )
    if not started:
        return False

    if reference is None:
        raise RuntimeError("Agent 决策恢复缺少原决策历史引用")
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Agent 决策恢复缺少原决策历史")
    messages = _load_conversation(run_dir, state, spec)
    if (
        len(messages) < 2
        or messages[1]["role"] != "assistant"
        or not messages[1]["content"].strip()
    ):
        raise RuntimeError("Agent 决策历史缺少初始负责人指令")

    if session is None:
        last_agent_result = (
            section.get("last_agent_result") if isinstance(section, dict) else None
        )
        if not (
            len(messages) == 2
            and not session_present
            and state.get("status") != "blocked"
            and (
                not isinstance(section, dict)
                or (
                    "init" not in section
                    and section.get("pending_agent_text") is None
                    and (
                        not isinstance(last_agent_result, dict)
                        or not last_agent_result.get("session_id")
                    )
                )
            )
        ):
            raise RuntimeError("Agent 决策已有回复或 session 事实但缺少 session 别名")
    return True


def _load_conversation(
    run_dir: Path, state: dict[str, Any], spec: AgentDecisionLoopSpec
) -> list[dict[str, str]]:
    reference = _conversation_reference(state, spec)
    path = run_dir / conversation_path(spec)
    if reference is None and not path.exists():
        return [conversation_message("system", spec.decision_system_prompt)]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("决策历史不可读取") from error
    if not isinstance(data, dict) or set(data) != {"messages"}:
        raise RuntimeError("决策历史内容不符合约定")
    messages = _validate_messages(data["messages"])
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


def _agent_reason(value: ClaudeRunResult | None, error: BaseException | None = None) -> str:
    if value is not None:
        if value.context_window_exceeded:
            detail = value.sdk_errors[0] if value.sdk_errors else "Agent SDK API 请求失败（HTTP 400）"
            return f"Claude Agent SDK 输入超过当前模型上下文窗口：{redact_text(detail)}"
        if value.sdk_errors:
            return redact_text(value.sdk_errors[0])
        if isinstance(value.exception_details, dict):
            message = value.exception_details.get("message")
            if isinstance(message, str) and message:
                return redact_text(message)
        if value.exception:
            return redact_text(value.exception)
        if value.api_error_status is not None:
            return f"Agent SDK API 请求失败（HTTP {value.api_error_status}）"
        if value.terminal_reason:
            return f"Agent SDK 终止原因：{redact_text(value.terminal_reason)}"
        if value.is_error or value.has_errors:
            return "Agent SDK 返回失败结果"
    if error is not None:
        return redact_text(f"{type(error).__name__}: {error}")
    return "Agent SDK 执行失败"


def _safe_agent_result(
    value: ClaudeRunResult, *, failure: AgentExecutionFailure | None = None
) -> dict[str, Any]:
    result = {
        "subtype": value.result_subtype,
        "is_error": value.is_error,
        "stop_reason": value.stop_reason,
        "session_id": value.session_id,
        "num_turns": value.num_turns,
        "total_cost_usd": value.total_cost_usd,
        "usage": value.usage,
        "model_usage": value.model_usage,
        "api_error_status": value.api_error_status,
        "terminal_reason": value.terminal_reason,
        "has_errors": value.has_errors,
        "exception_type": _safe_exception_type(value),
    }
    if value.context_window_exceeded or value.assistant_error is not None:
        result.update(
            {
                "assistant_error": value.assistant_error,
                "context_window_exceeded": value.context_window_exceeded,
            }
        )
    if failure is not None:
        result.update({"message": str(failure), "diagnostic_path": failure.diagnostic_path})
    return result


def _agent_diagnostic_context(
    state: dict[str, Any], key: str, context: dict[str, Any] | None
) -> dict[str, Any]:
    fields = {
        name: state.get(name)
        for name in ("step", "current_step", "phase", "current_node", "active_requirement")
        if state.get(name) is not None
    }
    fields.update(
        {
            "component": "claude_agent",
            "operation": "run_agent",
            "conversation_path": (Path("conversations") / f"{key}.json").as_posix(),
        }
    )
    if context:
        fields.update(context)
    return fields


def persist_agent_failure(
    run_dir: Path,
    state: dict[str, Any],
    *,
    key: str,
    state_key: str | None,
    value: ClaudeRunResult | None = None,
    error: BaseException | None = None,
    context: dict[str, Any] | None = None,
    retry_requested: bool | None = None,
) -> AgentExecutionFailure:
    """保存公共和直连 Claude 调用共用的当前故障快照。"""
    message = _agent_reason(value, error)
    exception = (
        value.exception_details
        if value is not None and isinstance(value.exception_details, dict)
        else exception_diagnostics(error) if error is not None else {
            "type": value.exception_type or "AgentExecutionFailure" if value else "AgentExecutionFailure",
            "message": message,
            "chain": [],
            "traceback": [],
        }
    )
    details: dict[str, Any] = {}
    if value is not None:
        details = {
            "result_subtype": value.result_subtype,
            "is_error": value.is_error,
            "stop_reason": value.stop_reason,
            "session_id": value.session_id,
            "num_turns": value.num_turns,
            "total_cost_usd": value.total_cost_usd,
            "api_error_status": value.api_error_status,
            "terminal_reason": value.terminal_reason,
            "sdk_errors": value.sdk_errors,
        }
        if value.context_window_exceeded or value.assistant_error is not None:
            details.update(
                {
                    "assistant_error": value.assistant_error,
                    "context_window_exceeded": value.context_window_exceeded,
                }
            )
    path = write_diagnostic(
        run_dir,
        f"{key}-agent.json",
        source="agent",
        kind="agent",
        context=_agent_diagnostic_context(state, key, context),
        details=details,
        exception=exception,
        error=error,
    )
    effective_retry_requested = (
        value.retry_requested
        if retry_requested is None and value is not None
        else bool(retry_requested)
    )
    failure = AgentExecutionFailure(
        message,
        path,
        retry_requested=effective_retry_requested,
    )
    if state_key is not None:
        section = state.setdefault(state_key, {})
        if not isinstance(section, dict):
            raise RuntimeError("Agent 决策运行状态不符合约定")
        if value is not None or not isinstance(section.get("last_agent_result"), dict):
            section["last_agent_result"] = (
                _safe_agent_result(value, failure=failure)
                if value is not None
                else {
                    "exception_type": type(error).__name__ if error else "AgentExecutionFailure",
                    "message": str(failure),
                    "diagnostic_path": path,
                }
            )
        write_state(run_dir, state)
    return failure


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
        if isinstance(value.text, str) and value.text.strip():
            section["pending_agent_text"] = value.text
    write_state(run_dir, state)


def _clear_pending_agent_text(
    run_dir: Path, state: dict[str, Any], spec: AgentDecisionLoopSpec
) -> None:
    _state_section(state, spec).pop("pending_agent_text", None)
    write_state(run_dir, state)


def _raise_decision_failure(
    run_dir: Path,
    state: dict[str, Any],
    spec: AgentDecisionLoopSpec,
    diagnostic: dict[str, str | int],
    error: BaseException | None = None,
) -> None:
    detail = diagnostic.get("provider_message")
    if not isinstance(detail, str) or not detail:
        detail = redact_text(f"{type(error).__name__}: {error}") if error else _DECISION_FAILURE_MESSAGES[str(diagnostic["kind"])]
    path = write_diagnostic(
        run_dir,
        f"{spec.key}-decision.json",
        source="decision",
        kind=str(diagnostic["kind"]),
        context=_agent_diagnostic_context(state, spec.key, {"component": "decision", "operation": "request_decision"}),
        details=diagnostic,
        error=error,
    )
    state_diagnostic = {**diagnostic, "message": detail, "diagnostic_path": path}
    _state_section(state, spec)["last_decision_failure"] = state_diagnostic
    write_state(run_dir, state)
    failure = AIDecisionFailure(diagnostic, message=detail, diagnostic_path=path)
    if error is not None:
        raise failure from error
    raise failure


def _clear_decision_failure(
    run_dir: Path, state: dict[str, Any], spec: AgentDecisionLoopSpec
) -> None:
    section = _state_section(state, spec)
    if "last_decision_failure" in section:
        section.pop("last_decision_failure")
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
    if not isinstance(pending, str):
        raise RuntimeError("待恢复 Agent 回复不符合约定")
    if not pending.strip():
        _clear_pending_agent_text(run_dir, state, spec)
        return messages
    tail = messages[-1]
    if tail["role"] == "user" and tail["content"] == pending:
        _clear_pending_agent_text(run_dir, state, spec)
        return messages
    if tail["role"] == "assistant":
        if _decision_at(messages, -1) is None:
            messages.append(conversation_message("user", pending))
            _save_conversation(run_dir, state, spec, messages)
        else:
            if len(messages) >= 2 and messages[-2]["role"] == "user" and messages[-2]["content"] == pending:
                # 结构化决定已消费该回复，只清理中断时遗留的恢复锚点。
                _clear_pending_agent_text(run_dir, state, spec)
                return messages
            messages.append(conversation_message("user", pending))
            _save_conversation(run_dir, state, spec, messages)
    else:
        raise RuntimeError("待恢复 Agent 回复与决策历史尾部冲突")
    _clear_pending_agent_text(run_dir, state, spec)
    return messages


def _require_decision_capacity(messages: list[dict[str, str]], spec: AgentDecisionLoopSpec) -> None:
    if count_decisions(messages) >= spec.max_decision_rounds:
        raise RuntimeError("Agent 决策循环达到上限仍未完成")


def _tail_decision(messages: list[dict[str, str]]) -> AgentDecision | None:
    return _decision_at(messages, -1)


def _legacy_completion(messages: list[dict[str, str]], spec: AgentDecisionLoopSpec) -> bool:
    tail = messages[-1]
    return (
        len(messages) >= 2
        and tail["role"] == "assistant"
        and messages[-2]["role"] == "user"
        and tail["content"] in spec.legacy_completion_messages
    )


def _validate_agent_result(
    run_dir: Path,
    state: dict[str, Any],
    workspace: Path,
    spec: AgentDecisionLoopSpec,
    value: ClaudeRunResult,
) -> None:
    def fail(message: str, *, retry_requested: bool = False) -> None:
        _clear_pending_agent_text(run_dir, state, spec)
        failure = persist_agent_failure(
            run_dir,
            state,
            key=spec.key,
            state_key=spec.state_key,
            value=value,
            context={"operation": "validate_agent_result", "validation_message": message},
            retry_requested=retry_requested,
        )
        raise failure

    if value.result_subtype is None:
        fail("Agent SDK 未返回 ResultMessage", retry_requested=value.retry_requested)
    if value.api_error_status is not None:
        fail("Agent SDK API 请求失败", retry_requested=value.retry_requested)
    if value.terminal_reason in _ABORTED_TERMINAL_REASONS:
        fail("Agent SDK 执行已取消")
    if value.result_subtype == "success" and value.terminal_reason not in _NORMAL_TERMINAL_REASONS:
        fail(
            "Agent SDK 正常结果包含不支持的终止原因",
            retry_requested=(
                value.retry_requested
                and value.terminal_reason in _RETRYABLE_TERMINAL_REASONS
            ),
        )
    if value.result_subtype not in {"success", *_RECOVERABLE_SUBTYPES}:
        fail("Agent SDK 返回了不支持的终止结果")
    if value.exception and value.result_subtype not in _RECOVERABLE_SUBTYPES:
        fail("Agent SDK 执行异常", retry_requested=value.retry_requested)
    if value.is_error and value.result_subtype not in _RECOVERABLE_SUBTYPES:
        fail("Agent SDK 执行失败", retry_requested=value.retry_requested)
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
        profile = get_agent_profile(spec.task)
        value = await run_timed_agent(
            agent_runner,
            prompt,
            cwd=workspace,
            resume_session_id=_session(state, spec),
            max_turns=spec.max_turns,
            task=spec.task,
            model=profile.model,
            effort=profile.effort,
            on_update=lambda update: _save_agent_update(run_dir, state, spec, update),
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        retry_requested = bool(getattr(error, "retry_requested", False)) or (
            is_retryable_claude_sdk_error(error)
        )
        failure = persist_agent_failure(
            run_dir,
            state,
            key=spec.key,
            state_key=spec.state_key,
            error=error,
            retry_requested=retry_requested,
        )
        raise AgentExecutionFailure(
            f"Agent SDK 执行异常：{failure}",
            failure.diagnostic_path,
            retry_requested=failure.retry_requested,
        ) from error
    if not isinstance(value, ClaudeRunResult):
        invalid = TypeError("Agent SDK 返回结果不符合约定")
        failure = persist_agent_failure(
            run_dir, state, key=spec.key, state_key=spec.state_key, error=invalid
        )
        raise failure from invalid
    try:
        _save_agent_update(run_dir, state, spec, value)
    except Exception as error:
        failure = persist_agent_failure(
            run_dir,
            state,
            key=spec.key,
            state_key=spec.state_key,
            value=value,
            error=error,
            retry_requested=False,
        )
        raise failure from error
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
        config = config_loader()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        _raise_decision_failure(
            run_dir, state, spec, {"kind": "configuration"}, error
        )

    try:
        data, _attempts, raw = await decision_runner(
            messages,
            config,
            system_prompt=messages[0]["content"],
        )
    except asyncio.CancelledError:
        raise
    except ResponsesFailure as error:
        _raise_decision_failure(run_dir, state, spec, error.diagnostic, error)
    except ValidationError as error:
        _raise_decision_failure(run_dir, state, spec, {"kind": "response"}, error)
    except Exception as error:
        _raise_decision_failure(run_dir, state, spec, {"kind": "internal"}, error)

    try:
        decision = parse_agent_decision(data)
        raw_decision = parse_agent_decision(raw)
    except (TypeError, ValidationError) as error:
        _raise_decision_failure(run_dir, state, spec, {"kind": "response"}, error)
    if not isinstance(raw, str) or decision != raw_decision:
        _raise_decision_failure(run_dir, state, spec, {"kind": "response"})

    messages.append(conversation_message("assistant", raw))
    try:
        _save_conversation(run_dir, state, spec, messages)
    except Exception as error:
        _raise_decision_failure(run_dir, state, spec, {"kind": "internal"}, error)
    _clear_decision_failure(run_dir, state, spec)
    return decision


async def _verify_completed(
    completion_verifier: Callable[[], str | None],
) -> str | None:
    try:
        repair = completion_verifier()
        if inspect.isawaitable(repair):
            repair = await repair
    except asyncio.CancelledError:
        raise
    except Exception as error:
        raise RuntimeError(f"完成核验失败：{redact_text(str(error))}") from error
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
    resume_message: ResumeMessage | None = None,
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
        targeted_resume = (
            resume_message is not None
            and not resume_message.consumed
            and resume_message.target_key == spec.key
        )
        if targeted_resume and (
            _resume_anchor(messages) or _tail_decision(messages) is not None
        ):
            _require_decision_capacity(messages, spec)
            messages.append(conversation_message("assistant", resume_message.content))
            _save_conversation(run_dir, state, spec, messages)
            resume_message.consumed = True
            blocked_resume_pending = False
            messages = await _run_agent(
                run_dir,
                state,
                workspace,
                spec,
                resume_message.content,
                agent_runner,
            )
            continue

        if _legacy_completion(messages, spec):
            repair = await _verify_completed(completion_verifier)
            if repair is None:
                if targeted_resume:
                    raise RuntimeError("负责人消息未能投递到原 blocked 对话")
                return AgentDecision(
                    verdict="completed",
                    answer="",
                    reason="已识别既有完成记录并通过核验",
                    required_inputs=[],
                )
            messages.append(conversation_message("assistant", repair))
            _save_conversation(run_dir, state, spec, messages)
            messages = await _run_agent(
                run_dir, state, workspace, spec, repair, agent_runner
            )
            continue

        decision = _tail_decision(messages)
        if decision is not None:
            _clear_decision_failure(run_dir, state, spec)
            if decision.verdict == "blocked":
                if not blocked_resume_pending:
                    return decision
                blocked_resume_pending = False
                messages.append(conversation_message("assistant", BLOCKED_RESUME_PROMPT))
                _save_conversation(run_dir, state, spec, messages)
                messages = await _run_agent(
                    run_dir, state, workspace, spec, BLOCKED_RESUME_PROMPT, agent_runner
                )
                continue
            if decision.verdict == "completed":
                if _last_agent_requires_normal_completion(state, spec):
                    messages.append(conversation_message("assistant", RECOVERABLE_RESULT_PROMPT))
                    _save_conversation(run_dir, state, spec, messages)
                    messages = await _run_agent(
                        run_dir, state, workspace, spec, RECOVERABLE_RESULT_PROMPT, agent_runner
                    )
                    continue
                repair = await _verify_completed(completion_verifier)
                if repair is None:
                    if targeted_resume:
                        raise RuntimeError("负责人消息未能投递到原 blocked 对话")
                    return decision
                messages.append(conversation_message("assistant", repair))
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
            messages.append(conversation_message("assistant", prompt))
            _save_conversation(run_dir, state, spec, messages)
        else:
            prompt = tail["content"]
        messages = await _run_agent(run_dir, state, workspace, spec, prompt, agent_runner)
