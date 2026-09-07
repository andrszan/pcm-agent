from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict, SecretStr

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from config import LLMConfig

from common import timing
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
            "id": "resp-primary",
            "status": status,
            "usage": {"input_tokens": 11, "output_tokens": 7},
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
        usage = SimpleNamespace(model_dump=lambda: {"input_tokens": 5, "output_tokens": 3})
        return SimpleNamespace(
            id="resp-repair",
            status="completed",
            output_text=self.repair_output,
            usage=usage,
        )


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

    def run_parse_timed(
        self, responses: Responses,
    ) -> tuple[OutputModel | None, Exception | None, dict[str, Any]]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        run_dir = Path(directory.name)
        client = Client(responses)
        clock = timing.StepTiming()
        clock.begin_attempt(0)
        clock.bind_run(run_dir)
        result = None
        error = None
        with clock.activate(), patch("common.openai_responses.AsyncOpenAI", return_value=client):
            try:
                result = asyncio.run(
                    parse_response(
                        self.config,
                        system_prompt="返回结果。",
                        input_model=InputModel(text="input"),
                        output_model=OutputModel,
                        max_retries=0,
                    )
                )
            except Exception as caught:  # noqa: BLE001 - 测试同时核验失败及旁路记录。
                error = caught
        record = json.loads((run_dir / "timings.json").read_text())["steps"][0]
        self.assertTrue(client.closed)
        return result, error, record

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
        self.assertNotIn("reasoning", responses.initial_calls[0])
        self.assertNotIn("reasoning", responses.repair_calls[0])

    def test_primary_and_repair_record_raw_usage_and_effort(self) -> None:
        self.config = LLMConfig(
            "https://example.invalid", SecretStr("secret"), "test-model", "high"
        )
        responses = Responses('{"wrapper":{"value":"ok"}}', repair_output='{"value":"ok"}')

        result, error, record = self.run_parse_timed(responses)

        self.assertIsNone(error)
        self.assertEqual(result, OutputModel(value="ok"))
        self.assertEqual(responses.initial_calls[0]["reasoning"], {"effort": "high"})
        self.assertEqual(responses.repair_calls[0]["reasoning"], {"effort": "high"})
        primary, repair = record["ai_executions"]
        self.assertEqual(
            (primary["model"], primary["effort"], primary["kind"]),
            ("test-model", "high", "primary"),
        )
        self.assertEqual(primary["usage"], {"input_tokens": 11, "output_tokens": 7})
        self.assertEqual(primary["response_id"], "resp-primary")
        self.assertEqual(primary["status"], "completed")
        self.assertEqual(
            (repair["model"], repair["effort"], repair["kind"]),
            ("test-model", "high", "repair"),
        )
        self.assertEqual(repair["usage"], {"input_tokens": 5, "output_tokens": 3})
        self.assertEqual(repair["response_id"], "resp-repair")
        self.assertEqual(repair["status"], "completed")
        self.assertTrue(all(call["finished_at"] for call in (primary, repair)))
        self.assertEqual(record["agent_elapsed_seconds"], 0)

    def test_strips_complete_markdown_fence_without_ai_repair(self) -> None:
        responses = Responses('```json\n{"value":"ok"}\n```')

        result, error, record = self.run_parse_timed(responses)
        self.assertIsNone(error)
        self.assertEqual(result, OutputModel(value="ok"))
        self.assertEqual(len(responses.repair_calls), 0)
        primary, = record["ai_executions"]
        self.assertEqual(primary["usage"], {"input_tokens": 11, "output_tokens": 7})

    def test_unfixable_output_returns_failure_without_retry(self) -> None:
        responses = Responses('{"wrong":"value"}')

        result, error, record = self.run_parse_timed(responses)
        self.assertIsNone(result)
        self.assertIsInstance(error, ResponsesFailure)
        self.assertEqual(len(responses.repair_calls), 1)
        self.assertEqual(len(record["ai_executions"]), 2)
        self.assertEqual(record["ai_executions"][0]["usage"]["input_tokens"], 11)
        self.assertEqual(record["ai_executions"][1]["usage"]["input_tokens"], 5)

    def test_incomplete_output_is_not_repaired(self) -> None:
        responses = Responses('{"value":', status="incomplete")

        result, error, record = self.run_parse_timed(responses)
        self.assertIsNone(result)
        self.assertIsInstance(error, ResponsesFailure)
        self.assertIn("incomplete", str(error))
        self.assertEqual(len(responses.repair_calls), 0)
        primary, = record["ai_executions"]
        self.assertEqual(primary["usage"], {"input_tokens": 11, "output_tokens": 7})
        self.assertEqual(primary["status"], "incomplete")

    def test_request_exception_records_unknown_usage(self) -> None:
        responses = Responses('{"value":"unused"}')

        async def fail(**kwargs: Any) -> RawResponse:
            responses.initial_calls.append(kwargs)
            raise RuntimeError("request failed")

        responses.with_raw_response.parse = fail
        result, error, record = self.run_parse_timed(responses)

        self.assertIsNone(result)
        self.assertIsInstance(error, ResponsesFailure)
        primary, = record["ai_executions"]
        self.assertIsNone(primary["usage"])
        self.assertIsNone(primary["response_id"])
        self.assertIsNone(primary["status"])
        self.assertIsNotNone(primary["finished_at"])

    def test_timing_write_failure_does_not_change_parsed_result(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        run_dir = Path(directory.name)
        clock = timing.StepTiming()
        clock.begin_attempt(0)
        clock.bind_run(run_dir)
        responses = Responses('{"value":"ok"}')
        client = Client(responses)

        with (
            clock.activate(),
            patch("common.openai_responses.AsyncOpenAI", return_value=client),
            patch("common.timing.write_json", side_effect=OSError("旁路写入失败")),
        ):
            result = asyncio.run(
                parse_response(
                    self.config,
                    system_prompt="返回结果。",
                    input_model=InputModel(text="input"),
                    output_model=OutputModel,
                    max_retries=0,
                )
            )

        self.assertEqual(result, OutputModel(value="ok"))
        self.assertTrue(clock.disabled)


if __name__ == "__main__":
    unittest.main()
