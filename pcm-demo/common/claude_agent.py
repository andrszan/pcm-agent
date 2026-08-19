from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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
        skills="all",
        plugins=load_plugins(cwd),
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
