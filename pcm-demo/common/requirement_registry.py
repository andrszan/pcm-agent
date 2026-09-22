from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.openai_responses import parse_response
from common.state import is_valid_requirement_id
from config import LLMConfig

SYSTEM_PROMPT = """<task>
从提供的 Backlog 中提取全部且仅有的正式需求。

Backlog 是自由格式的自然语言文档。标题、表格、列表、详情卡、章节和排版方式都只是表达方式，不是识别正式需求的前提。
</task>

<extraction_rules>
- 只提取文档明确纳入正式交付范围的需求。目录、背景、说明、示例、风险、非目标、历史记录、候选项、未来设想和普通引用都不是正式需求。
- 必须覆盖文档中的全部正式需求，每项只输出一次。不得遗漏、合并、拆分、虚构或补充需求；同一需求在多处被引用时不能重复输出。
- id 和 title 必须忠实使用文档明确给出的正式值，不得翻译、改写、缩写、补全、替换或重新编号。
- 优先遵循文档明确给出的正式顺序；没有单独声明顺序时，按各正式需求在文档中首次被完整定义的顺序排列。
- requirements 数组的物理顺序就是正式顺序。order 必须等于数组位置，从 1 开始连续编号到需求总数，不得按依赖、优先级、实现难度或你的判断重新排序。
- depends_on 只能包含文档明确声明为前置依赖的正式需求 ID，并保留文档给出的顺序。
- 未明确声明的前置依赖必须返回空数组。不得根据正文关联、出现先后、业务常识、实现关系或隐含含义猜测依赖。
- 依赖必须使用本次输出中对应需求的准确 id；不得重复、不得引用自身，也不得引用未输出的需求。
- 返回前在内部复核：每个正式需求恰好出现一次，正式需求没有遗漏，order 连续且与数组位置一致，所有依赖都使用输出中的准确 id。不要输出复核过程。
</extraction_rules>

<output>
只返回一个严格 JSON 对象，首字符必须是 {，末字符必须是 }。

顶层必须且只能包含 requirements。requirements 必须是非空数组。
数组中的每一项必须且只能包含以下字段：
- id：非空字符串，格式为 [A-Za-z0-9][A-Za-z0-9_-]*。
- title：文档中的完整非空标题字符串。
- order：从 1 开始且与数组位置相同的连续整数。
- depends_on：前置需求 ID 字符串数组；没有明确依赖时必须是空数组。

禁止增加、删除、重命名或重复字段。禁止返回需求开发状态、完成信息或其它动态字段。
禁止返回 null、Markdown、代码围栏、YAML、注释、解释、分析过程或 JSON 对象之外的任何文本。
</output>"""


class BacklogExtractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backlog_markdown: str = Field(min_length=1)


class RequirementStatic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    order: int = Field(gt=0, strict=True)
    depends_on: list[str]

    @field_validator("id", "title")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("id")
    @classmethod
    def requirement_id_is_safe_path_segment(cls, value: str) -> str:
        if not is_valid_requirement_id(value):
            raise ValueError("需求 ID 不符合路径约定")
        return value

    @field_validator("depends_on")
    @classmethod
    def strip_dependencies(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("依赖 ID 不能为空")
        if any(not is_valid_requirement_id(value) for value in normalized):
            raise ValueError("依赖 ID 不符合路径约定")
        return normalized


class RequirementCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[RequirementStatic] = Field(min_length=1)

def _validate_static_rules(requirements: list[RequirementStatic]) -> None:
    identifiers = [requirement.id for requirement in requirements]
    orders = [requirement.order for requirement in requirements]
    if len(set(identifiers)) != len(identifiers):
        raise RuntimeError("需求 ID 不唯一")
    if len({identifier.casefold() for identifier in identifiers}) != len(identifiers):
        raise RuntimeError("需求 ID 忽略大小写后不唯一")
    if orders != list(range(1, len(requirements) + 1)):
        raise RuntimeError("需求顺序必须与数组位置一致并从 1 连续编号")
    known = set(identifiers)
    graph: dict[str, list[str]] = {}
    for requirement in requirements:
        if len(set(requirement.depends_on)) != len(requirement.depends_on):
            raise RuntimeError("需求依赖不能重复")
        if any(dependency not in known for dependency in requirement.depends_on):
            raise RuntimeError("需求依赖引用不存在")
        if requirement.id in requirement.depends_on:
            raise RuntimeError("需求不能依赖自身")
        graph[requirement.id] = requirement.depends_on

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise RuntimeError("需求依赖存在环")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in graph[identifier]:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in graph:
        visit(identifier)


def validate_catalog(
    value: RequirementCatalog | list[dict[str, Any]] | dict[str, Any],
) -> list[dict[str, Any]]:
    catalog = value if isinstance(value, RequirementCatalog) else RequirementCatalog.model_validate(
        value if isinstance(value, dict) and set(value) == {"requirements"} else {"requirements": value}
    )
    _validate_static_rules(catalog.requirements)
    return [requirement.model_dump(mode="json") for requirement in catalog.requirements]


async def extract_requirements(
    backlog_markdown: str,
    config: LLMConfig,
    *,
    model_runner=parse_response,
) -> RequirementCatalog:
    return await model_runner(
        config,
        system_prompt=SYSTEM_PROMPT,
        input_model=BacklogExtractionInput(backlog_markdown=backlog_markdown),
        output_model=RequirementCatalog,
        max_retries=0,
    )
