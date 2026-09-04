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

from common.decision import (  # noqa: E402
    AgentDecision,
    render_decision_system_prompt,
    request_decision,
)
from config import LLMConfig  # noqa: E402

PROBE_DECISION_SYSTEM_PROMPT = render_decision_system_prompt(
    """completed 表示 Agent 的回复足以确认当前工作已经完成。
continue 表示还需要向 Agent 发出明确的完成或收尾指令。
blocked 仅表示完成任务缺少当前环境无法取得的真实外部资源。""",
    {"验证目标": "验证引用式不完整交接必须继续，以及自包含的不可替代外部资源阻塞决定。"},
)


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


async def probe(run_dir: Path) -> dict[str, Any]:
    config = LLMConfig.load()
    incomplete_handoff, incomplete_handoff_attempts, _ = await request_decision(
        [
            {"role": "system", "content": PROBE_DECISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Agent 回复：活动 TRD 已经生成，docs/trd/BR-005.md 第 641 行有五项需要负责人确认，请查看文档后决定。",
            },
        ],
        config,
        system_prompt=PROBE_DECISION_SYSTEM_PROMPT,
    )
    boundary, boundary_attempts, _ = await request_decision(
        [
            {"role": "system", "content": PROBE_DECISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Agent 自包含交接：准确问题是是否在缺少真实支付商户账号和生产密钥时继续完成真实支付验收。任务合同明确要求真实支付商户链路，已核验当前资源清单、受保护配置和可用工具均不包含该账号或密钥，当前环境也无权创建或申请；Mock、假凭据和降低验收标准都不是可行选项。当前约束下唯一实质可行方案是等待调用方提供已授权的账号和密钥，否则无法完成真实支付验收。推荐保持原合同并阻塞，解除条件是提供可用于当前环境的真实支付商户账号和生产密钥。",
            },
        ],
        config,
        system_prompt=PROBE_DECISION_SYSTEM_PROMPT,
    )
    incomplete_handoff_decision = AgentDecision.model_validate(incomplete_handoff)
    boundary_decision = AgentDecision.model_validate(boundary)

    checks = {
        "config_loaded": bool(config.base_url and config.api_key and config.model),
        "incomplete_handoff_continues": incomplete_handoff_decision.verdict == "continue",
        "incomplete_handoff_has_answer": bool(incomplete_handoff_decision.answer.strip()),
        "incomplete_handoff_has_no_required_inputs": not incomplete_handoff_decision.required_inputs,
        "boundary_blocked": boundary_decision.verdict == "blocked",
        "boundary_has_required_inputs": bool(boundary_decision.required_inputs),
        "pydantic_output_parsed": isinstance(incomplete_handoff_decision, AgentDecision)
        and isinstance(boundary_decision, AgentDecision),
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
            "incomplete_handoff": {
                "verdict": incomplete_handoff_decision.verdict,
                "attempts": incomplete_handoff_attempts,
            },
            "boundary": {
                "verdict": boundary_decision.verdict,
                "attempts": boundary_attempts,
                "required_input_count": len(boundary_decision.required_inputs),
            },
        },
    }
    (run_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
