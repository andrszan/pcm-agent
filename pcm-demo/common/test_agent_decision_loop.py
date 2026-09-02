from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import (
    CLIConnectionError,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    SystemMessage,
)
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.agent_decision_loop import (  # noqa: E402
    BLOCKED_RESUME_PROMPT,
    RECOVERABLE_RESULT_PROMPT,
    AIDecisionFailure,
    AgentExecutionFailure,
    AgentDecisionLoopSpec,
    persist_agent_failure,
    run_agent_decision_loop,
)
from common.claude_agent import ClaudeRunResult, filtered_env, run_claude  # noqa: E402
from common.decision import (  # noqa: E402
    LEGACY_CONTINUE_PROMPT,
    AgentDecision,
    count_decisions,
    parse_agent_decision,
    render_decision_system_prompt,
    request_decision,
)
from common.openai_responses import ResponsesFailure  # noqa: E402
from common.files import write_json  # noqa: E402
from config import AgentConfig  # noqa: E402


class FakeAgentRunner:
    def __init__(self, results: list[ClaudeRunResult]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __call__(self, prompt: str, **kwargs: object) -> ClaudeRunResult:
        self.calls.append((prompt, kwargs))
        return next(self.results)


class FakeDecisionRunner:
    def __init__(self, decisions: list[AgentDecision]) -> None:
        self.decisions = iter(decisions)
        self.calls: list[tuple[list[dict[str, str]], object, str]] = []

    async def __call__(
        self,
        messages: list[dict[str, str]],
        config: object,
        *,
        system_prompt: str,
    ) -> tuple[dict[str, object], int, str]:
        self.calls.append((copy.deepcopy(messages), config, system_prompt))
        decision = next(self.decisions)
        return decision.model_dump(), 1, decision.model_dump_json()


def decision(
    verdict: str,
    *,
    answer: str = "",
    reason: str = "已核验",
    required_inputs: list[str] | None = None,
) -> AgentDecision:
    return AgentDecision(
        verdict=verdict,
        answer=answer,
        reason=reason,
        required_inputs=required_inputs or [],
    )


class AgentDecisionLoopTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temporary_directory.name) / "run"
        self.workspace = Path(self.temporary_directory.name) / "workspace"
        self.run_dir.mkdir()
        self.workspace.mkdir()
        self.state: dict[str, object] = {}
        self.spec = AgentDecisionLoopSpec(
            key="test_conversation",
            state_key="test_step",
            skill_name="test-skill",
            max_decision_rounds=3,
            max_turns=7,
            model_tier="medium",
            effort="high",
            decision_system_prompt="决策 system prompt",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_spec_requires_supported_model_tier_and_effort(self) -> None:
        with self.assertRaisesRegex(ValueError, "model_tier"):
            AgentDecisionLoopSpec(**{**self.spec.__dict__, "model_tier": "unsupported"})
        with self.assertRaisesRegex(ValueError, "effort"):
            AgentDecisionLoopSpec(**{**self.spec.__dict__, "effort": "low"})

    def result(
        self,
        text: str,
        *,
        subtype: str | None = "success",
        is_error: bool = False,
        session_id: str | None = "session-1",
        cwd: Path | None = None,
        skills: list[str] | None = None,
        commands: list[str] | None = None,
        exception: str | None = None,
        api_error_status: int | None = None,
        terminal_reason: str | None = None,
        retry_requested: bool = False,
    ) -> ClaudeRunResult:
        return ClaudeRunResult(
            init={
                "cwd": str(cwd or self.workspace),
                "skills": skills if skills is not None else [self.spec.skill_name],
                "slash_commands": commands
                if commands is not None
                else [self.spec.skill_name],
            },
            text=text,
            result_subtype=subtype,
            is_error=is_error,
            session_id=session_id,
            stop_reason=None,
            num_turns=1,
            total_cost_usd=0.01,
            exception=exception,
            api_error_status=api_error_status,
            terminal_reason=terminal_reason,
            has_errors=is_error or exception is not None,
            exception_type="RuntimeError" if exception else None,
            retry_requested=retry_requested,
        )

    def save_conversation(self, messages: list[dict[str, str]], *, old_reference: bool = False) -> None:
        path = self.run_dir / "conversations" / f"{self.spec.key}.json"
        path.parent.mkdir()
        write_json(path, {"messages": messages})
        reference: dict[str, object] = {"path": path.relative_to(self.run_dir).as_posix()}
        if old_reference:
            reference["turn"] = 99
        self.state["decision_conversations"] = {self.spec.key: reference}

    async def run_loop(
        self,
        agent: FakeAgentRunner,
        decisions: FakeDecisionRunner,
        verifier=lambda: None,
    ) -> AgentDecision:
        return await run_agent_decision_loop(
            self.run_dir,
            self.state,
            self.workspace,
            self.spec,
            "初始 Agent 提示",
            verifier,
            agent_runner=agent,
            decision_runner=decisions,
            config_loader=lambda: object(),
        )

    async def test_new_session_continue_then_completed_preserves_full_text(self) -> None:
        original = "首轮 Agent 原文\n包含全部细节：token-like-text"
        continued = "第二轮 Agent 原文"
        agent = FakeAgentRunner([self.result(original), self.result(continued)])
        decisions = FakeDecisionRunner(
            [
                decision("continue", answer="请补齐核验。", reason="产物还不完整"),
                decision("completed", reason="产物已完成"),
            ]
        )

        outcome = await self.run_loop(agent, decisions)

        self.assertEqual(outcome.verdict, "completed")
        self.assertEqual([call[0] for call in agent.calls], ["初始 Agent 提示", "请补齐核验。"])
        self.assertIsNone(agent.calls[0][1]["resume_session_id"])
        self.assertEqual(agent.calls[1][1]["resume_session_id"], "session-1")
        self.assertEqual(
            [(call[1]["model_tier"], call[1]["effort"]) for call in agent.calls],
            [("medium", "high"), ("medium", "high")],
        )
        self.assertEqual(decisions.calls[0][0][-1], {"role": "user", "content": original})
        messages = json.loads(
            (self.run_dir / "conversations" / f"{self.spec.key}.json").read_text(encoding="utf-8")
        )["messages"]
        self.assertEqual(
            messages,
            [
                {"role": "system", "content": self.spec.decision_system_prompt},
                {"role": "assistant", "content": "初始 Agent 提示"},
                {"role": "user", "content": original},
                {
                    "role": "assistant",
                    "content": decision(
                        "continue", answer="请补齐核验。", reason="产物还不完整"
                    ).model_dump_json(),
                },
                {"role": "user", "content": continued},
                {
                    "role": "assistant",
                    "content": decision("completed", reason="产物已完成").model_dump_json(),
                },
            ],
        )
        self.assertEqual(self.state["claude_sessions"], {self.spec.key: "session-1"})
        self.assertEqual(
            self.state["decision_conversations"],
            {self.spec.key: {"path": f"conversations/{self.spec.key}.json"}},
        )
        self.assertNotIn("pending_agent_text", self.state[self.spec.state_key])
        self.assertNotIn("pending_agent_prompt", self.state[self.spec.state_key])

    async def test_pending_agent_text_recovers_to_user_without_recalling_agent(self) -> None:
        original = "已落盘但尚未决策的完整 Agent 原文"
        self.state["claude_sessions"] = {self.spec.key: "session-1"}
        self.state[self.spec.state_key] = {"pending_agent_text": original}
        self.save_conversation(
            [
                {"role": "system", "content": self.spec.decision_system_prompt},
                {"role": "assistant", "content": "初始 Agent 提示"},
            ]
        )
        agent = FakeAgentRunner([])
        decisions = FakeDecisionRunner([decision("completed", reason="已核验")])

        outcome = await self.run_loop(agent, decisions)

        self.assertEqual(outcome.verdict, "completed")
        self.assertEqual(agent.calls, [])
        self.assertEqual(decisions.calls[0][0][-1], {"role": "user", "content": original})
        self.assertNotIn("pending_agent_text", self.state[self.spec.state_key])

    async def test_configuration_failure_persists_safe_diagnostic(self) -> None:
        self.save_conversation(
            [
                {"role": "system", "content": self.spec.decision_system_prompt},
                {"role": "assistant", "content": "初始 Agent 提示"},
                {"role": "user", "content": "已完成的 Agent 回复"},
            ]
        )

        def invalid_config() -> object:
            raise ValueError("LLM_API_KEY=secret")

        with self.assertRaises(AIDecisionFailure) as raised:
            await run_agent_decision_loop(
                self.run_dir,
                self.state,
                self.workspace,
                self.spec,
                "初始 Agent 提示",
                lambda: None,
                agent_runner=FakeAgentRunner([]),
                decision_runner=FakeDecisionRunner([]),
                config_loader=invalid_config,  # type: ignore[arg-type]
            )

        self.assertEqual(raised.exception.diagnostic, {"kind": "configuration"})
        failure = self.state[self.spec.state_key]["last_decision_failure"]
        self.assertEqual(failure["kind"], "configuration")
        self.assertIn("LLM_API_KEY=[REDACTED]", failure["message"])
        self.assertEqual(failure["diagnostic_path"], "logs/test_conversation-decision.json")
        self.assertTrue((self.run_dir / failure["diagnostic_path"]).is_file())
        self.assertNotIn("secret", json.dumps(self.state, ensure_ascii=False))
        messages = json.loads(
            (self.run_dir / "conversations" / f"{self.spec.key}.json").read_text(
                encoding="utf-8"
            )
        )["messages"]
        self.assertEqual(messages[-1]["role"], "user")

    async def test_http_failure_persists_only_safe_response_fields(self) -> None:
        self.save_conversation(
            [
                {"role": "system", "content": self.spec.decision_system_prompt},
                {"role": "assistant", "content": "初始 Agent 提示"},
                {"role": "user", "content": "已完成的 Agent 回复"},
            ]
        )

        async def failed_decision(*_args: object, **_kwargs: object) -> object:
            raise ResponsesFailure(
                "http", http_status=403, request_id="request-123"
            )

        with self.assertRaises(AIDecisionFailure) as raised:
            await run_agent_decision_loop(
                self.run_dir,
                self.state,
                self.workspace,
                self.spec,
                "初始 Agent 提示",
                lambda: None,
                agent_runner=FakeAgentRunner([]),
                decision_runner=failed_decision,
                config_loader=lambda: object(),
            )

        diagnostic = {
            "kind": "http",
            "http_status": 403,
            "request_id": "request-123",
        }
        self.assertEqual(raised.exception.diagnostic, diagnostic)
        failure = self.state[self.spec.state_key]["last_decision_failure"]
        self.assertEqual({key: failure[key] for key in diagnostic}, diagnostic)
        self.assertIn("ResponsesFailure", failure["message"])
        self.assertEqual(failure["diagnostic_path"], "logs/test_conversation-decision.json")
        messages = json.loads(
            (self.run_dir / "conversations" / f"{self.spec.key}.json").read_text(
                encoding="utf-8"
            )
        )["messages"]
        self.assertEqual(messages[-1]["role"], "user")

    async def test_successful_decision_clears_failure_without_recalling_agent(self) -> None:
        self.state[self.spec.state_key] = {
            "last_decision_failure": {"kind": "transport"}
        }
        self.save_conversation(
            [
                {"role": "system", "content": self.spec.decision_system_prompt},
                {"role": "assistant", "content": "初始 Agent 提示"},
                {"role": "user", "content": "已完成的 Agent 回复"},
            ]
        )
        agent = FakeAgentRunner([])

        outcome = await self.run_loop(
            agent,
            FakeDecisionRunner([decision("completed", reason="已核验")]),
        )

        self.assertEqual(outcome.verdict, "completed")
        self.assertEqual(agent.calls, [])
        self.assertNotIn(
            "last_decision_failure", self.state[self.spec.state_key]
        )

    async def test_empty_pending_agent_text_is_discarded_before_resume(self) -> None:
        self.state["claude_sessions"] = {self.spec.key: "session-1"}
        self.state[self.spec.state_key] = {"pending_agent_text": ""}
        self.save_conversation(
            [
                {"role": "system", "content": self.spec.decision_system_prompt},
                {"role": "assistant", "content": "初始 Agent 提示"},
            ]
        )
        agent = FakeAgentRunner([self.result("恢复后的完整回复")])

        outcome = await self.run_loop(
            agent,
            FakeDecisionRunner([decision("completed", reason="已核验")]),
        )

        self.assertEqual(outcome.verdict, "completed")
        self.assertEqual(agent.calls[0][1]["resume_session_id"], "session-1")
        self.assertNotIn("pending_agent_text", self.state[self.spec.state_key])

    async def test_empty_agent_result_is_not_saved_as_pending_text(self) -> None:
        agent = FakeAgentRunner([self.result("")])

        with self.assertRaises(AgentExecutionFailure):
            await self.run_loop(agent, FakeDecisionRunner([]))

        self.assertNotIn("pending_agent_text", self.state[self.spec.state_key])

    async def test_decision_uses_persisted_system_prompt_on_recovery(self) -> None:
        original = "已落盘的完整 Agent 原文"
        persisted_system_prompt = "旧 run 的 system prompt"
        self.state["claude_sessions"] = {self.spec.key: "session-1"}
        self.state[self.spec.state_key] = {"pending_agent_text": original}
        self.save_conversation(
            [
                {"role": "system", "content": persisted_system_prompt},
                {"role": "assistant", "content": "初始 Agent 提示"},
            ]
        )
        decisions = FakeDecisionRunner([decision("completed", reason="已核验")])

        outcome = await self.run_loop(FakeAgentRunner([]), decisions)

        self.assertEqual(outcome.verdict, "completed")
        self.assertEqual(decisions.calls[0][2], persisted_system_prompt)

    async def test_orphaned_conversation_file_is_loaded_and_referenced(self) -> None:
        persisted_system_prompt = "中断前保存的 system prompt"
        self.state["claude_sessions"] = {self.spec.key: "session-1"}
        path = self.run_dir / "conversations" / f"{self.spec.key}.json"
        path.parent.mkdir()
        write_json(
            path,
            {
                "messages": [
                    {"role": "system", "content": persisted_system_prompt},
                    {"role": "assistant", "content": "初始 Agent 提示"},
                    {"role": "user", "content": "已保存的完整 Agent 原文"},
                ]
            },
        )
        decisions = FakeDecisionRunner([decision("completed", reason="已核验")])

        outcome = await self.run_loop(FakeAgentRunner([]), decisions)

        self.assertEqual(outcome.verdict, "completed")
        self.assertEqual(decisions.calls[0][2], persisted_system_prompt)
        self.assertEqual(
            self.state["decision_conversations"],
            {self.spec.key: {"path": f"conversations/{self.spec.key}.json"}},
        )

    async def test_completed_repair_keeps_completed_json_and_continues(self) -> None:
        completed = decision("completed", reason="首次已完成")
        agent = FakeAgentRunner([self.result("首次回答"), self.result("修复后回答")])
        decisions = FakeDecisionRunner([completed, decision("completed", reason="修复后已完成")])
        repairs = iter(["请修复遗漏的文件。", None])

        outcome = await self.run_loop(agent, decisions, verifier=lambda: next(repairs))

        self.assertEqual(outcome.verdict, "completed")
        self.assertEqual([call[0] for call in agent.calls], ["初始 Agent 提示", "请修复遗漏的文件。"])
        messages = json.loads(
            (self.run_dir / "conversations" / f"{self.spec.key}.json").read_text(encoding="utf-8")
        )["messages"]
        first_completed_index = next(
            index for index, message in enumerate(messages) if message["content"] == completed.model_dump_json()
        )
        self.assertEqual(messages[first_completed_index + 1], {"role": "assistant", "content": "请修复遗漏的文件。"})

    async def test_completion_verifier_exception_fails_without_rewriting_completed_decision(self) -> None:
        completed = decision("completed", reason="已完成")
        agent = FakeAgentRunner([self.result("Agent 回复")])
        decisions = FakeDecisionRunner([completed])

        with self.assertRaisesRegex(RuntimeError, "完成核验失败"):
            await self.run_loop(agent, decisions, verifier=lambda: (_ for _ in ()).throw(ValueError("secret")))

        messages = json.loads(
            (self.run_dir / "conversations" / f"{self.spec.key}.json").read_text(encoding="utf-8")
        )["messages"]
        self.assertEqual(messages[-1]["content"], completed.model_dump_json())

    async def test_blocked_outcome_and_explicit_rerun(self) -> None:
        blocked = decision(
            "blocked", reason="缺少外部授权", required_inputs=["提供授权"]
        )
        agent = FakeAgentRunner([self.result("首次回答"), self.result("恢复后回答")])
        decisions = FakeDecisionRunner([blocked, decision("completed", reason="恢复完成")])

        first = await self.run_loop(agent, decisions)
        self.assertEqual(first.verdict, "blocked")
        self.assertEqual(len(agent.calls), 1)

        self.state["status"] = "blocked"
        second = await self.run_loop(agent, decisions)

        self.assertEqual(second.verdict, "completed")
        self.assertEqual(agent.calls[1][0], BLOCKED_RESUME_PROMPT)
        self.assertEqual(agent.calls[1][1]["resume_session_id"], "session-1")

    async def test_explicit_blocked_rerun_stops_if_agent_is_still_blocked(self) -> None:
        blocked = decision(
            "blocked", reason="仍缺少外部授权", required_inputs=["提供授权"]
        )
        self.state.update(
            {
                "status": "blocked",
                "claude_sessions": {self.spec.key: "session-1"},
            }
        )
        self.save_conversation(
            [
                {"role": "system", "content": self.spec.decision_system_prompt},
                {"role": "assistant", "content": "初始 Agent 提示"},
                {"role": "user", "content": "首次 Agent 回复"},
                {"role": "assistant", "content": blocked.model_dump_json()},
            ]
        )
        agent = FakeAgentRunner([self.result("重新核验后仍然缺少授权")])
        decisions = FakeDecisionRunner([blocked])

        outcome = await self.run_loop(agent, decisions)

        self.assertEqual(outcome.verdict, "blocked")
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(agent.calls[0][0], BLOCKED_RESUME_PROMPT)
        self.assertEqual(len(decisions.calls), 1)

    async def test_legacy_action_and_legacy_completion_sentinel(self) -> None:
        legacy_action = json.dumps(
            {
                "action": "approve",
                "answer": "根据旧决定继续处理。",
                "reason": "旧记录要求继续",
                "required_inputs": [],
            },
            ensure_ascii=False,
        )
        self.state["claude_sessions"] = {self.spec.key: "session-1"}
        self.save_conversation(
            [
                {"role": "system", "content": self.spec.decision_system_prompt},
                {"role": "assistant", "content": "初始 Agent 提示"},
                {"role": "user", "content": "旧 Agent 原文"},
                {"role": "assistant", "content": legacy_action},
            ],
            old_reference=True,
        )
        legacy_agent = FakeAgentRunner([self.result("旧决定后的 Agent 原文")])
        outcome = await self.run_loop(
            legacy_agent, FakeDecisionRunner([decision("completed", reason="已完成")])
        )
        self.assertEqual(outcome.verdict, "completed")
        self.assertEqual(legacy_agent.calls[0][0], "根据旧决定继续处理。")
        self.assertEqual(
            count_decisions(
                json.loads(
                    (self.run_dir / "conversations" / f"{self.spec.key}.json").read_text(
                        encoding="utf-8"
                    )
                )["messages"]
            ),
            2,
        )

        sentinel_spec = AgentDecisionLoopSpec(
            **{
                **self.spec.__dict__,
                "legacy_completion_messages": ("旧完成 sentinel",),
            }
        )
        sentinel_state: dict[str, object] = {
            "decision_conversations": {
                sentinel_spec.key: {"path": f"conversations/{sentinel_spec.key}.json"}
            }
        }
        path = self.run_dir / "conversations" / f"{sentinel_spec.key}.json"
        write_json(
            path,
            {
                "messages": [
                    {"role": "system", "content": sentinel_spec.decision_system_prompt},
                    {"role": "user", "content": "旧 Agent 原文"},
                    {"role": "assistant", "content": "旧完成 sentinel"},
                ]
            },
        )
        sentinel_outcome = await run_agent_decision_loop(
            self.run_dir,
            sentinel_state,
            self.workspace,
            sentinel_spec,
            "初始 Agent 提示",
            lambda: None,
            agent_runner=FakeAgentRunner([]),
            decision_runner=FakeDecisionRunner([]),
            config_loader=lambda: object(),
        )
        self.assertEqual(sentinel_outcome.verdict, "completed")

    async def test_legacy_nonblocked_action_with_empty_answer_uses_safe_continue_prompt(self) -> None:
        for action in ("answer", "approve", "continue"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                run_dir = Path(directory) / "run"
                workspace = Path(directory) / "workspace"
                run_dir.mkdir()
                workspace.mkdir()
                state: dict[str, object] = {
                    "claude_sessions": {self.spec.key: "session-1"},
                    "decision_conversations": {
                        self.spec.key: {"path": f"conversations/{self.spec.key}.json"}
                    },
                }
                path = run_dir / "conversations" / f"{self.spec.key}.json"
                path.parent.mkdir()
                legacy_json = json.dumps(
                    {
                        "action": action,
                        "answer": "",
                        "reason": "旧决定没有继续文本",
                        "required_inputs": [],
                    },
                    ensure_ascii=False,
                )
                write_json(
                    path,
                    {
                        "messages": [
                            {"role": "system", "content": self.spec.decision_system_prompt},
                            {"role": "assistant", "content": "初始 Agent 提示"},
                            {"role": "user", "content": "旧 Agent 原文"},
                            {"role": "assistant", "content": legacy_json},
                        ]
                    },
                )
                agent = FakeAgentRunner([self.result("恢复后的 Agent 回复", cwd=workspace)])
                decisions = FakeDecisionRunner([decision("completed", reason="已完成")])

                outcome = await run_agent_decision_loop(
                    run_dir,
                    state,
                    workspace,
                    self.spec,
                    "初始 Agent 提示",
                    lambda: None,
                    agent_runner=agent,
                    decision_runner=decisions,
                    config_loader=lambda: object(),
                )

                self.assertEqual(outcome.verdict, "completed")
                self.assertEqual(agent.calls[0][0], LEGACY_CONTINUE_PROMPT)
                self.assertNotEqual(agent.calls[0][0], legacy_json)

    async def test_legacy_pending_prompt_is_discarded_not_scheduled(self) -> None:
        self.state[self.spec.state_key] = {"pending_agent_prompt": "不得使用的旧提示"}
        agent = FakeAgentRunner([self.result("新的 Agent 原文")])
        decisions = FakeDecisionRunner([decision("completed", reason="已完成")])

        outcome = await self.run_loop(agent, decisions)

        self.assertEqual(outcome.verdict, "completed")
        self.assertEqual(agent.calls[0][0], "初始 Agent 提示")
        self.assertNotIn("pending_agent_prompt", self.state[self.spec.state_key])

    async def test_session_cwd_skill_and_command_mismatches_fail(self) -> None:
        cases = [
            ("session", self.result("回复", session_id="other-session"), {"claude_sessions": {self.spec.key: "session-1"}}),
            ("cwd", self.result("回复", cwd=self.workspace.parent), {}),
            ("skill", self.result("回复", skills=[]), {}),
            ("command", self.result("回复", commands=[]), {}),
        ]
        for _name, value, initial_state in cases:
            with self.subTest(_name):
                with tempfile.TemporaryDirectory() as directory:
                    run_dir = Path(directory) / "run"
                    workspace = Path(directory) / "workspace"
                    run_dir.mkdir()
                    workspace.mkdir()
                    state = copy.deepcopy(initial_state)
                    value.init["cwd"] = str(workspace if _name != "cwd" else workspace.parent)
                    value.retry_requested = True
                    agent = FakeAgentRunner([value])
                    decisions = FakeDecisionRunner([])
                    with self.assertRaises(AgentExecutionFailure) as raised:
                        await run_agent_decision_loop(
                            run_dir,
                            state,
                            workspace,
                            self.spec,
                            "初始 Agent 提示",
                            lambda: None,
                            agent_runner=agent,
                            decision_runner=decisions,
                            config_loader=lambda: object(),
                        )
                    self.assertFalse(raised.exception.retry_requested)

    async def test_aborted_terminal_reason_fails_before_decision(self) -> None:
        for terminal_reason in ("aborted_streaming", "aborted_tools", "unexpected_reason"):
            with self.subTest(terminal_reason=terminal_reason):
                agent = FakeAgentRunner(
                    [
                        self.result(
                            "未完整的 Agent 回复",
                            terminal_reason=terminal_reason,
                            retry_requested=True,
                        )
                    ]
                )
                decisions = FakeDecisionRunner([])

                with self.assertRaises(AgentExecutionFailure) as raised:
                    await self.run_loop(agent, decisions)

                self.assertFalse(raised.exception.retry_requested)
                self.assertEqual(decisions.calls, [])
                self.state.clear()
                conversation = self.run_dir / "conversations" / f"{self.spec.key}.json"
                conversation.unlink(missing_ok=True)

    async def test_max_turns_and_budget_results_require_normal_completion(self) -> None:
        for subtype in ("error_max_turns", "error_max_budget_usd"):
            with self.subTest(subtype):
                with tempfile.TemporaryDirectory() as directory:
                    run_dir = Path(directory) / "run"
                    workspace = Path(directory) / "workspace"
                    run_dir.mkdir()
                    workspace.mkdir()
                    agent = FakeAgentRunner(
                        [
                            self.result(
                                "可恢复的完整回复",
                                subtype=subtype,
                                is_error=True,
                                cwd=workspace,
                                exception="RuntimeError: SDK 在 ResultMessage 后结束",
                            ),
                            self.result("正常结束后的完整回复", cwd=workspace),
                        ]
                    )
                    decisions = FakeDecisionRunner(
                        [
                            decision("completed", reason="部分结果可用"),
                            decision("completed", reason="已正常结束"),
                        ]
                    )
                    verifier_calls = 0

                    def verifier() -> None:
                        nonlocal verifier_calls
                        verifier_calls += 1
                        return None

                    outcome = await run_agent_decision_loop(
                        run_dir,
                        {},
                        workspace,
                        self.spec,
                        "初始 Agent 提示",
                        verifier,
                        agent_runner=agent,
                        decision_runner=decisions,
                        config_loader=lambda: object(),
                    )

                    self.assertEqual(outcome.verdict, "completed")
                    self.assertEqual(verifier_calls, 1)
                    self.assertEqual(
                        [call[0] for call in agent.calls],
                        ["初始 Agent 提示", RECOVERABLE_RESULT_PROMPT],
                    )
                    self.assertEqual(agent.calls[1][1]["resume_session_id"], "session-1")
                    self.assertEqual(decisions.calls[0][0][-1]["content"], "可恢复的完整回复")

    async def test_recoverable_completed_respects_decision_limit(self) -> None:
        limited_spec = AgentDecisionLoopSpec(
            **{**self.spec.__dict__, "max_decision_rounds": 1}
        )
        agent = FakeAgentRunner(
            [
                self.result(
                    "可恢复回复",
                    subtype="error_max_turns",
                    is_error=True,
                )
            ]
        )
        decisions = FakeDecisionRunner([decision("completed", reason="部分完成")])

        with self.assertRaisesRegex(RuntimeError, "达到上限"):
            await run_agent_decision_loop(
                self.run_dir,
                self.state,
                self.workspace,
                limited_spec,
                "初始 Agent 提示",
                lambda: (_ for _ in ()).throw(AssertionError("不应核验")),
                agent_runner=agent,
                decision_runner=decisions,
                config_loader=lambda: object(),
            )
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(len(decisions.calls), 1)

    async def test_api_status_missing_result_and_ordinary_error_fail_safely(self) -> None:
        cases = [
            self.result("回复", api_error_status=429),
            self.result("", subtype=None, session_id=None),
            self.result("", subtype="success"),
            self.result("回复", subtype="error", is_error=True),
            self.result("回复", exception="RuntimeError: API_KEY=secret"),
        ]
        for value in cases:
            with self.subTest(subtype=value.result_subtype, api=value.api_error_status):
                with tempfile.TemporaryDirectory() as directory:
                    run_dir = Path(directory) / "run"
                    workspace = Path(directory) / "workspace"
                    run_dir.mkdir()
                    workspace.mkdir()
                    state: dict[str, object] = {}
                    value.init["cwd"] = str(workspace)
                    with self.assertRaises(RuntimeError):
                        await run_agent_decision_loop(
                            run_dir,
                            state,
                            workspace,
                            self.spec,
                            "初始 Agent 提示",
                            lambda: None,
                            agent_runner=FakeAgentRunner([value]),
                            decision_runner=FakeDecisionRunner([]),
                            config_loader=lambda: object(),
                        )
                    self.assertNotIn("API_KEY=secret", json.dumps(state, ensure_ascii=False))

    async def test_agent_exception_fails_as_safe_runtime_error(self) -> None:
        async def raises_exception(*_args: object, **_kwargs: object) -> ClaudeRunResult:
            raise ValueError("API_KEY=secret")

        with self.assertRaises(AgentExecutionFailure) as raised:
            await run_agent_decision_loop(
                self.run_dir,
                {},
                self.workspace,
                self.spec,
                "初始 Agent 提示",
                lambda: None,
                agent_runner=raises_exception,
                decision_runner=FakeDecisionRunner([]),
                config_loader=lambda: object(),
            )
        self.assertFalse(raised.exception.retry_requested)

    async def test_agent_cancellation_is_propagated(self) -> None:
        async def raises_cancelled(*_args: object, **_kwargs: object) -> ClaudeRunResult:
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await run_agent_decision_loop(
                self.run_dir,
                {},
                self.workspace,
                self.spec,
                "初始 Agent 提示",
                lambda: None,
                agent_runner=raises_cancelled,
                decision_runner=FakeDecisionRunner([]),
                config_loader=lambda: object(),
            )

    async def test_decision_and_completion_cancellation_are_propagated(self) -> None:
        async def cancelled_decision(*_args: object, **_kwargs: object):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await run_agent_decision_loop(
                self.run_dir,
                {},
                self.workspace,
                self.spec,
                "初始 Agent 提示",
                lambda: None,
                agent_runner=FakeAgentRunner([self.result("Agent 完整回复")]),
                decision_runner=cancelled_decision,
                config_loader=lambda: object(),
            )

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            workspace = Path(directory) / "workspace"
            run_dir.mkdir()
            workspace.mkdir()

            async def cancelled_verifier() -> None:
                raise asyncio.CancelledError()

            with self.assertRaises(asyncio.CancelledError):
                await run_agent_decision_loop(
                    run_dir,
                    {},
                    workspace,
                    self.spec,
                    "初始 Agent 提示",
                    cancelled_verifier,
                    agent_runner=FakeAgentRunner([self.result("Agent 完整回复", cwd=workspace)]),
                    decision_runner=FakeDecisionRunner(
                        [decision("completed", reason="等待完成核验")]
                    ),
                    config_loader=lambda: object(),
                )

    async def test_direct_sdk_channel_errors_request_retry(self) -> None:
        cases = [
            (CLIConnectionError("connection failed"), True),
            (ProcessError("process failed", exit_code=1), True),
            (
                AgentExecutionFailure(
                    "explicit retry",
                    "logs/original.json",
                    retry_requested=True,
                ),
                True,
            ),
            (CLINotFoundError(), False),
        ]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                async def failed_runner(
                    *_args: object,
                    **_kwargs: object,
                ) -> ClaudeRunResult:
                    raise error

                with tempfile.TemporaryDirectory() as directory:
                    run_dir = Path(directory) / "run"
                    workspace = Path(directory) / "workspace"
                    run_dir.mkdir()
                    workspace.mkdir()
                    with self.assertRaises(AgentExecutionFailure) as raised:
                        await run_agent_decision_loop(
                            run_dir,
                            {},
                            workspace,
                            self.spec,
                            "初始 Agent 提示",
                            lambda: None,
                            agent_runner=failed_runner,
                            decision_runner=FakeDecisionRunner([]),
                            config_loader=lambda: object(),
                        )
                    self.assertEqual(raised.exception.retry_requested, expected)
                    self.assertNotIn("retry_requested", raised.exception.as_error())

    async def test_api_error_result_requests_retry_without_persisting_flag(self) -> None:
        for status in (400, 403, 500):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                run_dir = Path(directory) / "run"
                workspace = Path(directory) / "workspace"
                run_dir.mkdir()
                workspace.mkdir()
                state: dict[str, object] = {}
                value = self.result(
                    "",
                    cwd=workspace,
                    is_error=True,
                    api_error_status=status,
                    terminal_reason="api_error",
                    retry_requested=True,
                )
                value.sdk_errors = ["provider api_error: secret=hidden"]

                with self.assertRaises(AgentExecutionFailure) as raised:
                    await run_agent_decision_loop(
                        run_dir,
                        state,
                        workspace,
                        self.spec,
                        "初始 Agent 提示",
                        lambda: None,
                        agent_runner=FakeAgentRunner([value]),
                        decision_runner=FakeDecisionRunner([]),
                        config_loader=lambda: object(),
                    )

                self.assertTrue(raised.exception.retry_requested)
                self.assertNotIn("retry_requested", raised.exception.as_error())
                saved = json.loads(
                    (run_dir / raised.exception.diagnostic_path).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    saved["details"]["sdk_errors"],
                    ["provider api_error: secret=[REDACTED]"],
                )
                result = state[self.spec.state_key]["last_agent_result"]
                self.assertIn("provider api_error", result["message"])
                self.assertEqual(
                    result["diagnostic_path"], raised.exception.diagnostic_path
                )
                serialized = json.dumps(
                    {
                        "state": state,
                        "diagnostic": saved,
                        "conversation": json.loads(
                            (
                                run_dir
                                / "conversations"
                                / f"{self.spec.key}.json"
                            ).read_text(encoding="utf-8")
                        ),
                    },
                    ensure_ascii=False,
                )
                self.assertNotIn("retry_requested", serialized)

    async def test_agent_runner_exception_preserves_safe_cause_and_traceback_in_log(self) -> None:
        async def failed_runner(*_args: object, **_kwargs: object) -> ClaudeRunResult:
            try:
                raise ValueError("access_token=inner-secret")
            except ValueError as cause:
                raise RuntimeError("api_key=outer-secret") from cause

        with self.assertRaises(AgentExecutionFailure) as raised:
            await self.run_loop(failed_runner, FakeDecisionRunner([]))

        self.assertEqual(raised.exception.diagnostic_path, "logs/test_conversation-agent.json")
        saved = json.loads((self.run_dir / raised.exception.diagnostic_path).read_text(encoding="utf-8"))
        serialized = json.dumps(saved, ensure_ascii=False)
        self.assertNotIn("outer-secret", serialized)
        self.assertNotIn("inner-secret", serialized)
        self.assertEqual(saved["exception"]["chain"][0]["type"], "ValueError")
        self.assertTrue(saved["exception"]["traceback"])
        state_result = self.state[self.spec.state_key]["last_agent_result"]
        self.assertEqual(state_result["diagnostic_path"], raised.exception.diagnostic_path)
        self.assertIn("api_key=[REDACTED]", state_result["message"])

    async def test_long_agent_key_uses_stable_bounded_diagnostic_filename(self) -> None:
        key = "requirement_commit_BR-" + "x" * 200
        first = persist_agent_failure(
            self.run_dir,
            self.state,
            key=key,
            state_key=None,
            error=RuntimeError("agent failed"),
        )
        second = persist_agent_failure(
            self.run_dir,
            self.state,
            key=key,
            state_key=None,
            error=RuntimeError("agent failed again"),
        )

        self.assertEqual(first.diagnostic_path, second.diagnostic_path)
        self.assertLessEqual(len(Path(first.diagnostic_path).name), 128)
        self.assertRegex(Path(first.diagnostic_path).name, r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.json$")
        self.assertTrue((self.run_dir / first.diagnostic_path).is_file())

    async def test_decision_limit_has_no_extra_agent_or_decision_call(self) -> None:
        limited_spec = AgentDecisionLoopSpec(
            **{**self.spec.__dict__, "max_decision_rounds": 1}
        )
        agent = FakeAgentRunner([self.result("首轮回复"), self.result("不应调用")])
        decisions = FakeDecisionRunner(
            [decision("continue", answer="继续执行", reason="尚未完成")]
        )

        with self.assertRaisesRegex(RuntimeError, "达到上限"):
            await run_agent_decision_loop(
                self.run_dir,
                self.state,
                self.workspace,
                limited_spec,
                "初始 Agent 提示",
                lambda: None,
                agent_runner=agent,
                decision_runner=decisions,
                config_loader=lambda: object(),
            )
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(len(decisions.calls), 1)


class ClaudeAgentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.agent_config = AgentConfig(
            "http://agent.example.invalid",
            SecretStr("agent-secret"),
            low_model="low-model",
            medium_model="medium-model",
            high_model="high-model",
        )
        self.agent_config_patcher = patch(
            "common.claude_agent.AgentConfig.load", return_value=self.agent_config
        )
        self.agent_config_patcher.start()

    def tearDown(self) -> None:
        self.agent_config_patcher.stop()

    async def test_orchestrator_configuration_is_not_passed_to_agent(self) -> None:
        inherited = {
            "LLM_BASE_URL": "http://decision.example.invalid/v1",
            "LLM_API_KEY": "decision-secret",
            "LLM_MODEL": "decision-model",
            "PCM_WORKSPACE_ROOT": "/products",
            "PCM_TEMPLATE_CATALOG": "/catalog.json",
            "PCM_TEMPLATE_REPOSITORY": "git@example.invalid/template.git",
            "PCM_AGENT_WORKSPACE_ENV_FILE": "/protected/agent-workspace.env",
            "PCM_DEV_RESOURCE_LIST": "/protected/resources.md",
        }
        with patch.dict(os.environ, inherited):
            env = filtered_env(self.agent_config, "medium-model")
        for key in inherited:
            with self.subTest(key=key):
                self.assertEqual(env[key], "")

    async def test_result_terminal_reason_api_status_and_errors_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            write_json(workspace / "plugins-lock.json", {"version": 1, "plugins": []})
            updates: list[ClaudeRunResult] = []
            captured_options: list[Any] = []

            async def fake_query(*_args: object, **kwargs: object):
                captured_options.append(kwargs["options"])
                yield SystemMessage(
                    subtype="init",
                    data={"session_id": "session-1", "cwd": str(workspace)},
                )
                yield ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=True,
                    num_turns=1,
                    session_id="session-1",
                    result="Agent 的完整结果",
                    errors=["tool warning agent-secret"],
                    api_error_status=429,
                    terminal_reason="api_error",
                )

            with patch("common.claude_agent.query", new=fake_query):
                result = await run_claude(
                    "测试提示",
                    cwd=workspace,
                    resume_session_id="session-1",
                    on_update=updates.append,
                )

        self.assertEqual(captured_options[0].max_buffer_size, 10 * 1024 * 1024)
        self.assertEqual(captured_options[0].resume, "session-1")
        self.assertEqual(captured_options[0].model, "medium-model")
        self.assertEqual(captured_options[0].effort, "high")
        self.assertIsNone(captured_options[0].max_budget_usd)
        self.assertEqual(captured_options[0].env["ANTHROPIC_BASE_URL"], self.agent_config.base_url)
        self.assertEqual(captured_options[0].env["ANTHROPIC_API_KEY"], "agent-secret")
        self.assertEqual(captured_options[0].env["ANTHROPIC_AUTH_TOKEN"], "")
        self.assertEqual(captured_options[0].env["CLAUDE_CODE_SUBAGENT_MODEL"], "medium-model")
        self.assertEqual(captured_options[0].env["PCM_AGENT_API_KEY"], "")
        self.assertEqual(
            captured_options[0].env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"], "0"
        )
        self.assertEqual(result.terminal_reason, "api_error")
        self.assertEqual(result.api_error_status, 429)
        self.assertTrue(result.has_errors)
        self.assertEqual(result.sdk_errors, ["tool warning [REDACTED]"])
        self.assertTrue(result.retry_requested)
        self.assertTrue(updates[-1].is_error)
        self.assertEqual(updates[-1].terminal_reason, "api_error")
        self.assertEqual(updates[-1].api_error_status, 429)
        self.assertTrue(updates[-1].has_errors)
        self.assertEqual(updates[-1].sdk_errors, ["tool warning [REDACTED]"])
        self.assertTrue(updates[-1].retry_requested)

    async def test_all_api_statuses_and_api_terminal_reason_request_retry(self) -> None:
        for status in (400, 403, 500, None):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                write_json(
                    workspace / "plugins-lock.json",
                    {"version": 1, "plugins": []},
                )

                async def fake_query(*_args: object, **_kwargs: object):
                    yield SystemMessage(
                        subtype="init",
                        data={"session_id": "session-1", "cwd": str(workspace)},
                    )
                    yield ResultMessage(
                        subtype="success",
                        duration_ms=1,
                        duration_api_ms=1,
                        is_error=True,
                        num_turns=1,
                        session_id="session-1",
                        result=None,
                        api_error_status=status,
                        terminal_reason="api_error",
                    )

                with patch("common.claude_agent.query", new=fake_query):
                    result = await run_claude(
                        "测试提示",
                        cwd=workspace,
                        resume_session_id="session-1",
                    )

                self.assertTrue(result.retry_requested)

    async def test_sdk_exception_retry_classification(self) -> None:
        cases = [
            (CLIConnectionError("connection failed"), True),
            (ProcessError("process failed", exit_code=1), True),
            (CLINotFoundError(), False),
            (ValueError("local error"), False),
        ]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                write_json(
                    workspace / "plugins-lock.json",
                    {"version": 1, "plugins": []},
                )

                async def fake_query(*_args: object, **_kwargs: object):
                    raise error
                    yield

                with patch("common.claude_agent.query", new=fake_query):
                    result = await run_claude("测试提示", cwd=workspace)

                self.assertEqual(result.retry_requested, expected)

    async def test_sdk_timeout_is_not_reported_as_wall_clock_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            write_json(
                workspace / "plugins-lock.json",
                {"version": 1, "plugins": []},
            )

            async def fake_query(*_args: object, **_kwargs: object):
                raise TimeoutError("SDK internal timeout")
                yield

            with patch("common.claude_agent.query", new=fake_query):
                result = await run_claude("测试提示", cwd=workspace)

        self.assertEqual(result.exception_type, "TimeoutError")
        self.assertIn("SDK internal timeout", result.exception or "")
        self.assertNotIn("10 小时", result.exception or "")
        self.assertFalse(result.retry_requested)

    async def test_timeout_preserves_session_and_does_not_request_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            write_json(
                workspace / "plugins-lock.json",
                {"version": 1, "plugins": []},
            )
            cleaned_up = False

            async def fake_query(*_args: object, **_kwargs: object):
                nonlocal cleaned_up
                try:
                    yield SystemMessage(
                        subtype="init",
                        data={"session_id": "session-timeout", "cwd": str(workspace)},
                    )
                    await asyncio.Event().wait()
                finally:
                    cleaned_up = True

            with (
                patch("common.claude_agent.query", new=fake_query),
                patch("common.claude_agent.CLAUDE_AGENT_TIMEOUT_SECONDS", 0.001),
            ):
                result = await run_claude("测试提示", cwd=workspace)

        self.assertTrue(cleaned_up)
        self.assertEqual(result.session_id, "session-timeout")
        self.assertEqual(result.exception_type, "TimeoutError")
        self.assertIn("10 小时", result.exception or "")
        self.assertFalse(result.retry_requested)

    async def test_external_cancellation_is_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            write_json(
                workspace / "plugins-lock.json",
                {"version": 1, "plugins": []},
            )
            started = asyncio.Event()
            cleaned_up = False

            async def fake_query(*_args: object, **_kwargs: object):
                nonlocal cleaned_up
                try:
                    yield SystemMessage(
                        subtype="init",
                        data={"session_id": "session-cancel", "cwd": str(workspace)},
                    )
                    started.set()
                    await asyncio.Event().wait()
                finally:
                    cleaned_up = True

            with patch("common.claude_agent.query", new=fake_query):
                task = asyncio.create_task(run_claude("测试提示", cwd=workspace))
                await started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        self.assertTrue(cleaned_up)

    async def test_normal_result_followed_by_process_error_does_not_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            write_json(
                workspace / "plugins-lock.json",
                {"version": 1, "plugins": []},
            )

            async def fake_query(*_args: object, **_kwargs: object):
                yield SystemMessage(
                    subtype="init",
                    data={"session_id": "session-1", "cwd": str(workspace)},
                )
                yield ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="session-1",
                    result="Agent 的完整结果",
                    terminal_reason="completed",
                )
                raise ProcessError("process failed", exit_code=1)

            with patch("common.claude_agent.query", new=fake_query):
                result = await run_claude("测试提示", cwd=workspace)

        self.assertFalse(result.retry_requested)

    async def test_session_mismatch_clears_api_retry_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            write_json(
                workspace / "plugins-lock.json",
                {"version": 1, "plugins": []},
            )

            async def fake_query(*_args: object, **_kwargs: object):
                yield SystemMessage(
                    subtype="init",
                    data={"session_id": "other-session", "cwd": str(workspace)},
                )
                yield ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=True,
                    num_turns=1,
                    session_id="other-session",
                    result=None,
                    api_error_status=500,
                    terminal_reason="api_error",
                )

            with patch("common.claude_agent.query", new=fake_query):
                result = await run_claude(
                    "测试提示",
                    cwd=workspace,
                    resume_session_id="session-1",
                )

        self.assertEqual(result.exception_type, "SessionMismatchError")
        self.assertFalse(result.retry_requested)

    async def test_model_mismatch_is_reported_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            write_json(workspace / "plugins-lock.json", {"version": 1, "plugins": []})

            async def fake_query(*_args: object, **_kwargs: object):
                yield SystemMessage(
                    subtype="init",
                    data={
                        "session_id": "session-1",
                        "cwd": str(workspace),
                        "model": "other-model",
                    },
                )
                yield ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="session-1",
                    result="Agent 的完整结果",
                    terminal_reason="completed",
                )

            with patch("common.claude_agent.query", new=fake_query):
                result = await run_claude("测试提示", cwd=workspace)

        self.assertEqual(result.exception_type, "ModelMismatchError")
        self.assertFalse(result.retry_requested)


class AgentDecisionTest(unittest.IsolatedAsyncioTestCase):
    def test_rendered_system_prompt_uses_complete_xml_contract(self) -> None:
        prompt = render_decision_system_prompt(
            "completed 表示领域工作已完成；continue 表示仍可继续；blocked 仅限外部输入缺失。",
            {"产品初稿": {"content": "原始项目资料 <tag> & 内容"}},
        )

        self.assertTrue(prompt.startswith("<role>\n"))
        self.assertTrue(prompt.endswith("</output>\n"))
        for tag in (
            "<role>",
            "</role>",
            "<project_context>",
            "</project_context>",
            "<responsibility>",
            "</responsibility>",
            "<completion>",
            "</completion>",
            "<output>",
            "</output>",
        ):
            self.assertIn(tag, prompt)
        for required in (
            "最高项目负责人、工程负责人、专业开发者和 Agent 专家",
            "assistant 是你此前发给 Agent 的指令或结构化回复",
            "user 是 Agent 返回给你的完整执行结果",
            "completed 表示领域工作已完成",
            '"verdict": "completed | continue | blocked"',
            "首字符必须是 {，末字符必须是 }",
            "`completed`：`answer` 必须是空字符串",
            "`continue`：`answer` 必须是非空的下一步指令",
            "`blocked`：`answer` 必须是空字符串",
            "`reason` 始终必须是非空字符串",
            "禁止 JSON 之外的任何文本",
            "原始项目资料 &lt;tag&gt; &amp; 内容",
        ):
            self.assertIn(required, prompt)
        self.assertEqual(prompt.count("completed 表示领域工作已完成"), 1)
        responsibility = prompt.partition("<responsibility>")[2].partition("</responsibility>")[0]
        completion = prompt.partition("<completion>")[2].partition("</completion>")[0]
        self.assertNotIn("completed 表示领域工作已完成", responsibility)
        self.assertIn("completed 表示领域工作已完成", completion)
        self.assertNotIn("```", prompt)

    def test_strict_invariants_and_legacy_actions(self) -> None:
        with self.assertRaises(ValueError):
            AgentDecision(
                verdict="continue", answer="", reason="原因", required_inputs=[]
            )
        with self.assertRaises(ValueError):
            AgentDecision(
                verdict="blocked", answer="", reason="原因", required_inputs=[]
            )
        parsed = AgentDecision.model_validate(
            {
                "action": "answer",
                "answer": "继续处理",
                "reason": "尚未完成",
                "required_inputs": [],
            }
        )
        self.assertEqual(parsed.verdict, "continue")
        legacy_approve = AgentDecision.model_validate(
            {
                "action": "approve",
                "answer": "继续处理",
                "reason": "旧协议同意继续",
                "required_inputs": [],
            }
        )
        self.assertEqual(legacy_approve.verdict, "continue")

    async def test_request_decision_uses_exact_required_system_prompt_once(self) -> None:
        calls: list[str] = []
        result = AgentDecision(
            verdict="completed", answer="", reason="已完成", required_inputs=[]
        )

        async def fake_parse_response(*_args: object, **kwargs: object) -> AgentDecision:
            calls.append(str(kwargs["system_prompt"]))
            return result

        with patch("common.decision.parse_response", new=fake_parse_response):
            data, attempts, raw = await request_decision(
                [{"role": "system", "content": "完整 XML system"}],
                object(),  # type: ignore[arg-type]
                system_prompt="完整 XML system",
            )

        self.assertEqual(data, result.model_dump())
        self.assertEqual(parse_agent_decision(data), result)
        self.assertEqual(raw, result.model_dump_json())
        self.assertEqual(attempts, 1)
        self.assertEqual(calls, ["完整 XML system"])

    async def test_request_decision_requires_explicit_system_prompt(self) -> None:
        with self.assertRaises(TypeError):
            await request_decision(  # type: ignore[call-arg]
                [{"role": "system", "content": "历史 system"}],
                object(),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
