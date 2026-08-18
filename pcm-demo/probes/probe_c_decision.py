from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.decision import parse_with_retry, request_decision  # noqa: E402
from config import LLMConfig  # noqa: E402


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
    ordinary, ordinary_attempts, _ = await request_decision(
        [
            {
                "role": "user",
                "content": "当前步骤产物已存在，Agent 请求明确授权写入正式文档。请决定。",
            }
        ],
        config,
    )
    boundary, boundary_attempts, _ = await request_decision(
        [
            {
                "role": "user",
                "content": "Agent 完成任务必须取得真实支付商户账号和生产密钥，当前资源清单没有这些资源。请决定。",
            }
        ],
        config,
    )

    parser_retry = await check_parser_retry()
    checks = {
        "config_loaded": bool(config.base_url and config.api_key and config.model),
        "ordinary_approved": ordinary["action"] == "approve",
        "ordinary_has_no_required_inputs": not ordinary["required_inputs"],
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
            "ordinary": {
                "action": ordinary["action"],
                "attempts": ordinary_attempts,
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
