from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from common.openai_responses import parse_response
from config import LLMConfig

SYSTEM_PROMPT = """根据给定的 Agent 对话作出明确决定，并填写 verdict、answer、reason 和 required_inputs。

verdict 只能是 completed、continue 或 blocked：
- completed 表示 Agent 已完成可核验的工作；answer 必须为空，required_inputs 必须为空数组。
- continue 表示需要向 Agent 发送下一条明确指令；answer 必须是非空指令，required_inputs 必须为空数组。
- blocked 仅表示缺少当前环境无法取得的真实外部账号、凭据、私有数据、客户授权、专用设备、素材、付费服务或线下动作；answer 必须为空，required_inputs 必须列出非空的解除条件。

reason 必须说明决定依据。你拥有基于当前输入、项目事实、可用工具和已提供资源能够完成的全部产品、技术、文档、流程和执行决策权。存在多个合理方案、资料歧义、重大取舍或不可逆设计决定时，选择一个方案并说明理由，不要因此 blocked。不得用 Mock、假凭据或虚构资源消除阻塞。直接填写结构化输出，不要使用 Markdown 或代码围栏。"""
JSON_FORMAT_PROMPT = """只返回一个严格 JSON 对象：首字符必须是 {，末字符必须是 }，字段名和字符串值必须使用双引号。禁止 YAML 键值行、Markdown、代码围栏和 JSON 之外的任何文本。"""
FORMAT_RETRY_PROMPT = """上一次响应未遵守严格 JSON 格式。本次重新填写全部字段，输出形态必须类似 {"verdict":"continue","answer":"明确指令","reason":"判断依据","required_inputs":[]}。"""
LEGACY_CONTINUE_PROMPT = "请重新核验当前工作和已有产物，继续完成尚未满足的内容并报告结果。"


class DecisionMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["system", "assistant", "user"]
    content: str


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    messages: list[DecisionMessage] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_system_message(self) -> "DecisionInput":
        if self.messages[0].role != "system":
            raise ValueError("决策对话首条消息必须是 system")
        return self


class AgentDecision(BaseModel):
    """Agent 对话循环的唯一结构化决定。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    verdict: Literal["completed", "continue", "blocked"]
    answer: str
    reason: str
    required_inputs: list[str]

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_action(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "verdict" in value or "action" not in value:
            return value
        action = value.get("action")
        verdict = {
            "answer": "continue",
            "approve": "continue",
            "continue": "continue",
            "blocked": "blocked",
        }.get(action)
        if verdict is None:
            return value
        normalized = dict(value)
        normalized.pop("action")
        normalized["verdict"] = verdict
        if verdict == "blocked":
            normalized["answer"] = ""
        elif not isinstance(normalized.get("answer"), str) or not normalized["answer"].strip():
            normalized["answer"] = LEGACY_CONTINUE_PROMPT
        return normalized

    @model_validator(mode="after")
    def validate_fields(self) -> "AgentDecision":
        if not self.reason.strip():
            raise ValueError("reason 不能为空")
        if any(not item.strip() for item in self.required_inputs):
            raise ValueError("required_inputs 不能包含空字符串")
        if self.verdict == "continue":
            if not self.answer.strip():
                raise ValueError("continue 必须提供非空 answer")
            if self.required_inputs:
                raise ValueError("continue 的 required_inputs 必须为空")
        elif self.verdict == "completed":
            if self.answer.strip():
                raise ValueError("completed 的 answer 必须为空")
            if self.required_inputs:
                raise ValueError("completed 的 required_inputs 必须为空")
        else:
            if self.answer.strip():
                raise ValueError("blocked 的 answer 必须为空")
            if not self.required_inputs:
                raise ValueError("blocked 必须提供 required_inputs")
        return self


def parse_agent_decision(value: Any) -> AgentDecision:
    if isinstance(value, str):
        return AgentDecision.model_validate_json(value)
    return AgentDecision.model_validate(value)


def count_decisions(messages: list[dict[str, Any]]) -> int:
    count = 0
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        try:
            parse_agent_decision(message.get("content"))
        except (TypeError, ValidationError):
            continue
        count += 1
    return count


async def request_decision(
    messages: list[dict[str, Any]],
    config: LLMConfig,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    output_model: type[BaseModel] = AgentDecision,
) -> tuple[dict[str, Any], int, str]:
    input_model = DecisionInput.model_validate({"messages": messages})
    attempts = 0
    initial_prompt = f"{system_prompt}\n\n{JSON_FORMAT_PROMPT}"
    for current_prompt in (initial_prompt, f"{initial_prompt}\n\n{FORMAT_RETRY_PROMPT}"):
        attempts += 1
        try:
            decision = await parse_response(
                config,
                system_prompt=current_prompt,
                input_model=input_model,
                output_model=output_model,
            )
        except ValidationError:
            if attempts == 2:
                raise
            continue
        return decision.model_dump(), attempts, decision.model_dump_json()
    raise RuntimeError("决策模型未返回结构化结果")
