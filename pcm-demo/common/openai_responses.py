from __future__ import annotations

from typing import Any

import openai
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from config import LLMConfig


class ResponsesAPIUnsupportedError(RuntimeError):
    pass


class ResponsesStructuredOutputUnsupportedError(RuntimeError):
    pass


async def request_json(
    client: Any,
    *,
    model: str,
    instructions: str,
    input_text: str,
    schema_name: str,
    schema: dict[str, Any],
) -> str:
    try:
        response = await client.responses.create(
            model=model,
            instructions=instructions,
            input=input_text,
            max_output_tokens=512,
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        )
    except openai.APIStatusError as error:
        message = str(error).lower()
        if error.status_code in {404, 405, 501}:
            raise ResponsesAPIUnsupportedError("服务不支持 Responses API") from error
        if "text.format" in message or "json_schema" in message:
            raise ResponsesStructuredOutputUnsupportedError(
                "服务不支持 Responses API 的 strict JSON Schema"
            ) from error
        raise RuntimeError(f"Responses API 请求失败：HTTP {error.status_code}") from error
    except openai.APIConnectionError as error:
        raise RuntimeError("Responses API 连接失败") from error
    except openai.APITimeoutError as error:
        raise RuntimeError("Responses API 请求超时") from error

    if response.status != "completed":
        raise RuntimeError(f"Responses API 未完成：{response.status}")
    if not response.output_text:
        raise RuntimeError("Responses API 未返回 output_text")
    return response.output_text


async def request_json_response(
    config: LLMConfig,
    *,
    instructions: str,
    input_text: str,
    schema_name: str,
    schema: dict[str, Any],
) -> str:
    client = AsyncOpenAI(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        timeout=120.0,
        max_retries=1,
        http_client=DefaultAsyncHttpxClient(trust_env=False),
    )
    try:
        return await request_json(
            client,
            model=config.model,
            instructions=instructions,
            input_text=input_text,
            schema_name=schema_name,
            schema=schema,
        )
    finally:
        await client.close()
