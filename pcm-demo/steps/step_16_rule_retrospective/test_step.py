from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.state import read_state, write_state
from steps.step_16_rule_retrospective.step import (
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    STEP,
    RuleRetrospectiveBlocked,
    run,
)
import steps.step_16_rule_retrospective.step as retrospective_step


def agent_result(workspace: Path, *, session: str = "development-session-1") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(workspace),
            "skills": ["session-rule-retrospective"],
            "slash_commands": ["session-rule-retrospective"],
        },
        text="已依据真实开发会话完成复盘，没有剩余复盘工作。",
        result_subtype="success",
        is_error=False,
        session_id=session,
        stop_reason="end_turn",
        num_turns=1,
        total_cost_usd=0.1,
        exception=None,
    )


def decision(
    verdict: str,
    *,
    answer: str = "",
    reason: str = "已核验",
    required_inputs: list[str] | None = None,
) -> tuple[dict, int, str]:
    value = {
        "verdict": verdict,
        "answer": answer,
        "reason": reason,
        "required_inputs": required_inputs or [],
    }
    return value, 1, json.dumps(value, ensure_ascii=False)


class RuleRetrospectiveTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps/requirements/BR-001").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)
        state = {
            "status": "running",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {
                "root": str(workspace_root),
                "final_path": str(workspace),
            },
            "requirement_registry": {
                "schema_version": 1,
                "requirements": [
                    {
                        "id": "BR-001",
                        "title": "账户访问",
                        "order": 1,
                        "depends_on": [],
                        "status": "active",
                        "completion": None,
                    }
                ],
            },
            "active_requirement": "BR-001",
            "requirement_cycle": {
                "requirement_id": "BR-001",
                "development_session_id": "development-session-1",
            },
            "claude_sessions": {"development_BR-001": "development-session-1"},
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    @staticmethod
    def run_step(run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    def test_no_change_reuses_development_session_with_independent_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []
            resumes: list[str | None] = []

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                persisted = read_state(run_dir)
                self.assertEqual(
                    persisted["claude_sessions"]["rule_retrospective_BR-001"],
                    "development-session-1",
                )
                prompts.append(prompt)
                resumes.append(kwargs.get("resume_session_id"))
                self.assertEqual(kwargs.get("model_tier"), "medium")
                self.assertEqual(kwargs.get("effort"), "medium")
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )

            self.assertEqual(resumes, ["development-session-1"])
            self.assertEqual(len(prompts), 1)
            self.assertTrue(prompts[0].startswith("/session-rule-retrospective 本次开发会话\n"))
            for forbidden in ("第 16 步", "PCM", "requirement:", "development-session-1"):
                self.assertNotIn(forbidden, prompts[0])
            self.assertEqual(saved["outputs"], [])
            self.assertEqual(saved["development_session_id"], "development-session-1")
            completed = read_state(run_dir)
            self.assertEqual(
                (completed["step"], completed["current_step"], completed["current_node"]),
                (17, 17, NEXT_NODE),
            )
            self.assertEqual(
                completed["decision_conversations"]["rule_retrospective_BR-001"]["path"],
                "conversations/rule_retrospective_BR-001.json",
            )
            self.assertEqual(completed["requirement_registry"]["requirements"][0]["status"], "active")
            self.assertIsNone(completed["requirement_registry"]["requirements"][0]["completion"])

    def test_continue_reuses_original_development_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            resumes: list[str | None] = []
            decisions = iter(
                [
                    decision("continue", answer="请补充可复用结论。"),
                    decision("completed"),
                ]
            )

            async def agent(_prompt: str, **kwargs: object) -> ClaudeRunResult:
                resumes.append(kwargs.get("resume_session_id"))
                value = agent_result(workspace)
                value.text = f"第 {len(resumes)} 轮复盘结果。"
                return value

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return next(decisions)

            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(resumes, ["development-session-1", "development-session-1"])

    def test_blocked_keeps_current_anchor_and_original_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("blocked", reason="缺少外部授权", required_inputs=["外部授权"])

            with self.assertRaises(RuleRetrospectiveBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            blocked = read_state(run_dir)
            self.assertEqual(
                (blocked["step"], blocked["current_step"], blocked["current_node"]),
                (STEP, STEP, CURRENT_NODE),
            )
            self.assertEqual(
                blocked["claude_sessions"]["rule_retrospective_BR-001"],
                "development-session-1",
            )
            saved = json.loads(
                (run_dir / "steps/requirements/BR-001/16.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["status"], "blocked")

    def test_result_then_state_recovery_and_advanced_rerun_skip_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            original_write_state = retrospective_step.write_state

            def interrupt_advance(path: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("simulated state interruption")
                original_write_state(path, value)

            with patch.object(retrospective_step, "write_state", side_effect=interrupt_advance):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=decide,
                        config_loader=lambda: object(),
                    )
            interrupted = read_state(run_dir)
            self.assertEqual(interrupted["current_node"], CURRENT_NODE)
            self.assertEqual(
                json.loads(
                    (run_dir / "steps/requirements/BR-001/16.json").read_text(encoding="utf-8")
                )["status"],
                "success",
            )

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("不应再次调用 Agent")

            recovered = self.run_step(run_dir, interrupted, agent_runner=forbidden)
            advanced = read_state(run_dir)
            workspace.rmdir()
            self.assertEqual(self.run_step(run_dir, advanced, agent_runner=forbidden), recovered)

    def test_agent_returning_different_session_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace, session="replacement-session")

            with self.assertRaisesRegex(RuntimeError, "session"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    config_loader=lambda: object(),
                )
            self.assertEqual(
                read_state(run_dir)["claude_sessions"]["rule_retrospective_BR-001"],
                "development-session-1",
            )

    def test_inconsistent_development_session_fails_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            state["requirement_cycle"]["development_session_id"] = "other-session"
            write_state(run_dir, state)

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("session 不一致时不得调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "开发 session"):
                self.run_step(run_dir, state, agent_runner=forbidden)

    def test_step_does_not_import_git_or_hashing_modules(self) -> None:
        for name in ("subprocess", "hashlib", "stat", "os"):
            self.assertNotIn(name, vars(retrospective_step))


if __name__ == "__main__":
    unittest.main()
