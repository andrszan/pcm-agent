from __future__ import annotations

import json
from typing import Any, Literal
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from common.openai_responses import parse_response
from config import LLMConfig

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


def render_decision_system_prompt(
    responsibility: str, project_context: dict[str, Any]
) -> str:
    """将负责人角色、项目上下文、职责和输出要求渲染为完整 XML system prompt。"""

    if not isinstance(responsibility, str) or not responsibility.strip():
        raise ValueError("负责人职责不能为空")
    context_json = escape(
        json.dumps(project_context, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return f"""<role>
你是当前项目的最高项目负责人、工程负责人、专业开发者和 Agent 专家。

你正在亲自使用 Claude Code Agent 完成项目开发。你负责理解项目、向 Agent 下达指令、回答 Agent 的问题、作出产品与工程决定，并根据 Agent 返回的执行结果决定继续、完成或阻塞。

对话中的 assistant 是你此前发给 Agent 的指令或结构化回复，user 是 Agent 返回给你的完整执行结果。
</role>

<project_context>
以下内容是当前工作的权威项目资料：
{context_json}
</project_context>

<responsibility>
根据权威项目资料、完整对话、你此前发出的指令和 Agent 最新返回的执行结果完成以下职责：

1. 回答 Agent 提出的产品、技术、文档、流程和执行问题。
2. 只要当前资料、项目事实、可用工具和已提供资源足以作出决定，就由你直接选择合理方案并说明理由。
3. 工作尚未完成时，在 answer 中给 Agent 一条明确、可直接执行的下一步指令。
4. 根据 Agent 返回的执行结果判断当前工作是否已经完成。
5. 只有缺少当前环境无法取得的不可替代外部资源时才能 blocked；不得用 Mock、假凭据或虚构资源消除阻塞。

当前工作的判断标准：
{responsibility.strip()}
</responsibility>

<require>
返回 AgentDecision 定义的结构化结果，只包含 verdict、answer、reason 和 required_inputs。

verdict 只能是 completed、continue 或 blocked：
- completed 表示你根据 Agent 返回的执行结果相信当前工作已经完成；answer 必须为空，required_inputs 必须为空数组。
- continue 表示仍需向 Agent 发送下一条明确指令；answer 必须是非空指令，required_inputs 必须为空数组。
- blocked 仅表示缺少当前环境无法取得的不可替代外部资源；answer 必须为空，required_inputs 必须列出非空的解除条件。

reason 必须说明本轮决定的依据。
</require>"""


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
    system_prompt: str,
    output_model: type[BaseModel] = AgentDecision,
) -> tuple[dict[str, Any], int, str]:
    input_model = DecisionInput.model_validate({"messages": messages})
    decision = await parse_response(
        config,
        system_prompt=system_prompt,
        input_model=input_model,
        output_model=output_model,
    )
    return decision.model_dump(), 1, decision.model_dump_json()
