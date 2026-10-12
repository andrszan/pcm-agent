from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from claude_agent_sdk import AssistantMessage, ProcessError, SystemMessage, TextBlock
from pydantic import SecretStr

from common import agent_decision_loop as loop
from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import count_decisions
from common.state import read_state, write_state
from common.test_agent_decision_loop import FakeAgentRunner, FakeDecisionRunner, decision
from common.test_agent_handoff import sdk_result
from config import AgentConfig
from steps.step_17_commit.step import _execution_scene


class RecoveryRegressionsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run_dir = Path(temporary.name) / "run"
        self.workspace = Path(temporary.name) / "product"
        self.run_dir.mkdir()
        self.workspace.mkdir()
        self.state = {"status": "running"}
        self.spec = loop.AgentDecisionLoopSpec(
            key="recovery", state_key="recovery", skill_name="test-skill",
            max_decision_rounds=2, max_turns=3, task="project_intake",
            decision_system_prompt="负责人合同",
        )

    def result(self):
        return ClaudeRunResult(
            init={"cwd": str(self.workspace), "skills": [self.spec.skill_name],
                  "slash_commands": [self.spec.skill_name]},
            text="相同完整回复\r\n", result_subtype="success", is_error=False,
            session_id="test-session", stop_reason=None, num_turns=1,
            total_cost_usd=0, exception=None,
        )

    def history(self):
        return json.loads((self.run_dir / loop.conversation_path(self.spec)).read_text())["messages"]

    async def execute(self, agent, judge, verifier=lambda: None):
        return await loop.run_agent_decision_loop(
            self.run_dir, self.state, self.workspace, self.spec, "初始任务", verifier,
            agent_runner=agent, decision_runner=judge, config_loader=lambda: object(),
        )

    async def test_identical_new_replies_consume_rounds_including_callback_recovery(self):
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt):
                self.spec = replace(self.spec, key=f"same_{interrupt}", state_key=f"same_{interrupt}")
                calls = []

                async def agent(prompt, **kwargs):
                    calls.append(prompt)
                    if len(calls) > 2:
                        raise asyncio.CancelledError("重复调用哨兵")
                    value = self.result()
                    kwargs["on_update"](value)
                    if interrupt and len(calls) == 2:
                        raise asyncio.CancelledError("Result 回调后中断")
                    return value

                judge = FakeDecisionRunner([decision("continue", answer="继续核验")] * 2)
                if interrupt:
                    with self.assertRaises(asyncio.CancelledError):
                        await self.execute(agent, judge)
                    self.state = read_state(self.run_dir)
                with self.assertRaisesRegex(RuntimeError, "达到上限"):
                    await self.execute(agent, judge)
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(judge.calls), 2)
                messages = self.history()
                self.assertEqual(count_decisions(messages), 2)
                self.assertEqual([m["content"] for m in messages if m["role"] == "user"],
                                 [self.result().text] * 2)
                self.assertTrue(all("timestamp" in m for m in messages))

    async def sdk_agent(self, prompt, **kwargs):
        return await run_claude(
            prompt, **kwargs, agent_config_loader=lambda: AgentConfig(
                base_url="https://agent.example.invalid", auth_token=SecretStr("test-secret"),
            ),
        )

    async def test_callback_recovery_revalidates_execution_contract(self):
        variants = {
            "valid": {}, "cwd": {"cwd": str(self.run_dir)}, "skills": {"skills": []},
            "slash_commands": {"slash_commands": []}, "model": {"model": "wrong-model"},
        }
        for name, changes in variants.items():
            with self.subTest(name=name):
                self.spec = replace(self.spec, key=name, state_key=name)
                judge = FakeDecisionRunner([decision("completed")])

                async def query(**kwargs):
                    yield SystemMessage(subtype="init", data={
                        "session_id": "test-session", "model": kwargs["options"].model,
                        **self.result().init, **changes,
                    })
                    yield sdk_result(self.result().text)
                    raise asyncio.CancelledError("最终校验前中断")

                with patch("common.claude_agent.query", new=query), patch(
                    "common.claude_agent.load_plugins", return_value=[],
                ):
                    with self.assertRaises(asyncio.CancelledError):
                        await self.execute(self.sdk_agent, judge)
                self.state = read_state(self.run_dir)
                agent = FakeAgentRunner([])
                if name == "valid":
                    self.assertEqual((await self.execute(agent, judge)).verdict, "completed")
                    self.assertEqual(len(judge.calls), 1)
                else:
                    with self.assertRaises(loop.AgentExecutionFailure):
                        await self.execute(agent, judge)
                    self.assertEqual(judge.calls, [])
                    self.assertNotIn("pending_agent_text", self.state[self.spec.state_key])
                    self.assertFalse(any(m["role"] == "user" for m in self.history()))
                self.assertEqual(agent.calls, [])

    async def test_initial_conversation_write_interruption_recovers_step17_scene(self):
        write_state(self.run_dir, self.state)
        agent = FakeAgentRunner([self.result()])
        judge = FakeDecisionRunner([decision("completed")])
        with patch("common.agent_decision_loop.write_state", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.execute(agent, judge)
        self.assertEqual(agent.calls, [])
        self.state = read_state(self.run_dir)
        original = self.history()
        context = {"key": self.spec.key, "development_session_id": "development-session"}
        self.assertTrue(_execution_scene(self.run_dir, self.state, context, self.spec))
        self.assertEqual((await self.execute(agent, judge)).verdict, "completed")
        self.assertEqual(self.history()[:2], original)
        self.assertEqual(len(agent.calls), 1)
        self.assertIsNone(agent.calls[0][1]["resume_session_id"])

    async def test_recoverable_subtypes_reject_model_mismatch_but_allow_trailing_process_error(self):
        for subtype in ("error_max_turns", "error_max_budget_usd"):
            for mismatch in (False, True):
                with self.subTest(subtype=subtype, mismatch=mismatch):
                    self.spec = replace(self.spec, key=f"{subtype}_{mismatch}", state_key=f"{subtype}_{mismatch}")
                    judge = FakeDecisionRunner([decision("blocked", required_inputs=["外部输入"])])

                    async def query(**kwargs):
                        yield SystemMessage(subtype="init", data={
                            "session_id": "test-session", **self.result().init,
                            "model": "wrong-model" if mismatch else kwargs["options"].model,
                        })
                        yield AssistantMessage(content=[TextBlock("尚未完成")], model=kwargs["options"].model)
                        yield sdk_result(None, subtype=subtype, is_error=True)
                        raise ProcessError("结果后的普通进程异常", exit_code=1)

                    with patch("common.claude_agent.query", new=query), patch(
                        "common.claude_agent.load_plugins", return_value=[],
                    ):
                        if mismatch:
                            with self.assertRaises(loop.AgentExecutionFailure):
                                await self.execute(self.sdk_agent, judge)
                            self.assertEqual(judge.calls, [])
                            self.assertEqual(self.state[self.spec.state_key]["last_agent_result"]["exception_type"],
                                             "ModelMismatchError")
                        else:
                            self.assertEqual((await self.execute(self.sdk_agent, judge)).verdict, "blocked")
                            self.assertEqual(len(judge.calls), 1)

    async def test_pending_recovery_preserves_transient_retry_classification(self):
        context_error = (
            "API Error: 400 Your input exceeds the context window of this model. "
            "Please adjust your input and try again."
        )
        cases = (
            ("429", 429, None, None, False, True),
            ("503", 503, None, None, False, True),
            ("blocking", None, "blocking_limit", None, False, True),
            ("400", 400, None, None, False, False),
            ("aborted", 429, "aborted_streaming", None, False, False),
            ("context_window", 400, None, "invalid_request", False, False),
            ("context", 429, None, "invalid_request", False, False),
            ("authentication", 429, None, "authentication_failed", False, False),
            ("wrong_model", 429, None, None, True, False),
        )
        for name, status, terminal, assistant_error, mismatch, expected in cases:
            observed = []
            for interrupt in (False, True):
                with self.subTest(name=name, interrupt=interrupt):
                    key = f"retry_{name}_{interrupt}"
                    self.spec = replace(self.spec, key=key, state_key=key)
                    judge = FakeDecisionRunner([])

                    async def query(**kwargs):
                        yield SystemMessage(subtype="init", data={
                            "session_id": "test-session", **self.result().init,
                            "model": "wrong-model" if mismatch else kwargs["options"].model,
                        })
                        if assistant_error:
                            yield AssistantMessage(
                                content=[TextBlock(context_error if name.startswith("context") else "API Error: 401 authentication failed")],
                                model="<synthetic>", error=assistant_error,
                            )
                        else:
                            yield AssistantMessage(content=[TextBlock("尚未完成")], model=kwargs["options"].model)
                        yield sdk_result(None, subtype="success" if name == "blocking" else "error_during_execution",
                                         is_error=True, api_error_status=status, terminal_reason=terminal)
                        if interrupt:
                            raise asyncio.CancelledError("Result 回调后中断")

                    with patch("common.claude_agent.query", new=query), patch(
                        "common.claude_agent.load_plugins", return_value=[],
                    ):
                        if interrupt:
                            with self.assertRaises(asyncio.CancelledError):
                                await self.execute(self.sdk_agent, judge)
                            self.state = read_state(self.run_dir)
                            if name == "context_window":
                                self.assertTrue(self.state[key]["last_agent_result"]["context_window_exceeded"])
                            if assistant_error:
                                self.assertEqual(self.state[key]["last_agent_result"]["assistant_error"], assistant_error)
                            self.assertNotIn("retry_requested", json.dumps(self.state))
                        with self.assertRaises(loop.AgentExecutionFailure) as raised:
                            await self.execute(FakeAgentRunner([]) if interrupt else self.sdk_agent, judge)
                    observed.append(raised.exception.retry_requested)
                    self.assertEqual(raised.exception.retry_requested, expected)
                    self.assertEqual(judge.calls, [])
                    self.assertNotIn("retry_requested", json.dumps(self.state))
            self.assertEqual(observed[0], observed[1])

    async def test_pending_result_without_init_cannot_reuse_previous_call_identity(self):
        calls = []

        async def agent(prompt, **kwargs):
            calls.append(prompt)
            value = self.result()
            if len(calls) == 2:
                kwargs["on_update"](replace(value, init=None))
                raise asyncio.CancelledError
            return value

        judge = FakeDecisionRunner([decision("continue", answer="补充核验"), decision("completed")])
        with self.assertRaises(asyncio.CancelledError):
            await self.execute(agent, judge)
        self.state = read_state(self.run_dir)
        with self.assertRaises(loop.AgentExecutionFailure):
            await self.execute(FakeAgentRunner([]), judge)
        self.assertEqual(len(judge.calls), 1)
        self.assertEqual(len([m for m in self.history() if m["role"] == "user"]), 1)

    async def test_saved_pending_reply_is_idempotent_and_keeps_timestamp(self):
        agent = FakeAgentRunner([self.result()])
        judge = FakeDecisionRunner([decision("completed")])
        with patch("common.agent_decision_loop._clear_pending_agent_text", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.execute(agent, judge)
        original = self.history()
        self.assertEqual(original[-1]["role"], "user")
        self.state = read_state(self.run_dir)
        self.assertEqual((await self.execute(agent, judge)).verdict, "completed")
        self.assertEqual(self.history()[:-1], original)
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(len(judge.calls), 1)
        self.assertNotIn("pending_agent_text", self.state[self.spec.state_key])

    async def test_recovered_turn_and_budget_results_still_require_normal_completion(self):
        for subtype in ("error_max_turns", "error_max_budget_usd"):
            with self.subTest(subtype=subtype):
                self.spec = replace(self.spec, key=subtype, state_key=subtype)

                async def interrupted(prompt, **kwargs):
                    kwargs["on_update"](replace(
                        self.result(), result_subtype=subtype, is_error=True, has_errors=True,
                        exception="ProcessError", exception_type="ProcessError",
                    ))
                    raise asyncio.CancelledError

                judge = FakeDecisionRunner([decision("completed"), decision("completed")])
                with self.assertRaises(asyncio.CancelledError):
                    await self.execute(interrupted, judge)
                self.state = read_state(self.run_dir)
                agent = FakeAgentRunner([self.result()])
                verifier = Mock(return_value=None)
                self.assertEqual((await self.execute(agent, judge, verifier)).verdict, "completed")
                self.assertEqual(len(judge.calls), 2)
                self.assertEqual([call[0] for call in agent.calls], [loop.RECOVERABLE_RESULT_PROMPT])
                self.assertEqual(agent.calls[0][1]["resume_session_id"], "test-session")
                verifier.assert_called_once()

    def test_scene_does_not_repair_missing_reference_with_execution_facts(self):
        messages = [{"role": "system", "content": "负责人合同"},
                    {"role": "assistant", "content": "初始任务"}]
        path = self.run_dir / loop.conversation_path(self.spec)
        path.parent.mkdir()
        for changes, history in (
            ({"claude_sessions": {self.spec.key: "test-session"}}, messages),
            ({"decision_conversations": {self.spec.key: None}}, messages),
            ({self.spec.state_key: {"init": self.result().init}}, messages),
            ({}, messages + [{"role": "user", "content": "已经执行的回复"}]),
            ({"status": "blocked"}, messages),
        ):
            with self.subTest(changes=changes, history=history):
                path.write_text(json.dumps({"messages": history}, ensure_ascii=False))
                state = {"status": "running", **changes}
                write_state(self.run_dir, state)
                before = (self.run_dir / "state.json").read_bytes()
                with self.assertRaises(RuntimeError):
                    loop.validate_agent_decision_loop_scene(self.run_dir, state, self.spec)
                self.assertEqual((self.run_dir / "state.json").read_bytes(), before)

    async def test_exhausted_repair_keeps_completed_anchor_for_verifier_only_resume(self):
        self.spec = replace(self.spec, max_decision_rounds=1)
        agent = FakeAgentRunner([self.result()])
        judge = FakeDecisionRunner([decision("completed")])
        verifier = Mock(return_value="请补齐产物")
        with self.assertRaisesRegex(RuntimeError, "达到上限"):
            await self.execute(agent, judge, verifier)
        before = self.history()
        self.assertEqual(loop._tail_decision(before), decision("completed"))
        self.state = read_state(self.run_dir)
        verifier.return_value = None
        self.assertEqual((await self.execute(agent, judge, verifier)).verdict, "completed")
        self.assertEqual(verifier.call_count, 2)
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(len(judge.calls), 1)
        self.assertEqual(self.history(), before)
