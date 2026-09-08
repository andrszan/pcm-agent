from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ThinkingBlock, ToolUseBlock
from pydantic import SecretStr, ValidationError

from common.agent_decision_loop import (
    AgentDecisionLoopSpec,
    _append_pending_agent_text,
    _load_conversation,
    _save_agent_update,
    _save_conversation,
    _validate_messages,
    run_agent_decision_loop,
)
from common.claude_agent import run_claude
from common.decision import AgentDecision, DecisionInput, count_decisions, request_decision
from config import AgentConfig


TIME = "2026-09-08T20:15:30.123456+08:00"


def sdk_result(text="最后回复", **overrides):
    return ResultMessage(**{
        "subtype": "success", "duration_ms": 1, "duration_api_ms": 1,
        "is_error": False, "num_turns": 1, "session_id": "test-session",
        "result": text, **overrides,
    })


class AgentHandoffTest(unittest.IsolatedAsyncioTestCase):
    async def run_messages(self, messages):
        async def fake_query(**kwargs):
            for message in messages:
                if isinstance(message, Exception):
                    raise message
                yield message

        updates = []
        with tempfile.TemporaryDirectory() as directory:
            with patch("common.claude_agent.query", new=fake_query), patch(
                "common.claude_agent.load_plugins", return_value=[]
            ):
                result = await run_claude(
                    "当前指令", cwd=Path(directory), model="test-model", effort="low",
                    on_update=updates.append,
                    agent_config_loader=lambda: AgentConfig(
                        base_url="https://agent.example.invalid", auth_token=SecretStr("test-secret")
                    ),
                )
        return result, updates

    async def test_notes_and_final_reach_callback_and_result_without_nested_messages(self):
        result, updates = await self.run_messages([
            AssistantMessage(content=[TextBlock("先前失败，等待修复"),
                ThinkingBlock(thinking="思考不能交接", signature="signature"),
                ToolUseBlock(id="tool", name="Read", input={"secret": "工具参数不能交接"})], model="test-model"),
            AssistantMessage(content=[TextBlock("子代理正文不能交接")], model="test-model", parent_tool_use_id="tool"),
            AssistantMessage(content=[TextBlock("完整依据 <最终回复> & 推荐")], model="test-model"),
            AssistantMessage(content=[TextBlock("已修复，工作完成")], model="test-model"),
            sdk_result("已修复，工作完成"),
        ])
        self.assertIsNone(result.exception)
        self.assertEqual(updates[-1].text, result.text)
        payload = ElementTree.fromstring(f"<reply>{result.text}</reply>")
        self.assertEqual(payload.findtext("过程说明"), "先前失败，等待修复\n完整依据 <最终回复> & 推荐")
        self.assertEqual(payload.findtext("最终回复"), "已修复，工作完成")
        self.assertNotIn("思考不能交接", result.text)
        self.assertNotIn("工具参数不能交接", result.text)
        self.assertNotIn("子代理正文不能交接", result.text)
        with tempfile.TemporaryDirectory() as directory:
            run_dir, state = Path(directory), {}
            spec = AgentDecisionLoopSpec(
                key="handoff", state_key="handoff", skill_name="example", task="project_intake",
                max_decision_rounds=3, max_turns=3, decision_system_prompt="旧system",
            )
            messages = [{"role": "system", "content": "旧system"}, {"role": "assistant", "content": "原指令"}]
            _save_conversation(run_dir, state, spec, messages)
            _save_agent_update(run_dir, state, spec, updates[-1])
            messages = _append_pending_agent_text(run_dir, state, spec, messages)
            self.assertEqual(messages[-1]["content"], result.text)
            _save_agent_update(run_dir, state, spec, result)
            recovered = _append_pending_agent_text(run_dir, state, spec, _load_conversation(run_dir, state, spec))
            self.assertEqual(recovered, messages)
            self.assertEqual(len([m for m in recovered if m["role"] == "user"]), 1)

    async def test_exact_tail_dedup_and_plain_final_compatibility(self):
        cases = [
            ([], "最终", None),
            (["最终"], "最终", None),
            (["第一段", "第二段"], "第一段\n第二段", None),
            (["依据", "第一段", "第二段"], "第一段\n第二段", "依据"),
            (["相同结论", "中间依据"], "相同结论", "相同结论\n中间依据"),
            (["依据\n最终"], "最终", "依据\n最终"),
        ]
        for texts, final, notes in cases:
            with self.subTest(texts=texts):
                result, _ = await self.run_messages([
                    AssistantMessage(content=[TextBlock(text) for text in texts], model="test-model"),
                    sdk_result(final),
                ])
                if notes is None:
                    self.assertEqual(result.text, final)
                else:
                    payload = ElementTree.fromstring(f"<reply>{result.text}</reply>")
                    self.assertEqual(payload.findtext("过程说明"), notes)
                    self.assertEqual(payload.findtext("最终回复"), final)

    async def test_missing_or_failed_result_does_not_label_notes_as_final(self):
        for ending in [sdk_result(None), sdk_result("错误结果", is_error=True), RuntimeError("流中断")]:
            with self.subTest(ending=ending):
                result, _ = await self.run_messages([
                    AssistantMessage(content=[TextBlock("过程一"), TextBlock("过程二")], model="test-model"),
                    ending,
                ])
                self.assertEqual(result.text, "过程一\n过程二")
                if isinstance(ending, Exception):
                    self.assertTrue(result.is_error)
                    self.assertIsNotNone(result.exception)
                elif ending.is_error:
                    self.assertTrue(result.is_error)


class ConversationTimestampTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = Path(self.temp.name) / "run"
        self.run_dir.mkdir()
        self.workspace = Path(self.temp.name) / "product"
        self.workspace.mkdir()
        self.state = {}
        self.spec = AgentDecisionLoopSpec(
            key="example", state_key="example", skill_name="example", task="project_intake",
            max_decision_rounds=3, max_turns=3, decision_system_prompt="冻结的 system",
        )

    async def test_new_messages_timestamp_and_existing_resume_preserves_history(self):
        async def agent(prompt, **kwargs):
            from common.claude_agent import ClaudeRunResult
            return ClaudeRunResult(
                init={"cwd": str(self.workspace), "skills": ["example"], "slash_commands": ["example"]},
                text="完整交接", result_subtype="success", is_error=False,
                session_id="test-session", stop_reason=None, num_turns=1,
                total_cost_usd=0, exception=None,
            )

        async def judge(messages, config, **kwargs):
            value = AgentDecision(verdict="completed", answer="", reason="完成", required_inputs=[])
            return value.model_dump(), 1, value.model_dump_json()

        async def execute():
            return await run_agent_decision_loop(
                run_dir=self.run_dir, state=self.state, workspace=self.workspace,
                spec=self.spec, initial_prompt="初始指令", agent_runner=agent,
                decision_runner=judge, config_loader=lambda: object(), completion_verifier=lambda: None,
            )

        with patch("common.agent_decision_loop.beijing_now", return_value=TIME):
            await execute()
        path = self.run_dir / "conversations/example.json"
        original = path.read_text()
        messages = json.loads(original)["messages"]
        self.assertEqual([m["role"] for m in messages], ["system", "assistant", "user", "assistant"])
        self.assertTrue(all(m["timestamp"] == TIME for m in messages))
        with patch("common.agent_decision_loop.beijing_now", side_effect=AssertionError("旧消息不能重记时间")):
            await execute()
        self.assertEqual(path.read_text(), original)

    def test_old_messages_unchanged_and_pending_timestamp_not_duplicated(self):
        old = [{"role": "system", "content": "旧system"}, {"role": "assistant", "content": "旧指令"}]
        _save_conversation(self.run_dir, self.state, self.spec, old)
        self.assertEqual(_load_conversation(self.run_dir, self.state, self.spec), old)
        self.state["example"] = {"pending_agent_text": "过程与最终的完整交接"}
        with patch("common.agent_decision_loop.beijing_now", return_value=TIME):
            messages = _append_pending_agent_text(self.run_dir, self.state, self.spec, old.copy())
        self.assertEqual(messages[:2], old)
        self.assertEqual(messages[-1]["timestamp"], TIME)
        for with_decision in (False, True):
            history = messages.copy()
            if with_decision:
                history.append({"role": "assistant", "content": json.dumps({
                    "verdict": "completed", "answer": "", "reason": "完成", "required_inputs": [],
                }), "timestamp": TIME})
            self.state["example"]["pending_agent_text"] = messages[-1]["content"]
            with patch("common.agent_decision_loop.beijing_now", side_effect=AssertionError("重放不能新增消息")):
                self.assertEqual(_append_pending_agent_text(self.run_dir, self.state, self.spec, history), history)
        self.assertEqual(count_decisions(history), 1)

    async def test_request_decision_excludes_timestamp_but_keeps_full_content(self):
        messages = [
            {"role": "system", "content": "冻结system"},
            {"role": "user", "content": "过程说明及最终回复", "timestamp": TIME},
        ]
        async def parse(config, *, system_prompt, input_model, output_model):
            self.assertEqual(system_prompt, "冻结system")
            self.assertEqual(json.loads(input_model.model_dump_json()), {"messages": [
                messages[0], {"role": "user", "content": messages[1]["content"]},
            ]})
            return AgentDecision(verdict="completed", answer="", reason="完成", required_inputs=[])
        with patch("common.decision.parse_response", new=parse):
            await request_decision(messages, object(), system_prompt="冻结system")
        self.assertEqual(messages[1]["timestamp"], TIME)

    def test_deterministic_repository_recovery_stamps_only_new_message(self):
        from steps.step_08_initialize_repositories.step import _record_recovered_completion
        path = self.run_dir / "conversations/initialize_repositories.json"
        path.parent.mkdir()
        old = [{"role": "system", "content": "旧system"}, {"role": "user", "content": "已完成提交"}]
        path.write_text(json.dumps({"messages": old}, ensure_ascii=False))
        with patch("common.agent_decision_loop.beijing_now", return_value=TIME):
            _record_recovered_completion(self.run_dir, self.state)
        saved = path.read_text()
        history = json.loads(saved)["messages"]
        self.assertEqual(history[:-1], old)
        self.assertEqual(history[-1]["timestamp"], TIME)
        with patch("common.agent_decision_loop.beijing_now", side_effect=AssertionError("不能重记")):
            _record_recovered_completion(self.run_dir, self.state)
        self.assertEqual(path.read_text(), saved)

    def test_timestamp_validation_and_api_serialization(self):
        legacy = {"role": "system", "content": "旧system"}
        current = {"role": "user", "content": "回复", "timestamp": TIME}
        self.assertEqual(_validate_messages([legacy, current]), [legacy, current])
        payload = json.loads(DecisionInput.model_validate({"messages": [legacy, current]}).model_dump_json())
        self.assertEqual(payload, {"messages": [legacy, {"role": "user", "content": "回复"}]})
        for value in [None, "", "2026-09-08", "2026-09-08T12:15:30+00:00", 123]:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                _validate_messages([legacy, {**current, "timestamp": value}])
        with self.assertRaises(RuntimeError):
            _validate_messages([{**legacy, "unknown": "不能静默丢弃"}])
        with self.assertRaises(ValidationError):
            DecisionInput.model_validate({"messages": [{**legacy, "unknown": "不接受"}]})
