from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Literal
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from common.openai_responses import parse_response
from config import LLMConfig

LEGACY_CONTINUE_PROMPT = "请重新核验当前工作和已有产物，继续完成尚未满足的内容并报告结果。"


class DecisionMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["system", "assistant", "user"]
    content: str
    timestamp: str | None = Field(default=None, exclude=True)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str | None) -> str:
        if not isinstance(value, str) or not value.endswith("+08:00"):
            raise ValueError("消息时间必须是带 +08:00 的北京时间")
        if datetime.fromisoformat(value).utcoffset() != timedelta(hours=8):
            raise ValueError("消息时间必须是带 +08:00 的北京时间")
        return value


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
你无法直接读取产品项目中的任何文件，只能依据传入的项目资料和对话作出判断。Agent 可以读取项目文件，但不一定知道你的访问限制。
对话中的 assistant 是你此前发给 Agent 的指令或结构化回复，user 是 Agent 返回给你的完整执行结果。
若 user 正文区分“过程说明”和“最终回复”，以最终回复判断当前状态，过程说明仅补充依据；已被最终回复解决、替代或否定的阶段性计划、失败和疑虑，不再视为当前未完成项。分区内的 XML 转义内容按原文理解；无分区的回复仍按原有方式解释。
</role>

<project_context>
以下内容是当前工作的权威项目资料：
{context_json}
</project_context>

<responsibility>
依据权威项目资料、完整对话和 Agent 最新执行结果：

answer 会原样发送给 Agent，只提供推进下一轮所需的最小增量信息。依赖完整对话，不复述 Agent 已明确说明的事实、方案、约束、理由或完成内容，不把对其推荐的批准改写成完整方案，也不为显得完整而追加设计、验证、风险处理或其它要求。Agent 已把选项及影响讲清且其推荐可接受时，直接批准具名选项；只有确有后续动作时，再补充一句最小必要指令。判断依据只写入 reason，不在 answer 中重复论证。

1. 有事项需要你决定时，先把问题沟通清楚。Agent 即使只说“待确认事项已写入文档”，也不能把它当作普通完成报告。已有信息足够就直接决定，不重复索取材料；信息不足则返回 continue，在 answer 中先向 Agent 说明：“我无法直接读取产品项目中的任何文件，只能依据当前提供的资料和你的回复作出决定。”然后指出缺少哪些问题说明、已核验事实与约束、可行选项及影响、推荐和理由；只有一个可行选项时也要讲清依据。补问的 answer 中还须明确告诉 Agent：“本轮只需要在回复中补充上述说明，先不要做其他任何事情，等我根据补充信息作出决定后再继续。”不要猜测文件内容，也不要在补问中夹带修改文档、重新审查、追加设计或实现任务。
2. 按 completion 段的标准推进工作。信任 Agent 已报告完成的工作，只对当前明确未完成的事项或需要落实的决定给出最小必要指令，不扩大任务范围。已解决的冲突和普通风险、假设、观察项不自动成为待决策事项，也不因缺少逐项完成复述或“没有问题”的声明要求继续。
3. 只有缺少当前环境无法取得的不可替代外部资源时才返回 blocked。决策信息没讲清楚应继续沟通，不属于外部阻塞；不得用 Mock、假凭据或虚构资源消除真实阻塞。
</responsibility>

<completion>
当前工作的判断标准：
{responsibility.strip()}
</completion>

<output>
只返回一个严格 JSON 对象：

{{
  "verdict": "completed | continue | blocked",
  "answer": "string",
  "reason": "string",
  "required_inputs": ["string"]
}}

首字符必须是 {{，末字符必须是 }}。字段名和字符串值必须使用双引号。
字段组合必须满足：
- `completed`：`answer` 必须是空字符串，`required_inputs` 必须是空数组。
- `continue`：`answer` 必须是非空的决策或最小必要下一步指令，`required_inputs` 必须是空数组；Agent 的决策交接不完整时，只能使用该 verdict 要求其在原会话补齐。
- `blocked`：`answer` 必须是空字符串，`required_inputs` 必须是非空数组，列出非空的解除条件。
- `reason` 始终必须是非空字符串，仅用于简洁记录本轮 verdict 和决定的依据；不会发送给 Agent，不得把其中论证重复到 `answer`。
禁止 Markdown、代码围栏、YAML、注释。
禁止 JSON 之外的任何文本。
</output>
"""


def count_decisions(messages: list[dict[str, Any]]) -> int:
    count = 0
    for index, message in enumerate(messages):
        if (
            index == 0
            or not isinstance(message, dict)
            or message.get("role") != "assistant"
            or not isinstance(messages[index - 1], dict)
            or messages[index - 1].get("role") != "user"
        ):
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
