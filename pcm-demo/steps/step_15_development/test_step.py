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
from common.files import write_json
from common.state import read_state, write_requirement_step_result, write_state
from model_policy import get_agent_profile
from steps.step_15_development.step import (
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    STEP,
    DevelopmentBlocked,
    result,
    run,
)
import steps.step_15_development.step as development_step


def agent_result(
    workspace: Path,
    *,
    session: str = "development-session-1",
    text: str = "已完成实现、适用测试、真实验证和审查，没有剩余工作、验证缺口或阻断项。",
) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(workspace),
            "skills": ["dev-workflow"],
            "slash_commands": ["dev-workflow"],
        },
        text=text,
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


class DevelopmentTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        trd_path = "docs/trd/BR-001.md"
        (workspace / "docs/trd").mkdir(parents=True)
        (workspace / trd_path).write_text(
            "# 活动 TRD\n\nTRD_CONTEXT_MARKER：必须验证账户锁定恢复。\n",
            encoding="utf-8",
        )
        (run_dir / "steps").mkdir(parents=True)
        state = {
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
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
                "branch": "req/br-001",
                "trd_path": trd_path,
            },
            "blocked": None,
            "error": None,
        }
        write_requirement_step_result(
            run_dir,
            "BR-001",
            14,
            {
                "step": 14,
                "name": "形成活动 TRD",
                "status": "success",
                "summary": "已完成。",
                "applicable": True,
                "outputs": [trd_path],
                "blocked": None,
                "error": None,
                "requirement_id": "BR-001",
                "branch": "req/br-001",
                "trd_path": trd_path,
                "trd_session_id": "trd-session-1",
            },
        )
        write_state(run_dir, state)
        return run_dir, workspace, state

    @staticmethod
    def run_step(run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    def test_prompt_completed_result_and_session_are_requirement_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []
            decision_prompts: list[str] = []

            async def agent(prompt: str, **_: object) -> ClaudeRunResult:
                prompts.append(prompt)
                return agent_result(workspace)

            async def decide(*_: object, **kwargs: object) -> tuple[dict, int, str]:
                decision_prompts.append(str(kwargs["system_prompt"]))
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )

            self.assertEqual(len(prompts), 1)
            self.assertTrue(prompts[0].startswith("/dev-workflow\n"))
            self.assertIn("BR-001 账户访问", prompts[0])
            self.assertIn("docs/trd/BR-001.md", prompts[0])
            self.assertEqual(len(decision_prompts), 1)
            self.assertIn("docs/trd/BR-001.md", decision_prompts[0])
            self.assertIn("TRD_CONTEXT_MARKER：必须验证账户锁定恢复。", decision_prompts[0])
            self.assertIn(development_step.DEVELOPMENT_DECISION_RULES, decision_prompts[0])
            self.assertNotIn("TRD_CONTEXT_MARKER", prompts[0])
            self.assertEqual(saved["outputs"], [])
            self.assertEqual(saved["development_session_id"], "development-session-1")
            self.assertEqual(
                set(saved),
                {
                    "step",
                    "name",
                    "status",
                    "summary",
                    "applicable",
                    "outputs",
                    "blocked",
                    "error",
                    "requirement_id",
                    "trd_path",
                    "development_session_id",
                },
            )
            completed = read_state(run_dir)
            self.assertEqual(completed["claude_sessions"]["development_BR-001"], "development-session-1")
            self.assertEqual(
                completed["requirement_cycle"]["development_session_id"], "development-session-1"
            )
            self.assertEqual(
                (completed["step"], completed["current_step"], completed["current_node"]),
                (16, 16, NEXT_NODE),
            )

    def test_blocked_saves_session_and_keeps_current_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("blocked", reason="缺少外部授权", required_inputs=["外部授权"])

            with self.assertRaises(DevelopmentBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            saved = json.loads(
                (run_dir / "steps/requirements/BR-001/15.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["status"], "blocked")
            self.assertEqual(saved["development_session_id"], "development-session-1")
            blocked = read_state(run_dir)
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(
                (blocked["step"], blocked["current_step"], blocked["current_node"]),
                (STEP, STEP, CURRENT_NODE),
            )
            self.assertEqual(
                blocked["requirement_cycle"]["development_session_id"], "development-session-1"
            )

    def test_continue_reuses_development_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[tuple[object, object, object, object]] = []
            decisions = iter(
                [
                    decision("continue", answer="请继续完成遗漏。"),
                    decision("completed"),
                ]
            )

            async def agent(_prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append(
                    (
                        kwargs.get("resume_session_id"),
                        kwargs.get("task"),
                        kwargs.get("model"),
                        kwargs.get("effort"),
                    )
                )
                value = agent_result(workspace)
                value.text = f"第 {len(calls)} 轮完成情况。"
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
            profile = get_agent_profile("development")
            self.assertEqual(
                calls,
                [
                    (None, "development", profile.model, profile.effort),
                    (
                        "development-session-1",
                        "development",
                        profile.model,
                        profile.effort,
                    ),
                ],
            )

    def test_eight_continue_decisions_still_allow_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls = 0
            decisions = iter(
                [decision("continue", answer=f"继续完成第 {index} 轮。") for index in range(8)]
                + [decision("completed")]
            )

            async def agent(_prompt: str, **_kwargs: object) -> ClaudeRunResult:
                nonlocal calls
                calls += 1
                value = agent_result(workspace)
                value.text = f"第 {calls} 轮完成情况。"
                return value

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return next(decisions)

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )

            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls, 9)

    def test_saved_success_recovers_advance_and_advanced_rerun_skips_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            original_write_state = development_step.write_state

            def interrupt_advance(path: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("simulated state interruption")
                original_write_state(path, value)

            with patch.object(development_step, "write_state", side_effect=interrupt_advance):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=decide,
                        config_loader=lambda: object(),
                    )
            interrupted = read_state(run_dir)
            self.assertEqual(
                json.loads(
                    (run_dir / "steps/requirements/BR-001/15.json").read_text(encoding="utf-8")
                )["status"],
                "success",
            )

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("不应再次调用 Agent")

            recovered = self.run_step(run_dir, interrupted, agent_runner=forbidden)
            self.assertEqual(recovered["status"], "success")
            advanced = read_state(run_dir)
            self.assertEqual(
                self.run_step(run_dir, advanced, agent_runner=forbidden), recovered
            )

    def test_inconsistent_or_unusable_trd_fails_before_agent(self) -> None:
        for case in ("result-mismatch", "missing", "empty"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                trd = workspace / "docs/trd/BR-001.md"
                if case == "result-mismatch":
                    path = run_dir / "steps/requirements/BR-001/14.json"
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    saved["trd_path"] = "docs/trd/other.md"
                    write_json(path, saved)
                elif case == "missing":
                    trd.unlink()
                else:
                    trd.write_text("\n", encoding="utf-8")

                async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                    raise AssertionError("TRD 预检失败时不得调用 Agent")

                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state, agent_runner=forbidden)


if __name__ == "__main__":
    unittest.main()
