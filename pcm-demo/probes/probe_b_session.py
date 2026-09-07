from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
from importlib.metadata import version
from pathlib import Path
from secrets import token_hex
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from model_policy import get_agent_profile  # noqa: E402

STATE_NAME = "state.json"
RESULT_NAME = "result.json"
FACTS_NAME = "facts.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证 Agent SDK 跨进程 session 恢复")
    parser.add_argument("command", choices=("start", "mutate", "resume"))
    parser.add_argument("--run-dir", type=Path, required=True)
    return parser.parse_args()


def filtered_env() -> dict[str, str]:
    env = dict(os.environ)
    if env.get("ANTHROPIC_API_KEY"):
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def sdk_options(
    workspace: Path, *, resume: str | None = None, allow_read: bool = True
) -> ClaudeAgentOptions:
    profile = get_agent_profile("development")
    return ClaudeAgentOptions(
        cwd=workspace,
        setting_sources=[],
        system_prompt={"type": "preset", "preset": "claude_code"},
        tools=["Read"] if allow_read else [],
        allowed_tools=["Read"] if allow_read else [],
        disallowed_tools=["Bash", "Write", "Edit"],
        permission_mode="dontAsk",
        max_turns=3,
        max_budget_usd=1.0,
        model=profile.model,
        effort=profile.effort,
        resume=resume,
        env=filtered_env(),
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


async def run_agent(prompt: str, options: ClaudeAgentOptions) -> dict[str, Any]:
    result: ResultMessage | None = None
    texts: list[str] = []
    tool_uses: list[str] = []
    caught_exception: str | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        texts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_uses.append(block.name)
            elif isinstance(message, ResultMessage):
                result = message
    except Exception as error:
        caught_exception = f"{type(error).__name__}: {error}"

    return {
        "texts": texts,
        "tool_uses": tool_uses,
        "result": None
        if result is None
        else {
            "subtype": result.subtype,
            "is_error": result.is_error,
            "session_id": result.session_id,
            "stop_reason": result.stop_reason,
            "num_turns": result.num_turns,
            "total_cost_usd": result.total_cost_usd,
            "terminal_reason": result.terminal_reason,
        },
        "exception": caught_exception,
    }


def require_new_run_dir(run_dir: Path) -> Path:
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise FileExistsError(f"探针目录已存在，拒绝覆盖：{run_dir}")
    (run_dir / "workspace").mkdir(parents=True)
    return run_dir


def require_state(run_dir: Path, expected_phase: str) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    state_path = run_dir / STATE_NAME
    if not state_path.is_file():
        raise FileNotFoundError(f"缺少探针状态：{state_path}")
    state = read_json(state_path)
    if state.get("phase") != expected_phase:
        raise RuntimeError(
            f"状态阶段不匹配：期望 {expected_phase}，实际 {state.get('phase')}"
        )
    return run_dir, state


async def start(run_dir: Path) -> dict[str, Any]:
    run_dir = require_new_run_dir(run_dir)
    workspace = run_dir / "workspace"
    old_value = f"before-{token_hex(8)}"
    facts = workspace / FACTS_NAME
    facts.write_text(old_value + "\n")

    agent_run = await run_agent(
        "必须使用 Read 工具读取 facts.txt。记住文件中的完整值，之后只回复该值，不要创建或修改文件。",
        sdk_options(workspace),
    )
    result = agent_run["result"] or {}
    text = "\n".join(agent_run["texts"])
    checks = {
        "result_success": result.get("subtype") == "success",
        "facts_read": "Read" in agent_run["tool_uses"],
        "old_value_reported": old_value in text,
        "session_id_captured": bool(result.get("session_id")),
        "facts_unchanged": facts.read_text().strip() == old_value,
        "query_without_exception": agent_run["exception"] is None,
    }
    passed = all(checks.values())
    state = {
        "probe": "B",
        "phase": "started" if passed else "start_failed",
        "start_process_id": os.getpid(),
        "workspace": str(workspace),
        "session_id": result.get("session_id"),
        "old_value": old_value,
        "old_sha256": sha256(facts),
        "start_checks": checks,
        "runtime": {
            "python": platform.python_version(),
            "claude_agent_sdk": version("claude-agent-sdk"),
        },
    }
    write_json(run_dir / STATE_NAME, state)
    return {"status": "passed" if passed else "failed", "checks": checks}


def mutate(run_dir: Path) -> dict[str, Any]:
    run_dir, state = require_state(run_dir, "started")
    if os.getpid() == state["start_process_id"]:
        raise RuntimeError("mutate 必须在独立进程中运行")

    facts = Path(state["workspace"]) / FACTS_NAME
    if sha256(facts) != state["old_sha256"]:
        raise RuntimeError("facts.txt 在 mutate 前已发生意外变化")

    new_value = f"after-{token_hex(8)}"
    facts.write_text(new_value + "\n")
    state.update(
        {
            "phase": "mutated",
            "mutate_process_id": os.getpid(),
            "new_value": new_value,
            "new_sha256": sha256(facts),
        }
    )
    write_json(run_dir / STATE_NAME, state)
    checks = {
        "separate_from_start": os.getpid() != state["start_process_id"],
        "value_changed": new_value != state["old_value"],
        "hash_changed": state["new_sha256"] != state["old_sha256"],
    }
    return {"status": "passed" if all(checks.values()) else "failed", "checks": checks}


async def resume(run_dir: Path) -> dict[str, Any]:
    run_dir, state = require_state(run_dir, "mutated")
    current_pid = os.getpid()
    workspace = Path(state["workspace"])
    facts = workspace / FACTS_NAME

    process_ids = {
        state["start_process_id"],
        state["mutate_process_id"],
        current_pid,
    }
    memory_run = await run_agent(
        "不要使用任何工具。只回复你在上一轮从 facts.txt 读取并回复过的完整值。",
        sdk_options(workspace, resume=state["session_id"], allow_read=False),
    )
    memory_result = memory_run["result"] or {}
    memory_text = "\n".join(memory_run["texts"])

    current_run = await run_agent(
        "必须再次使用 Read 工具读取当前 facts.txt，并只回复当前完整值；不要根据之前的值猜测。",
        sdk_options(workspace, resume=state["session_id"]),
    )
    current_result = current_run["result"] or {}
    current_text = "\n".join(current_run["texts"])
    checks = {
        "three_distinct_processes": len(process_ids) == 3,
        "memory_result_success": memory_result.get("subtype") == "success",
        "current_result_success": current_result.get("subtype") == "success",
        "session_id_preserved": memory_result.get("session_id") == state["session_id"]
        and current_result.get("session_id") == state["session_id"],
        "old_value_remembered": state["old_value"] in memory_text,
        "memory_answer_without_read": "Read" not in memory_run["tool_uses"],
        "facts_reread": "Read" in current_run["tool_uses"],
        "new_value_reported": state["new_value"] in current_text,
        "current_hash_matches_mutation": sha256(facts) == state["new_sha256"],
        "queries_without_exception": memory_run["exception"] is None
        and current_run["exception"] is None,
    }
    final = {
        "probe": "B",
        "status": "passed" if all(checks.values()) else "failed",
        "runtime": state["runtime"],
        "process_ids": {
            "start": state["start_process_id"],
            "mutate": state["mutate_process_id"],
            "resume": current_pid,
        },
        "checks": checks,
        "start_checks": state["start_checks"],
        "session_id": state["session_id"],
        "old_sha256": state["old_sha256"],
        "new_sha256": state["new_sha256"],
        "memory_run": {
            "tool_uses": memory_run["tool_uses"],
            "result": memory_run["result"],
            "exception": memory_run["exception"],
        },
        "current_run": {
            "tool_uses": current_run["tool_uses"],
            "result": current_run["result"],
            "exception": current_run["exception"],
        },
    }
    write_json(run_dir / RESULT_NAME, final)
    if final["status"] == "passed":
        state["phase"] = "resumed"
        write_json(run_dir / STATE_NAME, state)
    return {"status": final["status"], "checks": checks, "result": str(run_dir / RESULT_NAME)}


async def main() -> int:
    args = parse_args()
    if args.command == "start":
        outcome = await start(args.run_dir)
    elif args.command == "mutate":
        outcome = mutate(args.run_dir)
    else:
        outcome = await resume(args.run_dir)

    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
