from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

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
from claude_agent_sdk.types import EffortLevel

from common.error_diagnostics import exception_diagnostics, redact_text
from config import AgentConfig

CLAUDE_AGENT_TIMEOUT_SECONDS = 10 * 60 * 60


class _QueryRaisedTimeout(RuntimeError):
    pass


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
    usage: dict[str, Any] | None = None
    model_usage: dict[str, Any] | None = None


def filtered_env(config: AgentConfig, model: str) -> dict[str, str]:
    env = dict(os.environ)
    for name in env:
        if name.startswith(("PCM_", "LLM_")):
            env[name] = ""
        if name in {"ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_MODEL", "ANTHROPIC_SMALL_FAST_MODEL"} or name.startswith((
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_FABLE_MODEL",
            "ANTHROPIC_CUSTOM_MODEL_OPTION",
        )):
            env[name] = ""
    env.update(
        {
            "ANTHROPIC_BASE_URL": config.base_url,
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": config.auth_token.get_secret_value(),
            "CLAUDE_CODE_OAUTH_TOKEN": "",
            "CLAUDE_CODE_OAUTH_REFRESH_TOKEN": "",
            "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR": "",
            "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR": "",
            "CLAUDE_CODE_USE_BEDROCK": "",
            "CLAUDE_CODE_USE_VERTEX": "",
            "CLAUDE_CODE_USE_FOUNDRY": "",
            "CLAUDE_CODE_USE_ANTHROPIC_AWS": "",
            "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD": "",
            "CLAUDE_CODE_USE_MANTLE": "",
            "CLAUDE_CODE_USE_GATEWAY": "",
            "CLAUDE_CODE_SUBAGENT_MODEL": model,
            "LLM_BASE_URL": "",
            "LLM_API_KEY": "",
            "LLM_MODEL": "",
            "LLM_MODEL_EFFORT": "",
            "PCM_MODEL_POLICY_SNAPSHOT": "",
            "PCM_AGENT_BASE_URL": "",
            "PCM_AGENT_AUTH_TOKEN": "",
            "PCM_AGENT_API_KEY": "",
            "PCM_WORKSPACE_ROOT": "",
            "PCM_MAX_CONCURRENT_PROJECTS": "",
            "PCM_TEMPLATE_CATALOG": "",
            "PCM_TEMPLATE_REPOSITORY": "",
            "PCM_AGENT_WORKSPACE_ENV_FILE": "",
            "PCM_DEV_RESOURCE_LIST": "",
            "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0",
        }
    )
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
    if api_error_status is not None or terminal_reason in {"api_error", "blocking_limit"}:
        return True
    return is_retryable_claude_sdk_error(error, has_result=has_result)


def _anthropic_secrets(config: AgentConfig) -> list[str]:
    values = [config.auth_token.get_secret_value()]
    values.extend(
        value
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN")
        if isinstance((value := os.environ.get(key)), str) and value
    )
    return list(dict.fromkeys(values))


def _sdk_errors(value: Any, known_secrets: list[str]) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [redact_text(item, known_secrets=known_secrets) for item in value if isinstance(item, str)] or None


async def run_claude(
    prompt: str,
    *,
    cwd: Path,
    model: str,
    effort: EffortLevel,
    task: str | None = None,
    resume_session_id: str | None = None,
    max_turns: int = 12,
    on_update: Callable[[ClaudeRunResult], None] | None = None,
    agent_config_loader: Callable[[], AgentConfig] | None = None,
) -> ClaudeRunResult:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Agent model 必须是非空真实模型名")
    if effort not in get_args(EffortLevel):
        raise ValueError("Agent effort 必须是 low、medium、high、xhigh 或 max")
    agent_config = (agent_config_loader or AgentConfig.load)()
    init: dict[str, Any] | None = None
    result: ResultMessage | None = None
    texts: list[str] = []
    exception: str | None = None
    exception_type: str | None = None
    exception_details: dict[str, Any] | None = None
    api_error_status: int | None = None
    caught_error: BaseException | None = None
    known_secrets = _anthropic_secrets(agent_config)
    options = ClaudeAgentOptions(
        cwd=cwd,
        system_prompt={"type": "preset", "preset": "claude_code"},
        skills="all",
        setting_sources=["project", "local"],
        # SDK 与插件的标准模型别名统一使用本次策略，不另设子代理档位。
        settings=json.dumps({"modelOverrides": {
            "claude-haiku-4-5-20251001": model,
            "claude-sonnet-4-6": model,
            "claude-opus-4-8": model,
        }}),
        plugins=load_plugins(cwd),
        max_turns=max_turns,
        max_buffer_size=10 * 1024 * 1024,
        resume=resume_session_id,
        model=model,
        effort=effort,
        env=filtered_env(agent_config, model),
    )

    async def guarded_messages():
        try:
            async for message in query(prompt=prompt, options=options):
                yield message
        except TimeoutError as error:
            raise _QueryRaisedTimeout(str(error)) from error

    async def consume_messages() -> None:
        nonlocal init, result
        async for message in guarded_messages():
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
                            usage=result.usage,
                            model_usage=result.model_usage,
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

    try:
        await asyncio.wait_for(
            consume_messages(), timeout=CLAUDE_AGENT_TIMEOUT_SECONDS
        )
    except _QueryRaisedTimeout as wrapped:
        original = wrapped.__cause__ or wrapped
        caught_error = original
        exception_details = exception_diagnostics(original, known_secrets=known_secrets)
        exception = f"TimeoutError: {exception_details['message']}"
        exception_type = "TimeoutError"
    except TimeoutError:
        timeout_error = TimeoutError("Claude Agent SDK 调用超过 10 小时墙钟期限")
        caught_error = timeout_error
        exception_details = exception_diagnostics(
            timeout_error, known_secrets=known_secrets
        )
        exception = f"TimeoutError: {exception_details['message']}"
        exception_type = "TimeoutError"
    except asyncio.CancelledError:
        raise
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
    observed_model = (init or {}).get("model")
    model_mismatch = bool(
        isinstance(observed_model, str)
        and observed_model.casefold() != model.casefold()
    )
    if session_mismatch:
        exception = (
            f"恢复 session ID 不一致：期望 {resume_session_id}，实际 "
            f"{', '.join(sorted(observed_session_ids))}"
        )
        exception_type = "SessionMismatchError"
    elif model_mismatch:
        exception = f"Agent 实际模型不一致：期望 {model}，实际 {observed_model}"
        exception_type = "ModelMismatchError"
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
        usage=result.usage if result else None,
        model_usage=result.model_usage if result else None,
        exception=exception,
        api_error_status=final_api_error_status,
        terminal_reason=final_terminal_reason,
        has_errors=bool(exception)
        or (bool(result.errors) or result.is_error if result else True),
        exception_type=exception_type,
        sdk_errors=_sdk_errors(result.errors if result else None, known_secrets),
        exception_details=exception_details,
        retry_requested=False
        if session_mismatch or model_mismatch
        else _retry_requested(
            api_error_status=final_api_error_status,
            terminal_reason=final_terminal_reason,
            error=caught_error,
            has_result=result is not None,
        ),
    )
