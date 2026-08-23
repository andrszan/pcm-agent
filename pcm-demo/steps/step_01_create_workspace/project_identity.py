from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.openai_responses import parse_response
from config import LLMConfig

SYSTEM_PROMPT = """从产品初稿中提取建立项目工作区所需的最小身份信息。

优先使用初稿已经明确给出的仓库名或英文代号。只有初稿没有提供目录名时，才根据产品选题生成单段小写 kebab-case 名称。如果初稿无法确定明确的产品选题，在 blocked_reason 中说明原因。不要扩展无关产品属性。

输出只能包含以下字段，禁止增加其它字段：
- topic_name：明确的产品选题；
- project_directory_name：单段小写 kebab-case 目录名；
- directory_name_source：只能是 source 或 generated；
- reason：目录名来源或生成理由；
- blocked_reason：没有阻塞时为 null，否则为非空字符串。

只返回符合所提供结构化输出格式的严格 JSON 对象；不要使用 Markdown、代码围栏、YAML 或 JSON 之外的文本。"""


class ProjectIdentityInput(BaseModel):
    product_draft: str = Field(min_length=1)


class ProjectIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_name: str = Field(min_length=1)
    project_directory_name: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    directory_name_source: Literal["source", "generated"]
    reason: str = Field(min_length=1)
    blocked_reason: str | None

    @field_validator("topic_name", "project_directory_name", "reason")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value.strip()

    @field_validator("blocked_reason")
    @classmethod
    def strip_blocked_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("blocked_reason 必须是非空字符串或 null")
        return value.strip()


def validate_identity(data: Any) -> dict[str, Any]:
    return ProjectIdentity.model_validate(data).model_dump()


async def extract_project_identity(
    product_draft: str, config: LLMConfig
) -> tuple[dict[str, Any], int]:
    identity = await parse_response(
        config,
        system_prompt=SYSTEM_PROMPT,
        input_model=ProjectIdentityInput(product_draft=product_draft),
        output_model=ProjectIdentity,
    )
    return identity.model_dump(), 1
