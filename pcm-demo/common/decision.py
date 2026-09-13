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
对话中的 assistant 是你此前发给 Agent 的指令或结构化回复，user 是 Agent 返回给你的完整执行结果。
若 user 正文区分“过程说明”和“最终回复”，以最终回复判断当前状态，过程说明仅补充依据；已被最终回复解决、替代或否定的阶段性计划、失败和疑虑，不再视为当前未完成项。分区内的 XML 转义内容按原文理解；无分区的回复仍按原有方式解释。
</role>

<project_context>
以下内容是当前工作的权威项目资料：
{context_json}
</project_context>

<responsibility>
依据权威项目资料、完整对话和 Agent 最新执行结果：

1. 识别 Agent 是否表达仍需负责人作出决定。除直接问句外，“待确认”“存在冲突”“请拍板”“需要负责人选择或确认”等陈述，以及列出选项后等待选择，只要明确仍需负责人决定，即使没有问号或疑问句也属于未完成的决策请求；已解决的冲突，以及普通风险、假设或观察，不自动成为决策请求。
2. Agent 请求决定时，检查其是否说明准确问题、已核验事实与约束、可行选项及影响、推荐与理由；只有一个可行选项时也须说明。
3. 待决策信息不足时返回 continue，说明你无法直接读取项目文件，并只要求 Agent 在原会话补齐本次决定缺少的具体事实、约束、选项影响或推荐理由；引用不能代替必要事实，不得猜测。answer 不得夹带完善 TRD、重新审查既有工作、扩展设计或执行其它工作的任务。
4. 待决策信息充分时，直接作出选择或确认并说明理由，不上抛普通判断，也不得要求 Agent 再完善材料或复核已经充分的信息。
5. 始终按 completion 段判断当前工作应继续、完成或阻塞；作出信息充分的决定后，也要结合该决定是否仍需 Agent 执行来判断 verdict。普通、明确且尚未完成的工作仍返回 continue，并在 answer 中要求完成该工作；完成报告不因缺少逐项完成复述、“无问题”声明或额外保证而要求继续。
6. 需要继续时，在 answer 中给出与当前缺口或未完成工作直接对应的明确、可执行指令，不扩大当前任务范围。
7. blocked 仅用于缺少当前环境无法取得的不可替代外部资源；不得用 Mock、假凭据或虚构资源消除阻塞。
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
- `continue`：`answer` 必须是非空的下一步指令，`required_inputs` 必须是空数组；Agent 的决策交接不完整时，只能使用该 verdict 要求其在原会话补齐。
- `blocked`：`answer` 必须是空字符串，`required_inputs` 必须是非空数组，列出非空的解除条件。
- `reason` 始终必须是非空字符串，必须说明本轮回复的依据。
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
