from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI, DefaultAsyncHttpxClient

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.openai_responses import request_json  # noqa: E402
from config import LLMConfig  # noqa: E402

ACTIONS = {"answer", "approve", "continue", "blocked"}
SYSTEM_PROMPT = """你是 PCM Demo 的受限决策器。根据当前步骤、事实和自动决策边界作出一个决定。

只返回一个 JSON 对象，字段必须为：
- action: answer、approve、continue、blocked 之一
- answer: 给 Agent 的简短明确答复
- reason: 决策理由
- required_inputs: 字符串数组；只有 blocked 时列出解除条件，否则为空数组

可以自动决定：不扩大范围的低影响、可逆文档细节，以及完成条件满足后的文档定稿许可。
必须 blocked：改变目标用户或核心闭环、扩大 E.1 范围、新增真实外部服务或账号、重大架构/安全/权限/兼容性/不可逆数据决定、伪造凭据或降低验收标准。
不要输出 API Key、环境变量值或 JSON 之外的文字。"""
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["answer", "approve", "continue", "blocked"]},
        "answer": {"type": "string"},
        "reason": {"type": "string"},
        "required_inputs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["action", "answer", "reason", "required_inputs"],
    "additionalProperties": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证 OpenAI-compatible 结构化决策")
    parser.add_argument("--run-dir", type=Path)
    return parser.parse_args()


def make_run_dir(requested: Path | None) -> Path:
    run_dir = requested or DEMO_ROOT / "probe-runs" / datetime.now(
        timezone.utc
    ).strftime("probe-c-%Y%m%dT%H%M%SZ")
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise FileExistsError(f"探针目录已存在，拒绝覆盖：{run_dir}")
    run_dir.mkdir(parents=True)
    return run_dir


def validate_decision(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("决策结果必须是 JSON 对象")
    required = {"action", "answer", "reason", "required_inputs"}
    if set(data) != required:
        raise ValueError("决策结果字段不符合约定")
    if data["action"] not in ACTIONS:
        raise ValueError("决策 action 不符合约定")
    if not isinstance(data["answer"], str) or not data["answer"]:
        raise ValueError("决策 answer 必须是非空字符串")
    if not isinstance(data["reason"], str) or not data["reason"]:
        raise ValueError("决策 reason 必须是非空字符串")
    if not isinstance(data["required_inputs"], list) or not all(
        isinstance(item, str) and item for item in data["required_inputs"]
    ):
        raise ValueError("决策 required_inputs 必须是字符串数组")
    if data["action"] == "blocked" and not data["required_inputs"]:
        raise ValueError("blocked 决策必须说明 required_inputs")
    if data["action"] != "blocked" and data["required_inputs"]:
        raise ValueError("非 blocked 决策不得包含 required_inputs")
    return data


async def parse_with_retry(
    get_content: Callable[[int, str | None], Awaitable[str]], *, max_attempts: int = 2
) -> tuple[dict[str, Any], int]:
    error: str | None = None
    for attempt in range(1, max_attempts + 1):
        content = await get_content(attempt, error)
        try:
            return validate_decision(json.loads(content)), attempt
        except (json.JSONDecodeError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
    raise ValueError(f"结构化决策在 {max_attempts} 次内持续无效")


async def request_decision(
    client: AsyncOpenAI, config: LLMConfig, decision_context: str
) -> tuple[dict[str, Any], int]:
    async def get_content(attempt: int, previous_error: str | None) -> str:
        repair = (
            ""
            if previous_error is None
            else f"\n上一次响应无效：{previous_error}。请严格按 JSON 合同重新回答。"
        )
        return await request_json(
            client,
            model=config.model,
            instructions=SYSTEM_PROMPT,
            input_text=decision_context + repair,
            schema_name="pcm_decision",
            schema=DECISION_SCHEMA,
        )

    return await parse_with_retry(get_content)


async def check_parser_retry() -> dict[str, Any]:
    responses = iter(
        [
            "not-json",
            json.dumps(
                {
                    "action": "approve",
                    "answer": "允许写入当前工作区文档。",
                    "reason": "这是不扩大产品范围的低影响文档定稿许可。",
                    "required_inputs": [],
                },
                ensure_ascii=False,
            ),
        ]
    )

    async def get_content(attempt: int, previous_error: str | None) -> str:
        assert attempt == 1 or previous_error
        return next(responses)

    decision, attempts = await parse_with_retry(get_content)

    async def always_invalid(attempt: int, previous_error: str | None) -> str:
        assert attempt == 1 or previous_error
        return "not-json"

    exhausted = False
    try:
        await parse_with_retry(always_invalid)
    except ValueError as error:
        exhausted = "2 次" in str(error)

    return {
        "passed": decision["action"] == "approve" and attempts == 2 and exhausted,
        "attempts": attempts,
        "persistent_failure_stopped": exhausted,
    }


async def probe(run_dir: Path) -> dict[str, Any]:
    config = LLMConfig.load()
    client = AsyncOpenAI(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        timeout=120.0,
        max_retries=1,
        http_client=DefaultAsyncHttpxClient(trust_env=False),
    )
    try:
        low_risk, low_attempts = await request_decision(
            client,
            config,
            """当前步骤：第 2 步产品定义。
事实：源 PRD 明确要求项目和维护者文档使用中文；Agent 已完成产品定义两件套并询问是否允许写入工作区。
决定：是否批准写入。该决定不改变用户、核心闭环或 E.1 范围。""",
        )
        boundary, boundary_attempts = await request_decision(
            client,
            config,
            """当前步骤：第 2 步产品定义。
事实：Agent 建议把真实在线支付加入 E.1，并要求提供商户账号和生产支付密钥；源 PRD 的 E.1 不包含支付。
决定：是否自动采纳该建议。""",
        )
    finally:
        await client.close()

    parser_retry = await check_parser_retry()
    checks = {
        "config_loaded": bool(config.base_url and config.api_key and config.model),
        "low_risk_approved": low_risk["action"] == "approve",
        "low_risk_has_no_required_inputs": not low_risk["required_inputs"],
        "boundary_blocked": boundary["action"] == "blocked",
        "boundary_has_required_inputs": bool(boundary["required_inputs"]),
        "parser_retry_bounded": parser_retry["passed"],
    }
    result = {
        "probe": "C",
        "status": "passed" if all(checks.values()) else "failed",
        "runtime": {
            "python": platform.python_version(),
            "model": config.model,
        },
        "checks": checks,
        "decisions": {
            "low_risk": {
                "action": low_risk["action"],
                "attempts": low_attempts,
            },
            "boundary": {
                "action": boundary["action"],
                "attempts": boundary_attempts,
                "required_input_count": len(boundary["required_inputs"]),
            },
            "parser_retry": parser_retry,
        },
    }
    (run_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result


async def main() -> int:
    run_dir = make_run_dir(parse_args().run_dir)
    result = await probe(run_dir)
    print(
        json.dumps(
            {"status": result["status"], "result": str(run_dir / "result.json")},
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
