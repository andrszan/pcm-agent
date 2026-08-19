from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    query,
)


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


def filtered_env() -> dict[str, str]:
    env = dict(os.environ)
    if env.get("ANTHROPIC_API_KEY"):
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env.pop("CLAUDE_CONFIG_DIR", None)
    return env


async def run_claude(
    prompt: str,
    *,
    cwd: Path,
    skill: str,
    resume_session_id: str | None = None,
    max_turns: int = 12,
    max_budget_usd: float = 2.0,
    on_update: Callable[[ClaudeRunResult], None] | None = None,
) -> ClaudeRunResult:
    init: dict[str, Any] | None = None
    result: ResultMessage | None = None
    texts: list[str] = []
    exception: str | None = None
    options = ClaudeAgentOptions(
        cwd=cwd,
        system_prompt={"type": "preset", "preset": "claude_code"},
        skills=[skill],
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
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
                        )
                    )
    except Exception as error:  # SDK may raise after yielding a ResultMessage.
        exception = f"{type(error).__name__}: {error}"

    final_session_id = (result.session_id if result else None) or (init or {}).get("session_id")
    observed_session_ids = {
        session_id
        for session_id in ((init or {}).get("session_id"), result.session_id if result else None)
        if session_id
    }
    if resume_session_id and any(
        session_id != resume_session_id for session_id in observed_session_ids
    ):
        exception = (
            f"恢复 session ID 不一致：期望 {resume_session_id}，实际 "
            f"{', '.join(sorted(observed_session_ids))}"
        )
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
    )
