from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.openai_responses import parse_response
from config import LLMConfig

SYSTEM_PROMPT = """<task>
从产品初稿中提取建立项目工作区所需的最小身份信息。
</task>

<naming_rules>
- 优先使用初稿已经明确给出的仓库名或英文代号。
- 只有初稿没有提供目录名时，才根据明确的产品选题生成目录名。
- 生成的目录名必须是单段小写 kebab-case，只能包含小写字母、数字和连接相邻单词的连字符。
- 不得扩展或虚构无关产品属性。
</naming_rules>

<blocking_rules>
- 只有初稿无法确定明确的产品选题时，才返回 blocked。
- 返回 blocked 时不得猜测产品选题、目录名或目录名来源。
</blocking_rules>

<output>
只返回以下两种形态之一的严格 JSON 对象。

成功时：
{
  "status": "success",
  "topic_name": "初稿中明确的产品选题",
  "project_directory_name": "符合单段小写 kebab-case 的目录名",
  "directory_name_source": "source",
  "reason": "目录名来源或生成理由",
  "blocked_reason": null
}

无法确定明确产品选题时：
{
  "status": "blocked",
  "topic_name": null,
  "project_directory_name": null,
  "directory_name_source": null,
  "reason": null,
  "blocked_reason": "无法确定明确产品选题的具体原因"
}

字段限制：
- status 只能是 success 或 blocked。
- status 为 success 时，topic_name、project_directory_name、directory_name_source 和 reason 必须是非空字符串，blocked_reason 必须为 null。
- directory_name_source 只能是 source 或 generated；初稿明确提供目录名时返回 source，根据产品选题生成目录名时返回 generated。
- status 为 blocked 时，blocked_reason 必须是非空字符串，其余结果字段必须为 null。
- 禁止增加其它字段，也禁止删除或重命名字段。
- 首字符必须是 {，末字符必须是 }。字段名和字符串值必须使用双引号。
- 只返回 JSON 对象；不要返回 Markdown、代码围栏、YAML、注释、分析过程或 JSON 之外的任何文本。
</output>"""


class ProjectIdentityInput(BaseModel):
    product_draft: str = Field(
        min_length=1,
        description="用于确定产品选题和项目目录名的产品输入，可以是一句话想法或已有资料。",
    )


class ProjectIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "blocked"] = Field(
        description="是否已从初稿取得建立工作区所需的完整项目身份。"
    )
    topic_name: str | None = Field(
        description="初稿中明确的产品选题；blocked 时为 null。"
    )
    project_directory_name: str | None = Field(
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="初稿提供或根据明确产品选题生成的单段小写 kebab-case 目录名；blocked 时为 null。",
    )
    directory_name_source: Literal["source", "generated"] | None = Field(
        description="目录名来自初稿时为 source，由模型生成时为 generated；blocked 时为 null。"
    )
    reason: str | None = Field(
        description="目录名来源或生成理由；blocked 时为 null。"
    )
    blocked_reason: str | None = Field(
        description="无法确定明确产品选题时的具体原因；success 时为 null。"
    )

    @field_validator(
        "topic_name",
        "project_directory_name",
        "reason",
        "blocked_reason",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("文本字段必须是非空字符串或 null")
        return value

    @model_validator(mode="after")
    def validate_status_fields(self) -> "ProjectIdentity":
        result_fields = (
            self.topic_name,
            self.project_directory_name,
            self.directory_name_source,
            self.reason,
        )
        if self.status == "success":
            if any(value is None for value in result_fields):
                raise ValueError("success 必须提供完整项目身份")
            if self.blocked_reason is not None:
                raise ValueError("success 的 blocked_reason 必须为 null")
        elif any(value is not None for value in result_fields) or self.blocked_reason is None:
            raise ValueError("blocked 只能提供非空 blocked_reason")
        return self


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
