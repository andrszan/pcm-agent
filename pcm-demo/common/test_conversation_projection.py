from __future__ import annotations

import copy
import json
import tempfile
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch

from pydantic import BaseModel, SecretStr, ValidationError

from common import decision
from common.agent_decision_loop import (
    AgentDecisionLoopSpec,
    agent_conversation_report,
    run_agent_decision_loop,
)
from common.test_openai_responses import Client, Responses
from config import LLMConfig


TIME = "2026-09-08T20:15:30.123456+08:00"


def history():
    context = json.dumps({"report": '<资料>\\"&\r\n' * 40000}, ensure_ascii=False)
    continued = decision.AgentDecision(
        verdict="continue", answer="只补充第二项依据", reason="第一项已确认", required_inputs=[],
    )
    completed = decision.AgentDecision(
        verdict="completed", answer="", reason="补证完成", required_inputs=[],
    )
    return [
        {"role": "system", "content": "冻结的原始 system 快照\n" + context},
        {"role": "assistant", "content": "初始任务\n" + context},
        {"role": "user", "content": "第一项完整成果\r\n第二项结论待补证\n", "timestamp": TIME},
        {"role": "assistant", "content": continued.model_dump_json(), "timestamp": TIME},
        {"role": "user", "content": "第二项局部补证，第一项不变"},
        {"role": "assistant", "content": completed.model_dump_json()},
        {"role": "assistant", "content": "repair：核验发现第二项结论与文件冲突", "timestamp": TIME},
        {"role": "assistant", "content": "人工补充：请以新证据核验，不沿用旧结论"},
        {"role": "user", "content": "撤销第二项旧结论；纠正为新结论 & 保留第一项\r\n", "timestamp": TIME},
    ]


class ConversationProjectionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run_dir = Path(temporary.name)
        self.spec = AgentDecisionLoopSpec(
            key="projection", state_key="projection", skill_name=None, task="project_intake",
            max_decision_rounds=10, max_turns=3, decision_system_prompt="新生成但不得替换旧快照的 system",
        )
        self.path = self.run_dir / "conversations/projection.json"
        self.path.parent.mkdir()
        self.state = {
            "decision_conversations": {self.spec.key: {"path": "conversations/projection.json", "turn": 2}},
            "claude_sessions": {self.spec.key: "original-session"},
        }
        self.config = LLMConfig("https://example.invalid", SecretStr("test-secret"), "test-model")
        self.completed = decision.AgentDecision(
            verdict="completed", answer="", reason="已完成", required_inputs=[],
        )

    def save(self, messages):
        self.path.write_text(json.dumps({"messages": messages}, ensure_ascii=False), encoding="utf-8")
        return self.path.read_bytes()

    def test_large_report_omits_only_initial_context_and_never_writes_history(self):
        messages = history()
        original = self.save(messages)
        state_before = copy.deepcopy(self.state)
        with patch("common.agent_decision_loop.write_state", side_effect=AssertionError("只读投影不能写状态")):
            report = agent_conversation_report(self.run_dir, self.state, self.spec, include_initial_context=False)
        self.assertEqual(json.loads(report), messages[2:])
        self.assertNotIn("冻结的原始 system 快照", report)
        self.assertNotIn("初始任务", report)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.state, state_before)

    def test_default_and_explicit_full_report_remain_identical(self):
        messages = history()
        original = self.save(messages)
        expected = json.dumps(messages, ensure_ascii=False)
        self.assertEqual(agent_conversation_report(self.run_dir, self.state, self.spec), expected)
        self.assertEqual(agent_conversation_report(
            self.run_dir, self.state, self.spec, include_initial_context=True,
        ), expected)
        self.assertEqual(self.path.read_bytes(), original)

    def test_projection_keeps_all_existing_fields_without_rebuilding_messages(self):
        messages = history()
        messages[-1]["existing_metadata"] = {"nested": ["保留原字段"]}
        before = copy.deepcopy(messages)
        projected = decision.project_conversation_messages(messages, include_initial_context=False)
        self.assertEqual(projected, messages[2:])
        self.assertEqual(messages, before)
        self.assertIsNot(projected, messages)

    async def test_default_payload_keeps_legacy_duplicate_initial_context(self):
        messages = history()
        responses = Responses(self.completed.model_dump_json())
        with patch("common.openai_responses.AsyncOpenAI", return_value=Client(responses)):
            await decision.request_decision(messages, self.config, system_prompt=messages[0]["content"])
        payload = responses.initial_calls[0]["input"]
        self.assertEqual(json.dumps(payload, ensure_ascii=False).count("冻结的原始 system 快照"), 2)
        self.assertEqual(json.loads(payload[1]["content"])["messages"][:2], messages[:2])

    async def test_responses_payload_has_old_system_once_and_all_substantive_turns(self):
        messages = history()
        before = copy.deepcopy(messages)
        responses = Responses(self.completed.model_dump_json())
        client = Client(responses)
        with patch("common.openai_responses.AsyncOpenAI", return_value=client):
            result = await decision.request_decision(
                messages, self.config, system_prompt=messages[0]["content"], include_initial_context=False,
            )
        self.assertEqual(result, (self.completed.model_dump(), 1, self.completed.model_dump_json()))
        self.assertEqual(len(responses.initial_calls), 1)
        self.assertEqual(responses.repair_calls, [])
        payload = responses.initial_calls[0]["input"]
        self.assertEqual(payload[0], {"role": "system", "content": messages[0]["content"]})
        self.assertEqual(json.loads(payload[1]["content"]), {"messages": [
            {key: value for key, value in row.items() if key != "timestamp"} for row in messages[2:]
        ]})
        self.assertEqual(json.dumps(payload, ensure_ascii=False).count("冻结的原始 system 快照"), 1)
        self.assertNotIn("初始任务", payload[1]["content"])
        self.assertEqual(messages, before)
        self.assertTrue(client.closed)

    async def test_default_request_retains_full_input_and_custom_output_model(self):
        class Output(BaseModel):
            value: str

        messages = history()
        for options in ({}, {"include_initial_context": True}, {"include_initial_context": False}):
            with self.subTest(options=options):
                with patch("common.decision.parse_response", return_value=Output(value="ok")) as parse:
                    result = await decision.request_decision(
                        messages, self.config, system_prompt="调用者原样快照", output_model=Output, **options,
                    )
                self.assertEqual(result, ({"value": "ok"}, 1, '{"value":"ok"}'))
                kwargs = parse.await_args.kwargs
                self.assertEqual(kwargs["system_prompt"], "调用者原样快照")
                self.assertIs(kwargs["output_model"], Output)
                expected = messages if options.get("include_initial_context", True) else messages[2:]
                self.assertEqual(json.loads(kwargs["input_model"].model_dump_json()), {"messages": [
                    {key: value for key, value in row.items() if key != "timestamp"} for row in expected
                ]})

    async def test_partial_runner_uses_old_snapshot_and_persists_complete_history(self):
        messages = history()
        self.save(messages)
        with patch("common.decision.parse_response", return_value=self.completed) as parse:
            with patch("common.agent_decision_loop.run_timed_agent", side_effect=AssertionError("已有回复不能重跑 Agent")):
                result = await run_agent_decision_loop(
                    self.run_dir, self.state, self.run_dir, self.spec, "新初始任务不能替换历史", lambda: None,
                    decision_runner=partial(decision.request_decision, include_initial_context=False),
                    config_loader=lambda: self.config,
                )
        self.assertEqual(result, self.completed)
        self.assertEqual(parse.await_args.kwargs["system_prompt"], messages[0]["content"])
        self.assertEqual([row.content for row in parse.await_args.kwargs["input_model"].messages],
                         [row["content"] for row in messages[2:]])
        saved = json.loads(self.path.read_text())["messages"]
        self.assertEqual(saved[:-1], messages)
        self.assertEqual(saved[-1]["content"], self.completed.model_dump_json())
        self.assertEqual(self.state["claude_sessions"], {self.spec.key: "original-session"})

    async def test_invalid_or_missing_initial_protocol_fails_without_dropping_replies(self):
        system = {"role": "system", "content": "system"}
        task = {"role": "assistant", "content": "初始任务"}
        reply = {"role": "user", "content": "不能裁掉的 Agent 回复"}
        cases = [[], [system], [reply, task, reply], [system, reply], [system, reply, task],
                 [system, {"role": "assistant", "content": "  "}, reply],
                 [system, {"role": "assistant", "content": 123}, reply],
                 [system, {"role": "system", "content": "不是任务"}, reply],
                 [{"role": "system", "content": ""}, task, reply],
                 [system, None, reply], [system, task],
                 [system, {**task, "timestamp": "invalid"}, reply]]
        for messages in cases:
            with self.subTest(messages=messages):
                before = copy.deepcopy(messages)
                original = self.save(messages)
                state_before = copy.deepcopy(self.state)
                with self.assertRaises((RuntimeError, ValueError)):
                    agent_conversation_report(self.run_dir, self.state, self.spec, include_initial_context=False)
                with patch("common.decision.parse_response") as parse:
                    with self.assertRaises((ValueError, RuntimeError)):
                        await decision.request_decision(
                            messages, self.config, system_prompt="system", include_initial_context=False,
                        )
                parse.assert_not_called()
                self.assertEqual(messages, before)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.state, state_before)

    def test_report_rejects_missing_reference_and_empty_agent_reply(self):
        messages = history()[:2] + [{"role": "user", "content": " \n"}]
        self.save(messages)
        with self.assertRaisesRegex(RuntimeError, "回复正文"):
            agent_conversation_report(self.run_dir, self.state, self.spec, include_initial_context=False)
        with self.assertRaisesRegex(RuntimeError, "历史引用"):
            agent_conversation_report(self.run_dir, {}, self.spec, include_initial_context=False)

    def test_default_input_still_requires_system_first(self):
        with self.assertRaises(ValidationError):
            decision.DecisionInput.model_validate({"messages": [{"role": "user", "content": "回复"}]})
