from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from common.openai_responses import request_json_response
from config import LLMConfig

ACTIONS = {"answer", "approve", "continue", "blocked"}
SYSTEM_PROMPT = """你负责处理 Claude Agent 提出的决定。

只返回一个 JSON 对象，字段必须为：
- action: answer、approve、continue、blocked 之一
- answer: 我给 Agent 的明确决定
- reason: 决策理由
- required_inputs: 字符串数组；只有 blocked 时列出解除条件，否则为空数组

你拥有基于当前输入、项目事实、可用工具和已提供资源能够完成的全部产品、技术、文档、流程和执行决策权。存在多个合理方案、资料歧义、重大取舍或不可逆设计决定时，选择一个方案并说明理由，不要因此 blocked。approve 代表我明确同意写入或更新正式产物。

只有缺少模型和当前环境无法取得的不可替代外部资源，例如真实外部账号、凭据、私有数据、客户授权、专用设备、素材、付费服务或线下动作时，才允许 blocked。不得用 Mock、假凭据、虚构资源或降低验收标准消除阻塞。

不要输出密钥、环境变量值或 JSON 之外的文字。"""
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": sorted(ACTIONS)},
        "answer": {"type": "string"},
        "reason": {"type": "string"},
        "required_inputs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["action", "answer", "reason", "required_inputs"],
    "additionalProperties": False,
}


def validate_decision(data: Any) -> dict[str, Any]:
    required = set(DECISION_SCHEMA["required"])
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("决策结果字段不符合约定")
    if data["action"] not in ACTIONS:
        raise ValueError("决策 action 不符合约定")
    if not isinstance(data["answer"], str) or not data["answer"].strip():
        raise ValueError("决策 answer 必须是非空字符串")
    if not isinstance(data["reason"], str) or not data["reason"].strip():
        raise ValueError("决策 reason 必须是非空字符串")
    if not isinstance(data["required_inputs"], list) or not all(
        isinstance(item, str) and item.strip() for item in data["required_inputs"]
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
        except (json.JSONDecodeError, ValueError) as exception:
            error = f"{type(exception).__name__}: {exception}"
    raise ValueError(f"结构化决策在 {max_attempts} 次内持续无效")


async def request_decision(
    messages: list[dict[str, Any]], config: LLMConfig
) -> tuple[dict[str, Any], int, str]:
    async def get_content(attempt: int, previous_error: str | None) -> str:
        current = list(messages)
        if previous_error:
            current.append(
                {
                    "role": "user",
                    "content": f"上一次响应无效：{previous_error}。请严格按 JSON 合同重新回答。",
                }
            )
        return await request_json_response(
            config,
            instructions=SYSTEM_PROMPT,
            input_text=current,
            schema_name="pcm_decision",
            schema=DECISION_SCHEMA,
        )

    decision, attempts = await parse_with_retry(get_content)
    return decision, attempts, json.dumps(decision, ensure_ascii=False)
