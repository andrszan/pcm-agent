from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from config import LLMConfig

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SYSTEM_PROMPT = """你负责从产品初稿提取第 1 步建立工作区所需的最小项目身份。

只返回一个 JSON 对象，字段必须为：
- topic_name：能够明确表达当前产品选题的非空中文或英文字符串
- project_directory_name：单段小写 kebab-case 文件夹名，只能包含小写字母、数字和连字符
- directory_name_source：source 或 generated；初稿明确给出仓库名或英文代号时用 source，否则可根据选题生成并用 generated
- reason：目录名提取或生成的简短依据
- blocked_reason：如果初稿无法确定明确选题，填写原因；否则必须为 null

不要扩展产品属性，不要输出 JSON 之外的文字。"""


def validate_identity(data: Any) -> dict[str, Any]:
    required = {
        "topic_name",
        "project_directory_name",
        "directory_name_source",
        "reason",
        "blocked_reason",
    }
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("项目身份字段不符合约定")
    if data["blocked_reason"] is not None:
        if not isinstance(data["blocked_reason"], str) or not data["blocked_reason"].strip():
            raise ValueError("blocked_reason 必须是非空字符串或 null")
        return data
    if not isinstance(data["topic_name"], str) or not data["topic_name"].strip():
        raise ValueError("topic_name 必须是非空字符串")
    if not isinstance(data["project_directory_name"], str) or not NAME_PATTERN.fullmatch(
        data["project_directory_name"]
    ):
        raise ValueError("project_directory_name 必须是小写 kebab-case")
    if data["directory_name_source"] not in {"source", "generated"}:
        raise ValueError("directory_name_source 不符合约定")
    if not isinstance(data["reason"], str) or not data["reason"].strip():
        raise ValueError("reason 必须是非空字符串")
    return data


async def parse_with_retry(
    get_content: Callable[[int, str | None], Awaitable[str]], *, max_attempts: int = 2
) -> tuple[dict[str, Any], int]:
    error: str | None = None
    for attempt in range(1, max_attempts + 1):
        content = await get_content(attempt, error)
        try:
            return validate_identity(json.loads(content)), attempt
        except (json.JSONDecodeError, ValueError) as exception:
            error = f"{type(exception).__name__}: {exception}"
    raise ValueError(f"项目身份在 {max_attempts} 次内持续无效")


async def extract_project_identity(
    product_draft: str, config: LLMConfig
) -> tuple[dict[str, Any], int]:
    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=120.0,
        max_retries=1,
        http_client=DefaultAsyncHttpxClient(trust_env=False),
    )

    async def get_content(attempt: int, previous_error: str | None) -> str:
        repair = (
            ""
            if previous_error is None
            else f"\n上一次响应无效：{previous_error}。请严格按 JSON 合同重新回答。"
        )
        response = await client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": product_draft + repair},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("模型返回了空内容")
        return content

    try:
        return await parse_with_retry(get_content)
    finally:
        await client.close()
