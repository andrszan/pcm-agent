from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from typing import Any, Literal, TypeVar

import openai
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from pydantic import BaseModel, ValidationError

from common.error_diagnostics import exception_diagnostics, redact_text, truncate_text
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
        provider_code: str | None = None,
        provider_type: str | None = None,
        provider_message: str | None = None,
        exception_details: dict[str, Any] | None = None,
    ) -> None:
        diagnostic: dict[str, str | int] = {"kind": kind}
        if type(http_status) is int and 100 <= http_status <= 599:
            diagnostic["http_status"] = http_status
        if isinstance(request_id, str) and _REQUEST_ID.fullmatch(request_id):
            diagnostic["request_id"] = request_id
        for name, value in (
            ("provider_code", provider_code),
            ("provider_type", provider_type),
            ("provider_message", provider_message),
        ):
            if isinstance(value, str) and value:
                diagnostic[name] = truncate_text(value)
        self.diagnostic = diagnostic
        self.exception_details = exception_details
        message = _FAILURE_MESSAGES[kind]
        if "http_status" in diagnostic:
            message = f"{message}（HTTP {diagnostic['http_status']}）"
        details = [
            diagnostic[name]
            for name in ("provider_code", "provider_type", "provider_message")
            if isinstance(diagnostic.get(name), str) and diagnostic[name]
        ]
        if details:
            message = f"{message}：{'；'.join(details)}"
        super().__init__(message)


class ResponsesAPIUnsupportedError(ResponsesFailure):
    pass


class ResponsesStructuredOutputUnsupportedError(ResponsesFailure):
    pass


class ResponsesAccessError(ResponsesFailure):
    pass


def _provider_text(value: Any, known_secrets: list[str]) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return redact_text(str(value), known_secrets=known_secrets)
    return None


def _status_diagnostic(
    error: openai.APIStatusError, known_secrets: list[str]
) -> dict[str, str | int]:
    body = error.body if isinstance(error.body, Mapping) else {}
    body_error = body.get("error") if isinstance(body.get("error"), Mapping) else body
    response = error.response
    headers = getattr(response, "headers", {})
    header_request_id = headers.get("x-request-id") if isinstance(headers, Mapping) else None
    request_id = (
        body.get("request_id")
        or getattr(error, "request_id", None)
        or getattr(response, "request_id", None)
        or header_request_id
    )
    result: dict[str, str | int] = {"http_status": error.status_code}
    if isinstance(request_id, str) and _REQUEST_ID.fullmatch(request_id):
        result["request_id"] = request_id
    for field in ("code", "type", "message"):
        value = body_error.get(field) if isinstance(body_error, Mapping) else None
        if value is None:
            value = getattr(error, field, None)
        text = _provider_text(value, known_secrets)
        if text:
            result[f"provider_{field}"] = text
    if "provider_message" not in result:
        fallback = _provider_text(str(error), known_secrets)
        if fallback:
            result["provider_message"] = fallback
    return result


def _failure_from_error(
    kind: ResponsesFailureKind,
    error: BaseException,
    known_secrets: list[str],
) -> ResponsesFailure:
    return ResponsesFailure(
        kind,
        provider_message=redact_text(str(error), known_secrets=known_secrets),
        exception_details=exception_diagnostics(error, known_secrets=known_secrets),
    )


async def parse_response(
    config: LLMConfig,
    *,
    system_prompt: str,
    input_model: BaseModel,
    output_model: type[ParsedModel],
    max_output_tokens: int = 512,
    max_retries: int = 1,
) -> ParsedModel:
    known_secrets = [config.api_key.get_secret_value()]
    try:
        client = AsyncOpenAI(
            api_key=known_secrets[0],
            base_url=config.base_url,
            timeout=120.0,
            max_retries=max_retries,
            http_client=DefaultAsyncHttpxClient(trust_env=False),
        )
    except Exception as error:
        raise _failure_from_error("internal", error, known_secrets) from error

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
        diagnostic = _status_diagnostic(error, known_secrets)
        exception_details = exception_diagnostics(error, known_secrets=known_secrets)
        message = str(diagnostic.get("provider_message") or "").lower()
        if diagnostic["http_status"] in {401, 403}:
            raise ResponsesAccessError(
                "http", **diagnostic, exception_details=exception_details
            ) from error
        if diagnostic["http_status"] in {404, 405, 501}:
            raise ResponsesAPIUnsupportedError(
                "http", **diagnostic, exception_details=exception_details
            ) from error
        if "text.format" in message or "json_schema" in message:
            raise ResponsesStructuredOutputUnsupportedError(
                "response", **diagnostic, exception_details=exception_details
            ) from error
        raise ResponsesFailure(
            "http", **diagnostic, exception_details=exception_details
        ) from error
    except (openai.APIResponseValidationError, ValidationError) as error:
        raise _failure_from_error("response", error, known_secrets) from error
    except (openai.APIConnectionError, openai.APITimeoutError) as error:
        raise _failure_from_error("transport", error, known_secrets) from error
    except Exception as error:
        raise _failure_from_error("internal", error, known_secrets) from error
    finally:
        active_error = sys.exc_info()[1]
        try:
            await client.close()
        except Exception as error:
            if active_error is None:
                raise _failure_from_error("internal", error, known_secrets) from error

    if response.status != "completed" or response.output_parsed is None:
        raise ResponsesFailure(
            "response",
            provider_message=f"Responses API 返回状态：{redact_text(str(response.status), known_secrets=known_secrets)}",
        )
    return response.output_parsed
