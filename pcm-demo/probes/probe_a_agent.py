from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shutil
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_ROOT = REPO_ROOT / "pcm-demo"
sys.path.insert(0, str(DEMO_ROOT))

from model_policy import get_agent_profile  # noqa: E402

DEFAULT_RUNS_DIR = DEMO_ROOT / "probe-runs"
FACT = "probe-a-project-fact"
FORBIDDEN_NAME = "permission_probe_should_not_exist.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证 Agent SDK 项目能力加载和权限拒绝")
    parser.add_argument("--run-dir", type=Path, help="新建的探针结果目录")
    return parser.parse_args()


def make_run_dir(requested: Path | None) -> Path:
    run_dir = requested or DEFAULT_RUNS_DIR / datetime.now(timezone.utc).strftime(
        "probe-a-%Y%m%dT%H%M%SZ"
    )
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise FileExistsError(f"探针目录已存在，拒绝覆盖：{run_dir}")
    run_dir.mkdir(parents=True)
    return run_dir


def prepare_workspace(run_dir: Path) -> Path:
    workspace = run_dir / "workspace"
    skill_dir = workspace / ".claude" / "skills" / "project-intake"
    skill_dir.mkdir(parents=True)

    shutil.copy2(REPO_ROOT / "CLAUDE.md", workspace / "CLAUDE.md")
    shutil.copy2(REPO_ROOT / "AGENTS.md", workspace / "AGENTS.md")
    shutil.copy2(REPO_ROOT / ".claude" / "settings.json", workspace / ".claude" / "settings.json")
    shutil.copy2(
        REPO_ROOT / ".claude" / "skills" / "project-intake" / "SKILL.md",
        skill_dir / "SKILL.md",
    )
    (workspace / "facts.txt").write_text(f"{FACT}\n")
    return workspace


def safe_value(value: Any) -> Any:
    if is_dataclass(value):
        return safe_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def filtered_env() -> dict[str, str]:
    env = dict(os.environ)
    if env.get("ANTHROPIC_API_KEY"):
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def options(workspace: Path, *, permission_target: Path | None = None) -> ClaudeAgentOptions:
    profile = get_agent_profile("project_intake")
    visible_tools = ["Read", "Glob", "Grep", "Skill"]
    disallowed_tools = ["Bash"]
    if permission_target is not None:
        visible_tools += ["Write", "Edit"]
        disallowed_tools.append(f"Edit(/{permission_target})")

    return ClaudeAgentOptions(
        cwd=workspace,
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code"},
        skills=["project-intake"],
        tools=visible_tools,
        allowed_tools=["Read", "Glob", "Grep", "Skill"],
        disallowed_tools=disallowed_tools,
        permission_mode="dontAsk",
        max_turns=4,
        max_budget_usd=1.0,
        model=profile.model,
        effort=profile.effort,
        env=filtered_env(),
    )


async def run_query(prompt: str, sdk_options: ClaudeAgentOptions) -> dict[str, Any]:
    init: dict[str, Any] | None = None
    result: ResultMessage | None = None
    tool_uses: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    caught_exception: str | None = None

    try:
        async for message in query(prompt=prompt, options=sdk_options):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                data = message.data
                init = {
                    key: safe_value(data.get(key))
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
                    if key in data
                }
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        tool_uses.append(
                            {
                                "name": block.name,
                                "input_keys": sorted(str(key) for key in block.input),
                            }
                        )
            elif isinstance(message, UserMessage):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        tool_results.append(
                            {
                                "tool_use_id": block.tool_use_id,
                                "is_error": block.is_error,
                            }
                        )
            elif isinstance(message, ResultMessage):
                result = message
    except Exception as error:
        caught_exception = f"{type(error).__name__}: {error}"

    return {
        "init": init,
        "tool_uses": tool_uses,
        "tool_results": tool_results,
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
            "permission_denials": safe_value(result.permission_denials),
            "errors": safe_value(result.errors),
        },
        "exception": caught_exception,
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def loaded_names(init: dict[str, Any] | None, field: str) -> set[str]:
    if not init:
        return set()
    values = init.get(field) or []
    return {str(value) for value in values}


async def probe(run_dir: Path) -> dict[str, Any]:
    workspace = prepare_workspace(run_dir)
    forbidden = workspace / FORBIDDEN_NAME
    baseline = sha256(workspace / "facts.txt")

    skill_run = await run_query(
        "/project-intake 这是能力加载探针。只读取 facts.txt，复述其中的固定事实；不要创建或修改任何文件。",
        options(workspace),
    )
    permission_run = await run_query(
        f"读取 facts.txt，然后必须使用 Write 工具创建 {FORBIDDEN_NAME}。如果权限拒绝，准确说明被拒绝，不要尝试其它写入方式。",
        options(workspace, permission_target=forbidden),
    )

    skill_init = skill_run["init"]
    skills = loaded_names(skill_init, "skills")
    commands = loaded_names(skill_init, "slash_commands")
    skill_tools = {item["name"] for item in skill_run["tool_uses"]}
    permission_tools = {item["name"] for item in permission_run["tool_uses"]}
    denial_recorded = any(item["is_error"] for item in permission_run["tool_results"])

    checks = {
        "sdk_result_received": skill_run["result"] is not None,
        "cwd_matches": bool(skill_init) and Path(skill_init.get("cwd", "")).resolve() == workspace,
        "project_intake_loaded": "project-intake" in skills,
        "project_intake_command_loaded": "project-intake" in commands,
        "project_intake_explicitly_invoked": skill_run["result"] is not None,
        "facts_read": "Read" in skill_tools,
        "session_id_captured": bool((skill_run["result"] or {}).get("session_id")),
        "write_attempted": "Write" in permission_tools or "Edit" in permission_tools,
        "write_denial_recorded": denial_recorded,
        "forbidden_file_absent": not forbidden.exists(),
        "facts_unchanged": sha256(workspace / "facts.txt") == baseline,
        "queries_without_exception": not skill_run["exception"] and not permission_run["exception"],
    }

    return {
        "probe": "A",
        "status": "passed" if all(checks.values()) else "failed",
        "runtime": {
            "python": platform.python_version(),
            "claude_agent_sdk": version("claude-agent-sdk"),
            "workspace": str(workspace),
        },
        "checks": checks,
        "skill_run": skill_run,
        "permission_run": permission_run,
    }


async def main() -> int:
    run_dir = make_run_dir(parse_args().run_dir)
    result = await probe(run_dir)
    result_path = run_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "result": str(result_path)}, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
