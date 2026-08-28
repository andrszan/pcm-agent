from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    CLIConnectionError,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    SystemMessage,
    TextBlock,
    query,
)

from common.error_diagnostics import exception_diagnostics, redact_text


@dataclass
class ClaudeRunResult:
    init: dict[str, Any] | None
    text: str
    result_subtype: str | None
    is_error: bool
    session_id: str | None
    stop_reason: str | None
    num_turns: int | None
    total_cost_usd: float | None
    exception: str | None
    api_error_status: int | None = None
    terminal_reason: str | None = None
    has_errors: bool = False
    exception_type: str | None = None
    sdk_errors: list[str] | None = None
    exception_details: dict[str, Any] | None = None
    retry_requested: bool = False


def filtered_env() -> dict[str, str]:
    env = dict(os.environ)
    if env.get("ANTHROPIC_API_KEY"):
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env.pop("CLAUDE_CONFIG_DIR", None)
    return env


def load_plugins(cwd: Path) -> list[dict[str, str]]:
    project_root = cwd.resolve()
    lock_path = project_root / "plugins-lock.json"
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"缺少 Claude Plugin 锁文件：{lock_path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Claude Plugin 锁文件不可读取：{lock_path}") from error
    if data.get("version") != 1 or not isinstance(data.get("plugins"), list):
        raise RuntimeError("Claude Plugin 锁文件格式无效")

    plugins: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in data["plugins"]:
        if not isinstance(item, dict):
            raise RuntimeError("Claude Plugin 锁文件包含无效条目")
        plugin_id = item.get("id")
        relative_path = item.get("path")
        if (
            not isinstance(plugin_id, str)
            or not plugin_id
            or plugin_id in seen_ids
            or not isinstance(relative_path, str)
            or not relative_path
        ):
            raise RuntimeError("Claude Plugin 锁文件包含重复或无效条目")
        path = Path(relative_path)
        if path.is_absolute():
            raise RuntimeError(f"Claude Plugin 路径必须是相对路径：{relative_path}")
        resolved = (project_root / path).resolve()
        if resolved != project_root and project_root not in resolved.parents:
            raise RuntimeError(f"Claude Plugin 路径越出项目根目录：{relative_path}")
        if path.is_symlink() or not resolved.is_dir():
            raise RuntimeError(f"Claude Plugin 目录不存在或无效：{relative_path}")
        seen_ids.add(plugin_id)
        plugins.append({"type": "local", "path": str(resolved)})
    return plugins


def _api_error_status(value: Any) -> int | None:
    status = getattr(value, "api_error_status", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status
    return None


def is_retryable_claude_sdk_error(
    error: BaseException | None, *, has_result: bool = False
) -> bool:
    if error is None or has_result or isinstance(error, asyncio.CancelledError):
        return False
    if isinstance(error, CLINotFoundError):
        return False
    return isinstance(error, (CLIConnectionError, ProcessError))


def _retry_requested(
    *,
    api_error_status: int | None,
    terminal_reason: str | None,
    error: BaseException | None = None,
    has_result: bool = False,
) -> bool:
    if terminal_reason in {"aborted_streaming", "aborted_tools"}:
        return False
    if api_error_status is not None or terminal_reason == "api_error":
        return True
    return is_retryable_claude_sdk_error(error, has_result=has_result)


def _anthropic_secrets() -> list[str]:
    return [
        value
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        if isinstance((value := os.environ.get(key)), str) and value
    ]


def _sdk_errors(value: Any, known_secrets: list[str]) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [redact_text(item, known_secrets=known_secrets) for item in value if isinstance(item, str)] or None


async def run_claude(
    prompt: str,
    *,
    cwd: Path,
    resume_session_id: str | None = None,
    max_turns: int = 12,
    max_budget_usd: float = 2.0,
    on_update: Callable[[ClaudeRunResult], None] | None = None,
) -> ClaudeRunResult:
    init: dict[str, Any] | None = None
    result: ResultMessage | None = None
    texts: list[str] = []
    exception: str | None = None
    exception_type: str | None = None
    exception_details: dict[str, Any] | None = None
    api_error_status: int | None = None
    caught_error: BaseException | None = None
    known_secrets = _anthropic_secrets()
    options = ClaudeAgentOptions(
        cwd=cwd,
        system_prompt={"type": "preset", "preset": "claude_code"},
        skills="all",
        plugins=load_plugins(cwd),
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        max_buffer_size=10 * 1024 * 1024,
        resume=resume_session_id,
        env=filtered_env(),
    )

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                init = {
                    key: message.data.get(key)
                    for key in (
                        "session_id",
                        "cwd",
                        "model",
                        "tools",
                        "skills",
                        "slash_commands",
                        "plugins",
                        "permissionMode",
                        "claude_code_version",
                    )
                    if key in message.data
                }
                if on_update:
                    on_update(
                        ClaudeRunResult(
                            init=init,
                            text="",
                            result_subtype=None,
                            is_error=False,
                            session_id=init.get("session_id"),
                            stop_reason=None,
                            num_turns=None,
                            total_cost_usd=None,
                            exception=None,
                        )
                    )
            elif isinstance(message, AssistantMessage):
                texts.extend(
                    block.text for block in message.content if isinstance(block, TextBlock)
                )
            elif isinstance(message, ResultMessage):
                result = message
                if on_update:
                    on_update(
                        ClaudeRunResult(
                            init=init,
                            text=result.result or "\n".join(texts),
                            result_subtype=result.subtype,
                            is_error=result.is_error,
                            session_id=result.session_id,
                            stop_reason=result.stop_reason,
                            num_turns=result.num_turns,
                            total_cost_usd=result.total_cost_usd,
                            exception=None,
                            api_error_status=_api_error_status(result),
                            terminal_reason=result.terminal_reason,
                            has_errors=bool(result.errors) or result.is_error,
                            sdk_errors=_sdk_errors(result.errors, known_secrets),
                            retry_requested=_retry_requested(
                                api_error_status=_api_error_status(result),
                                terminal_reason=result.terminal_reason,
                                has_result=True,
                            ),
                        )
                    )
    except asyncio.CancelledError as error:
        caught_error = error
        exception = "CancelledError"
        exception_type = "CancelledError"
        exception_details = exception_diagnostics(error, known_secrets=known_secrets)
    except Exception as error:  # SDK may raise after yielding a ResultMessage.
        caught_error = error
        exception_details = exception_diagnostics(error, known_secrets=known_secrets)
        exception = f"{type(error).__name__}: {exception_details['message']}"
        exception_type = type(error).__name__
        api_error_status = _api_error_status(error)

    final_session_id = (result.session_id if result else None) or (init or {}).get("session_id")
    observed_session_ids = {
        session_id
        for session_id in ((init or {}).get("session_id"), result.session_id if result else None)
        if session_id
    }
    session_mismatch = bool(
        resume_session_id
        and any(session_id != resume_session_id for session_id in observed_session_ids)
    )
    if session_mismatch:
        exception = (
            f"恢复 session ID 不一致：期望 {resume_session_id}，实际 "
            f"{', '.join(sorted(observed_session_ids))}"
        )
        exception_type = "SessionMismatchError"
    final_api_error_status = (_api_error_status(result) if result else None) or api_error_status
    final_terminal_reason = result.terminal_reason if result else None
    final_text = result.result if result and not result.is_error and result.result else "\n".join(texts)
    return ClaudeRunResult(
        init=init,
        text=final_text,
        result_subtype=result.subtype if result else None,
        is_error=result.is_error if result else True,
        session_id=final_session_id,
        stop_reason=result.stop_reason if result else None,
        num_turns=result.num_turns if result else None,
        total_cost_usd=result.total_cost_usd if result else None,
        exception=exception,
        api_error_status=final_api_error_status,
        terminal_reason=final_terminal_reason,
        has_errors=bool(exception)
        or (bool(result.errors) or result.is_error if result else True),
        exception_type=exception_type,
        sdk_errors=_sdk_errors(result.errors if result else None, known_secrets),
        exception_details=exception_details,
        retry_requested=False
        if session_mismatch
        else _retry_requested(
            api_error_status=final_api_error_status,
            terminal_reason=final_terminal_reason,
            error=caught_error,
            has_result=result is not None,
        ),
    )
