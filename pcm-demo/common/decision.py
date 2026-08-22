from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from common.openai_responses import parse_response
from config import LLMConfig

SYSTEM_PROMPT = """根据给定的 Agent 决策上下文作出明确决定，并填写输出模型中的 action、answer、reason 和 required_inputs。

你拥有基于当前输入、项目事实、可用工具和已提供资源能够完成的全部产品、技术、文档、流程和执行决策权。存在多个合理方案、资料歧义、重大取舍或不可逆设计决定时，选择一个方案并说明理由，不要因此 blocked。approve 代表明确同意写入或更新正式产物。

只有缺少当前环境无法取得的真实外部账号、凭据、私有数据、客户授权、专用设备、素材、付费服务或线下动作时，才使用 blocked，并在 required_inputs 中列出解除条件；其他 action 的 required_inputs 为空数组。不得用 Mock、假凭据或虚构资源消除阻塞。直接填写结构化输出，不要使用 Markdown 或代码围栏。"""


class DecisionMessage(BaseModel):
    role: str
    content: str


class DecisionInput(BaseModel):
    messages: list[DecisionMessage] = Field(min_length=1)


class Decision(BaseModel):
    action: Literal["answer", "approve", "continue", "blocked"]
    answer: str
    reason: str
    required_inputs: list[str]


async def request_decision(
    messages: list[dict[str, Any]],
    config: LLMConfig,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    output_model: type[BaseModel] = Decision,
) -> tuple[dict[str, Any], int, str]:
    decision = await parse_response(
        config,
        system_prompt=system_prompt,
        input_model=DecisionInput.model_validate({"messages": messages}),
        output_model=output_model,
    )
    data = decision.model_dump()
    return data, 1, decision.model_dump_json()
