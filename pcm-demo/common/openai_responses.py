from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal, TypeVar

import openai
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from pydantic import BaseModel, ValidationError

from config import LLMConfig

ParsedModel = TypeVar("ParsedModel", bound=BaseModel)
ResponsesFailureKind = Literal[
    "configuration",
    "transport",
    "http",
    "response",
    "internal",
]
_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_FAILURE_MESSAGES = {
    "configuration": "AI-compatible 配置不可用",
    "transport": "Responses API 连接或请求超时",
    "http": "Responses API HTTP 请求失败",
    "response": "Responses API 响应不符合结构化输出合同",
    "internal": "Responses API 本地处理失败",
}


class ResponsesFailure(RuntimeError):
    def __init__(
        self,
        kind: ResponsesFailureKind,
        *,
        http_status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        diagnostic: dict[str, str | int] = {"kind": kind}
        if type(http_status) is int and 100 <= http_status <= 599:
            diagnostic["http_status"] = http_status
        if isinstance(request_id, str) and _REQUEST_ID.fullmatch(request_id):
            diagnostic["request_id"] = request_id
        self.diagnostic = diagnostic
        message = _FAILURE_MESSAGES[kind]
        if "http_status" in diagnostic:
            message = f"{message}（HTTP {diagnostic['http_status']}）"
        super().__init__(message)


class ResponsesAPIUnsupportedError(ResponsesFailure):
    pass


class ResponsesStructuredOutputUnsupportedError(ResponsesFailure):
    pass


class ResponsesAccessError(ResponsesFailure):
    pass


def _status_diagnostic(error: openai.APIStatusError) -> tuple[int, str | None]:
    body = error.body if isinstance(error.body, Mapping) else {}
    request_id = body.get("request_id") or error.response.headers.get("x-request-id")
    return error.status_code, request_id if isinstance(request_id, str) else None


async def parse_response(
    config: LLMConfig,
    *,
    system_prompt: str,
    input_model: BaseModel,
    output_model: type[ParsedModel],
    max_output_tokens: int = 512,
    max_retries: int = 1,
) -> ParsedModel:
    try:
        client = AsyncOpenAI(
            api_key=config.api_key.get_secret_value(),
            base_url=config.base_url,
            timeout=120.0,
            max_retries=max_retries,
            http_client=DefaultAsyncHttpxClient(trust_env=False),
        )
    except Exception as error:
        raise ResponsesFailure("internal") from error

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
        http_status, request_id = _status_diagnostic(error)
        message = str(error).lower()
        if http_status in {401, 403}:
            raise ResponsesAccessError(
                "http", http_status=http_status, request_id=request_id
            ) from error
        if http_status in {404, 405, 501}:
            raise ResponsesAPIUnsupportedError(
                "http", http_status=http_status, request_id=request_id
            ) from error
        if "text.format" in message or "json_schema" in message:
            raise ResponsesStructuredOutputUnsupportedError(
                "response", http_status=http_status, request_id=request_id
            ) from error
        raise ResponsesFailure(
            "http", http_status=http_status, request_id=request_id
        ) from error
    except (openai.APIResponseValidationError, ValidationError) as error:
        raise ResponsesFailure("response") from error
    except (openai.APIConnectionError, openai.APITimeoutError) as error:
        raise ResponsesFailure("transport") from error
    except Exception as error:
        raise ResponsesFailure("internal") from error
    finally:
        await client.close()

    if response.status != "completed" or response.output_parsed is None:
        raise ResponsesFailure("response")
    return response.output_parsed
