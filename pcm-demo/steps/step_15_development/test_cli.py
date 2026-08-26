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

from common.files import write_json
from common.state import read_state, write_requirement_step_result, write_state
from steps.step_15_development.step import (
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    STEP,
    DevelopmentBlocked,
    result,
)


class DevelopmentCLITests(unittest.TestCase):
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
        self, *, advanced: bool = False, session: bool = False, run_id: str = "test-run"
    ) -> tuple[Path, dict]:
        run_dir = self.demo_root / "runs" / run_id
        workspace_root = self.demo_root / "workspace-root"
        workspace = workspace_root / "project"
        trd_path = "docs/trd/BR-001.md"
        (workspace / "docs/trd").mkdir(parents=True, exist_ok=True)
        (workspace / trd_path).write_text("# TRD\n\n有效内容。\n", encoding="utf-8")
        (run_dir / "steps").mkdir(parents=True)
        cycle = {
            "requirement_id": "BR-001",
            "branch": "req/br-001",
            "trd_path": trd_path,
        }
        state = {
            "status": "success" if advanced else "running",
            "phase": PHASE,
            "step": STEP + 1 if advanced else STEP,
            "current_step": STEP + 1 if advanced else STEP,
            "current_node": NEXT_NODE if advanced else CURRENT_NODE,
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
            "requirement_cycle": cycle,
            "blocked": None,
            "error": None,
        }
        if session:
            cycle["development_session_id"] = "development-session-1"
            state["claude_sessions"] = {"development_BR-001": "development-session-1"}
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
        return run_dir, state

    def complete_result(self) -> dict:
        return result(
            "success",
            "已完成。",
            requirement_id="BR-001",
            trd_path="docs/trd/BR-001.md",
            development_session_id="development-session-1",
        )

    def test_dispatches_step_fifteen_and_prints_scoped_path(self) -> None:
        run_dir, _ = self.make_run()
        runner = AsyncMock(return_value=(run_dir, self.complete_result()))
        stdout = io.StringIO()
        args = self.args(run_dir.name)
        with (
            patch.object(self.cli, "parse_args", return_value=args),
            patch.object(self.cli, "run_step_fifteen", runner),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(self.cli.main(), 0)
        runner.assert_awaited_once_with(args)
        self.assertEqual(
            stdout.getvalue().strip(), str(run_dir / "steps/requirements/BR-001/15.json")
        )

    def test_complete_scoped_success_protects_state_and_result(self) -> None:
        run_dir, _ = self.make_run(advanced=True, session=True)
        success = self.complete_result()
        result_path = run_dir / "steps/requirements/BR-001/15.json"
        write_requirement_step_result(run_dir, "BR-001", STEP, success)
        before_state = (run_dir / "state.json").read_bytes()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_fifteen", side_effect=OSError("simulated")),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual(result_path.read_bytes(), json.dumps(success, ensure_ascii=False, indent=2).encode() + b"\n")
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)
        self.assertFalse((run_dir / "logs").exists())

    def test_incomplete_or_failed_scoped_result_is_not_protected(self) -> None:
        for saved in ({"status": "success"}, {"status": "failed"}):
            with self.subTest(saved=saved):
                run_dir, _ = self.make_run(run_id=f"test-{saved['status']}")
                write_requirement_step_result(run_dir, "BR-001", STEP, saved)
                with (
                    patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
                    patch.object(self.cli, "run_step_fifteen", side_effect=OSError("simulated")),
                ):
                    self.assertEqual(self.cli.main(), 1)
                replaced = json.loads(
                    (run_dir / "steps/requirements/BR-001/15.json").read_text(encoding="utf-8")
                )
                self.assertEqual(replaced["status"], "failed")
                self.assertEqual(read_state(run_dir)["current_node"], CURRENT_NODE)

    def test_failed_exception_writes_specific_redacted_diagnostic(self) -> None:
        run_dir, _ = self.make_run()
        stderr = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_fifteen", side_effect=RuntimeError("secret=hidden")),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads(
            (run_dir / "steps/requirements/BR-001/15.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["error"]["message"], "secret=[REDACTED]")
        self.assertEqual(saved["error"]["diagnostic_path"], "logs/step-15-error.json")
        self.assertNotIn("secret=hidden", json.dumps(saved, ensure_ascii=False))
        self.assertIn("secret=[REDACTED]", stderr.getvalue())
        self.assertIn("logs/step-15-error.json", stderr.getvalue())

    def test_blocked_exception_writes_a_scoped_blocked_result(self) -> None:
        run_dir, _ = self.make_run(session=True)
        blocked = DevelopmentBlocked(
            "缺少外部授权",
            ["外部授权"],
            requirement_id="BR-001",
            trd_path="docs/trd/BR-001.md",
            development_session_id="development-session-1",
        )
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_fifteen", side_effect=blocked),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads(
            (run_dir / "steps/requirements/BR-001/15.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["status"], "blocked")
        self.assertEqual(saved["development_session_id"], "development-session-1")


if __name__ == "__main__":
    unittest.main()
