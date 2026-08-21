from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TypeVar

import openai
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from pydantic import BaseModel

from config import LLMConfig

ParsedModel = TypeVar("ParsedModel", bound=BaseModel)


class ResponsesAPIUnsupportedError(RuntimeError):
    pass


class ResponsesStructuredOutputUnsupportedError(RuntimeError):
    pass


class ResponsesAccessError(RuntimeError):
    pass


def _redact_error_message(message: str) -> str:
    message = re.sub(
        r"(?i)authorization\s*[:=]\s*(?:bearer\s+)?[^\s,;]+",
        "authorization=[REDACTED]",
        message,
    )
    return re.sub(
        r"(?i)(api[-_ ]?key|token|password|secret)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        message,
    )


def _status_error_diagnostics(error: openai.APIStatusError) -> str:
    body = error.body if isinstance(error.body, Mapping) else {}
    payload = body.get("error", body)
    if not isinstance(payload, Mapping):
        payload = {}
    diagnostics = [f"HTTP {error.status_code}"]
    if isinstance(payload.get("code"), str):
        diagnostics.append(f"错误码：{payload['code']}")
    request_id = body.get("request_id") or error.response.headers.get("x-request-id")
    if isinstance(request_id, str):
        diagnostics.append(f"请求 ID：{request_id}")
    if isinstance(payload.get("message"), str):
        diagnostics.append(f"原因：{_redact_error_message(payload['message'])}")
    return "；".join(diagnostics)


async def parse_response(
    config: LLMConfig,
    *,
    system_prompt: str,
    input_model: BaseModel,
    output_model: type[ParsedModel],
    max_output_tokens: int = 512,
    max_retries: int = 1,
) -> ParsedModel:
    client = AsyncOpenAI(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        timeout=120.0,
        max_retries=max_retries,
        http_client=DefaultAsyncHttpxClient(trust_env=False),
    )
    try:
        response = await client.responses.parse(
            model=config.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": input_model.model_dump_json()},
            ],
            text_format=output_model,
            max_output_tokens=max_output_tokens,
        )
    except openai.APIStatusError as error:
        diagnostics = _status_error_diagnostics(error)
        message = str(error).lower()
        if error.status_code in {401, 403}:
            raise ResponsesAccessError(
                f"当前凭据不能访问 Responses API 所需模型（{diagnostics}）"
            ) from error
        if error.status_code in {404, 405, 501}:
            raise ResponsesAPIUnsupportedError(
                f"服务不支持 Responses API（{diagnostics}）"
            ) from error
        if "text.format" in message or "json_schema" in message:
            raise ResponsesStructuredOutputUnsupportedError(
                f"服务不支持 Pydantic 结构化输出（{diagnostics}）"
            ) from error
        raise RuntimeError(f"Responses API 请求失败：{diagnostics}") from error
    except openai.APIConnectionError as error:
        raise RuntimeError("Responses API 连接失败") from error
    except openai.APITimeoutError as error:
        raise RuntimeError("Responses API 请求超时") from error
    finally:
        await client.close()

    if response.status != "completed":
        raise RuntimeError(f"Responses API 未完成：{response.status}")
    if response.output_parsed is None:
        raise RuntimeError("Responses API 未返回结构化结果")
    return response.output_parsed
