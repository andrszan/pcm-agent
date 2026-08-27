from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict, SecretStr

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from config import LLMConfig

from common.openai_responses import ResponsesFailure, parse_response


class InputModel(BaseModel):
    text: str


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: str


class RawResponse:
    def __init__(self, body: dict[str, Any], output_model: type[BaseModel]) -> None:
        self.http_response = SimpleNamespace(json=lambda: body)
        self.body = body
        self.output_model = output_model

    def parse(self) -> object:
        output = self.body["output"][0]["content"][0]["text"]
        parsed = self.output_model.model_validate_json(output)
        return SimpleNamespace(status=self.body["status"], output_parsed=parsed)


class RawResponses:
    def __init__(self, responses: Responses) -> None:
        self.responses = responses

    async def parse(self, **kwargs: Any) -> RawResponse:
        self.responses.initial_calls.append(kwargs)
        return RawResponse(self.responses.body, kwargs["text_format"])


class Responses:
    def __init__(
        self,
        output: str,
        *,
        status: str = "completed",
        repair_output: str | None = None,
    ) -> None:
        self.body = {
            "status": status,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": output}],
                }
            ],
        }
        self.repair_output = output if repair_output is None else repair_output
        self.initial_calls: list[dict[str, Any]] = []
        self.repair_calls: list[dict[str, Any]] = []
        self.with_raw_response = RawResponses(self)

    async def create(self, **kwargs: Any) -> object:
        self.repair_calls.append(kwargs)
        return SimpleNamespace(status="completed", output_text=self.repair_output)


class Client:
    def __init__(self, responses: Responses) -> None:
        self.responses = responses
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class OpenAIResponsesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = LLMConfig(
            "https://example.invalid",
            SecretStr("secret"),
            "test-model",
        )

    def run_parse(self, responses: Responses) -> OutputModel:
        client = Client(responses)
        with patch("common.openai_responses.AsyncOpenAI", return_value=client):
            result = asyncio.run(
                parse_response(
                    self.config,
                    system_prompt="返回结果。",
                    input_model=InputModel(text="input"),
                    output_model=OutputModel,
                    max_retries=0,
                )
            )
        self.assertTrue(client.closed)
        return result

    def test_repairs_invalid_structure_once(self) -> None:
        responses = Responses(
            '{"wrapper":{"value":"ok"}}',
            repair_output='{"value":"ok"}',
        )

        self.assertEqual(self.run_parse(responses), OutputModel(value="ok"))
        self.assertEqual(len(responses.initial_calls), 1)
        self.assertEqual(len(responses.repair_calls), 1)
        repair_input = json.loads(responses.repair_calls[0]["input"][1]["content"])
        self.assertEqual(repair_input["invalid_output"], '{"wrapper":{"value":"ok"}}')
        self.assertIn("properties", repair_input["target_schema"])
        self.assertNotIn("max_output_tokens", responses.initial_calls[0])
        self.assertNotIn("max_output_tokens", responses.repair_calls[0])

    def test_strips_complete_markdown_fence_without_ai_repair(self) -> None:
        responses = Responses('```json\n{"value":"ok"}\n```')

        self.assertEqual(self.run_parse(responses), OutputModel(value="ok"))
        self.assertEqual(len(responses.repair_calls), 0)

    def test_unfixable_output_returns_failure_without_retry(self) -> None:
        responses = Responses('{"wrong":"value"}')

        with self.assertRaises(ResponsesFailure):
            self.run_parse(responses)
        self.assertEqual(len(responses.repair_calls), 1)

    def test_incomplete_output_is_not_repaired(self) -> None:
        responses = Responses('{"value":', status="incomplete")

        with self.assertRaisesRegex(ResponsesFailure, "incomplete"):
            self.run_parse(responses)
        self.assertEqual(len(responses.repair_calls), 0)


if __name__ == "__main__":
    unittest.main()
