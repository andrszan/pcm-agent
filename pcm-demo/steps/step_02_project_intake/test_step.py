from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.files import sha256, write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_02_project_intake.step import (
    OUTPUTS,
    ProjectIntakeBlocked,
    decision_prompt,
    run,
)


def agent_result(*, session: str = "session-1", text: str = "需要确认") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={"skills": ["project-intake"], "slash_commands": ["project-intake"]},
        text=text,
        result_subtype="success",
        is_error=False,
        session_id=session,
        stop_reason="end_turn",
        num_turns=1,
        total_cost_usd=0.1,
        exception=None,
    )


class ProjectIntakeTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        (run_dir / "logs").mkdir()
        workspace = root / "workspace"
        (workspace / ".claude").mkdir(parents=True)
        (workspace / "docs").mkdir()
        draft = root / "draft.md"
        draft.write_text("# 产品初稿\n", encoding="utf-8")
        (workspace / "docs/产品初稿.md").write_bytes(draft.read_bytes())
        write_json(
            run_dir / "steps/01.json",
            {
                "step": 1,
                "name": "建立项目工作区",
                "status": "success",
                "summary": "完成",
                "applicable": True,
                "outputs": ["docs/产品初稿.md"],
                "blocked": None,
                "error": None,
            },
        )
        (workspace / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        (workspace / "AGENTS.md").write_text("规则\n", encoding="utf-8")
        (workspace / ".claude/settings.json").write_text("{}\n", encoding="utf-8")
        root_repository = initialize_root_repository(workspace)
        state = {
            "run_id": "test",
            "status": "success",
            "current_step": 1,
            "publication_phase": "git_initialized",
            "root_repository": root_repository,
            "workspace": {
                "root": str(root),
                "staging_path": str(root / "staging-unused"),
                "final_path": str(workspace),
            },
            "checks": {
                "template_capabilities_present": True,
                "upstream_git_removed": True,
                "docs_reinitialized": True,
                "draft_hash_matches": True,
                "source_draft_unchanged": True,
                "renamed_to_final_path": True,
                "root_git_initialized": True,
                "root_git_is_final_path": True,
                "root_git_has_no_commits": True,
            },
            "input": {
                "source_path": str(draft),
                "source_sha256": sha256(draft),
                "published_path": str(workspace / "docs/产品初稿.md"),
            },
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    def test_agent_does_not_override_config_dir(self) -> None:
        from common.claude_agent import filtered_env

        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": "/custom"}, clear=False):
            env = filtered_env()
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            for relative in OUTPUTS:
                path = workspace / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# 完成\n", encoding="utf-8")
            state.update(
                {
                    "status": "success",
                    "claude_sessions": {"project_intake": "session-1"},
                    "project_intake": {
                        "last_agent_result": {"subtype": "success", "is_error": False}
                    },
                }
            )
            write_state(run_dir, state)

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("既有成功不应再次调用 Agent")

            outcome = asyncio.run(run(run_dir, state, agent_runner=unexpected_agent))
            self.assertEqual(outcome["status"], "success")
            self.assertIn("确认既有成功", outcome["summary"])

    def test_approve_is_explicit_developer_authorization(self) -> None:
        prompt = decision_prompt(
            {"action": "approve", "answer": "批准", "reason": "足够", "required_inputs": []}
        )
        self.assertEqual(prompt, "批准")

    def test_missing_outputs_runs_decision_then_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs):
                calls.append({"prompt": prompt, **kwargs})
                update = kwargs["on_update"]
                current = agent_result(
                    session="session-1", text=f"Agent 第 {len(calls)} 轮回答"
                )
                update(current)
                if len(calls) == 2:
                    for relative in OUTPUTS:
                        path = workspace / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("# 完成\n", encoding="utf-8")
                return current

            async def fake_decision(messages, config):
                return (
                    {"action": "approve", "answer": "批准", "reason": "输入足够", "required_inputs": []},
                    1,
                    json.dumps(
                        {"action": "approve", "answer": "批准", "reason": "输入足够", "required_inputs": []},
                        ensure_ascii=False,
                    ),
                )

            with patch("steps.step_02_project_intake.step.LLMConfig.load", return_value=object()):
                outcome = asyncio.run(
                    run(
                        run_dir,
                        state,
                        agent_runner=fake_agent,
                        decision_runner=fake_decision,
                    )
                )

            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertIn("批准", calls[1]["prompt"])
            saved = read_state(run_dir)
            self.assertNotIn("pending_agent_prompt", saved.get("project_intake", {}))
            self.assertEqual(
                saved["decision_conversations"]["project_intake"],
                {"path": "conversations/project_intake.json", "turn": 1},
            )
            history = json.loads(
                (run_dir / "conversations/project_intake.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [item["role"] for item in history["messages"]],
                ["system", "assistant", "user", "assistant", "user", "assistant"],
            )
            self.assertTrue(
                history["messages"][1]["content"].startswith("/project-intake")
            )
            self.assertEqual(history["messages"][2]["content"], "Agent 第 1 轮回答")
            self.assertIn('"action": "approve"', history["messages"][3]["content"])
            self.assertNotIn("发送给 Claude Agent SDK 的指令", history["messages"][3]["content"])
            self.assertEqual(history["messages"][4]["content"], "Agent 第 2 轮回答")
            self.assertNotIn(
                "allowed_inputs",
                json.dumps(history["messages"], ensure_ascii=False),
            )
            self.assertIn("已完成 project-intake", history["messages"][5]["content"])

    def test_budget_result_continues_with_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs):
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 1:
                    current = ClaudeRunResult(
                        init={
                            "skills": ["project-intake"],
                            "slash_commands": ["project-intake"],
                        },
                        text="预算达到上限前尚未完成",
                        result_subtype="error_max_budget_usd",
                        is_error=True,
                        session_id="session-1",
                        stop_reason="tool_use",
                        num_turns=7,
                        total_cost_usd=4.0,
                        exception="Exception: Reached maximum budget ($4)",
                    )
                else:
                    current = agent_result(session="session-1")
                    for relative in OUTPUTS:
                        path = workspace / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("# 完成\n", encoding="utf-8")
                kwargs["on_update"](current)
                return current

            async def fake_decision(messages, config):
                decision = {
                    "action": "continue",
                    "answer": "继续",
                    "reason": "已有 session 可恢复",
                    "required_inputs": [],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with patch(
                "steps.step_02_project_intake.step.LLMConfig.load", return_value=object()
            ):
                outcome = asyncio.run(
                    run(
                        run_dir,
                        state,
                        agent_runner=fake_agent,
                        decision_runner=fake_decision,
                    )
                )

            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertEqual(calls[0]["max_budget_usd"], 4.0)
            self.assertEqual(calls[1]["max_budget_usd"], 4.0)

    def test_structured_blocked_stops_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs):
                current = agent_result()
                kwargs["on_update"](current)
                return current

            async def fake_decision(messages, config):
                decision = {
                    "action": "blocked",
                    "answer": "需要真实账号",
                    "reason": "环境无法取得",
                    "required_inputs": ["PAYMENT_ACCOUNT"],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with patch("steps.step_02_project_intake.step.LLMConfig.load", return_value=object()):
                with self.assertRaises(ProjectIntakeBlocked) as raised:
                    asyncio.run(
                        run(
                            run_dir,
                            state,
                            agent_runner=fake_agent,
                            decision_runner=fake_decision,
                        )
                    )
            self.assertEqual(raised.exception.required_inputs, ["PAYMENT_ACCOUNT"])

    def test_skill_must_be_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs):
                return ClaudeRunResult(
                    init={"skills": [], "slash_commands": []},
                    text="",
                    result_subtype="success",
                    is_error=False,
                    session_id="session-1",
                    stop_reason="end_turn",
                    num_turns=1,
                    total_cost_usd=0.1,
                    exception=None,
                )

            with self.assertRaisesRegex(RuntimeError, "未加载 project-intake Skill"):
                asyncio.run(run(run_dir, state, agent_runner=fake_agent))

    def test_sdk_error_result_fails_without_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            called = False

            async def fake_agent(prompt: str, **kwargs):
                nonlocal called
                called = True
                return ClaudeRunResult(
                    init={"skills": ["project-intake"], "slash_commands": ["project-intake"]},
                    text="",
                    result_subtype="error_during_execution",
                    is_error=True,
                    session_id="session-1",
                    stop_reason=None,
                    num_turns=1,
                    total_cost_usd=0.1,
                    exception=None,
                )

            with self.assertRaisesRegex(RuntimeError, "执行失败"):
                asyncio.run(run(run_dir, state, agent_runner=fake_agent))
            self.assertTrue(called)
            history = json.loads(
                (run_dir / "conversations/project_intake.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                [item["role"] for item in history["messages"]],
                ["system", "assistant"],
            )
            self.assertTrue(
                history["messages"][1]["content"].startswith("/project-intake")
            )

    def test_resume_session_id_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            state["claude_sessions"] = {"project_intake": "old-session"}
            write_state(run_dir, state)

            async def fake_agent(prompt: str, **kwargs):
                update = kwargs["on_update"]
                current = agent_result(session="new-session")
                update(current)
                return current

            with self.assertRaisesRegex(RuntimeError, "session ID 不一致"):
                asyncio.run(run(run_dir, state, agent_runner=fake_agent))

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "docs/产品初稿.md").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "初稿.*不一致"):
                asyncio.run(run(run_dir, state))


if __name__ == "__main__":
    unittest.main()
