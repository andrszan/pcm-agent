from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.agent_decision_loop import AIDecisionFailure
from common.state import write_requirement_step_result, write_state
from steps.step_14_trd_design.step import (
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    STEP,
    TRDDesignBlocked,
    result,
)


class TRDDesignCLITests(unittest.TestCase):
    def setUp(self) -> None:
        import run_step as cli

        self.cli = cli
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.demo_root = Path(self.temporary_directory.name)
        (self.demo_root / "runs").mkdir()
        self.demo_root_patch = patch.object(cli, "DEMO_ROOT", self.demo_root)
        self.demo_root_patch.start()

    def tearDown(self) -> None:
        self.demo_root_patch.stop()
        self.temporary_directory.cleanup()

    @staticmethod
    def args(run_id: str, step: int = STEP) -> Namespace:
        return Namespace(
            step=step,
            product_draft=None,
            workspace_root=None,
            catalog_path=None,
            run_id=run_id,
        )

    def make_run(
        self,
        *,
        advanced: bool = False,
        trd_path: str | None = "docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md",
    ) -> tuple[Path, dict]:
        run_dir = self.demo_root / "runs/test-run"
        (run_dir / "steps/requirements/BR-001").mkdir(parents=True)
        workspace_root = self.demo_root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)
        cycle = {
            "requirement_id": "BR-001",
            "branch": "req/br-001",
            "return_node_after_completion": "phase_1:select_requirement",
        }
        if trd_path is not None:
            cycle["trd_path"] = trd_path
        state = {
            "status": "success" if advanced else "running",
            "phase": PHASE,
            "step": 15 if advanced else STEP,
            "current_step": 15 if advanced else STEP,
            "current_node": NEXT_NODE if advanced else CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "requirement_registry": {
                "schema_version": 1,
                "requirements": [
                    {
                        "id": "BR-001",
                        "title": "身份、角色访问与站内消息入口",
                        "order": 1,
                        "depends_on": [],
                        "status": "active",
                        "completion": None,
                    }
                ],
            },
            "active_requirement": "BR-001",
            "requirement_cycle": cycle,
            "blocked": None,
            "error": None,
        }
        if advanced:
            state["claude_sessions"] = {"trd_design_BR-001": "session-1"}
            write_requirement_step_result(
                run_dir,
                "BR-001",
                STEP,
                result(
                    "success",
                    "已完成。",
                    requirement_id="BR-001",
                    branch="req/br-001",
                    trd_path=trd_path,
                    trd_session_id="session-1",
                    outputs=[trd_path] if trd_path else [],
                ),
            )
        write_state(run_dir, state)
        return run_dir, state

    def test_dispatches_step_fourteen_and_prints_scoped_result(self) -> None:
        run_dir, _ = self.make_run(trd_path=None)
        saved = result(
            "success",
            "已完成。",
            requirement_id="BR-001",
            branch="req/br-001",
            trd_path="docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md",
            trd_session_id="session-1",
            outputs=["docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md"],
        )
        runner = AsyncMock(return_value=(run_dir, saved))
        stdout = io.StringIO()
        args = self.args(run_dir.name)
        with (
            patch.object(self.cli, "parse_args", return_value=args),
            patch.object(self.cli, "run_step_fourteen", runner),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(self.cli.main(), 0)
        runner.assert_called_once_with(args)
        self.assertEqual(
            stdout.getvalue().strip(),
            str(run_dir / "steps/requirements/BR-001/14.json"),
        )
        self.assertFalse((run_dir / "steps/14.json").exists())

    def test_failure_before_trd_path_has_no_state_or_result_side_effect(self) -> None:
        run_dir, _ = self.make_run(trd_path=None)
        before = (run_dir / "state.json").read_bytes()
        stderr = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(
                self.cli,
                "run_step_fourteen",
                side_effect=RuntimeError("simulated failure"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual((run_dir / "state.json").read_bytes(), before)
        self.assertFalse((run_dir / "steps/requirements/BR-001/14.json").exists())

    def test_valid_scope_failure_writes_sanitized_scoped_result(self) -> None:
        run_dir, _ = self.make_run()
        stderr = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(
                self.cli,
                "run_step_fourteen",
                side_effect=RuntimeError("secret=hidden"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads(
            (run_dir / "steps/requirements/BR-001/14.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(
            saved["trd_path"],
            "docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md",
        )
        self.assertNotIn("secret=hidden", json.dumps(saved, ensure_ascii=False))
        self.assertNotIn("secret=hidden", stderr.getvalue())

    def test_decision_failure_writes_safe_structured_diagnostic(self) -> None:
        run_dir, _ = self.make_run()
        stderr = io.StringIO()
        error = AIDecisionFailure(
            {"kind": "http", "http_status": 403, "request_id": "request-123"}
        )
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_fourteen", side_effect=error),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads(
            (run_dir / "steps/requirements/BR-001/14.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(saved["error"], error.as_error())
        self.assertEqual(
            json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["error"],
            error.as_error(),
        )
        self.assertIn("HTTP 403", stderr.getvalue())

    def test_blocked_exception_writes_scoped_blocked_result(self) -> None:
        run_dir, _ = self.make_run()
        error = TRDDesignBlocked(
            "缺少外部授权",
            ["外部授权"],
            requirement_id="BR-001",
            branch="req/br-001",
            trd_path="docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md",
            trd_session_id="session-1",
        )
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_fourteen", side_effect=error),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads(
            (run_dir / "steps/requirements/BR-001/14.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["status"], "blocked")
        self.assertEqual(saved["trd_session_id"], "session-1")

    def test_complete_current_success_is_not_overwritten(self) -> None:
        run_dir, _ = self.make_run(advanced=True)
        result_path = run_dir / "steps/requirements/BR-001/14.json"
        before_result = result_path.read_bytes()
        before_state = (run_dir / "state.json").read_bytes()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(
                self.cli,
                "run_step_fourteen",
                side_effect=OSError("simulated"),
            ),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual(result_path.read_bytes(), before_result)
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)

    def test_invalid_active_context_does_not_create_scoped_failure(self) -> None:
        run_dir, state = self.make_run()
        state["requirement_registry"]["requirements"][0]["status"] = "pending"
        write_state(run_dir, state)
        result_path = run_dir / "steps/requirements/BR-001/14.json"
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(
                self.cli,
                "run_step_fourteen",
                side_effect=RuntimeError("simulated"),
            ),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertFalse(result_path.exists())


if __name__ == "__main__":
    unittest.main()
