from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.files import write_json
from common.state import read_state, write_state
from steps.step_11_requirement_breakdown.step import (
    BACKLOG_PATH,
    CURRENT_NODE,
    NEXT_NODE,
    RequirementBreakdownBlocked,
)


class StepElevenCLITests(unittest.TestCase):
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
    def successful_result() -> dict:
        return {
            "step": 11,
            "name": "拆分 Backlog",
            "status": "success",
            "summary": "已完成 Backlog 拆分。",
            "applicable": True,
            "outputs": [BACKLOG_PATH.as_posix()],
            "blocked": None,
            "error": None,
        }

    def make_run(self, state: dict) -> Path:
        run_dir = self.demo_root / "runs" / "test-run"
        (run_dir / "steps").mkdir(parents=True)
        write_state(run_dir, state)
        return run_dir

    @staticmethod
    def args(run_id: str) -> Namespace:
        return Namespace(
            step=11,
            product_draft=None,
            workspace_root=None,
            catalog_path=None,
            run_id=run_id,
        )

    @staticmethod
    def step_eleven_state() -> dict:
        return {
            "status": "success",
            "phase": "project_initialization",
            "step": 11,
            "current_step": 11,
            "current_node": CURRENT_NODE,
            "blocked": None,
            "error": None,
        }

    @staticmethod
    def advanced_state() -> dict:
        return {
            "status": "success",
            "phase": "phase_1_requirement_development",
            "step": 12,
            "current_step": 12,
            "current_node": NEXT_NODE,
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }

    def test_has_step_eleven_success_requires_exact_valid_shape(self) -> None:
        run_dir = self.make_run(self.step_eleven_state())
        result_path = run_dir / "steps/11.json"
        success = self.successful_result()
        write_json(result_path, success)
        self.assertTrue(self.cli.has_step_success(run_dir, 11))

        cases = {
            "missing": {"status": "success"},
            "extra": {**success, "unexpected": "field"},
            "wrong-output": success | {"outputs": []},
            "false-applicable": success | {"applicable": False},
            "wrong-step-type": success | {"step": "11"},
            "blank-summary": success | {"summary": "  "},
        }
        for label, value in cases.items():
            with self.subTest(label=label):
                write_json(result_path, value)
                self.assertFalse(self.cli.has_step_success(run_dir, 11))

    def test_dispatches_step_eleven_runner(self) -> None:
        run_dir = self.make_run(self.step_eleven_state())
        args = self.args(run_dir.name)
        runner = AsyncMock(return_value=(run_dir, self.successful_result()))
        with (
            patch.object(self.cli, "parse_args", return_value=args),
            patch.object(self.cli, "run_step_eleven", runner),
        ):
            self.assertEqual(self.cli.main(), 0)
        runner.assert_awaited_once_with(args)

    def test_blocked_exception_writes_step_eleven_resume_fields(self) -> None:
        run_dir = self.make_run(self.step_eleven_state())
        blocked = RequirementBreakdownBlocked(
            "缺少外部授权", ["需求负责人授权"], [BACKLOG_PATH.as_posix()]
        )
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_eleven", AsyncMock(side_effect=blocked)),
        ):
            self.assertEqual(self.cli.main(), 1)

        result = json.loads((run_dir / "steps/11.json").read_text(encoding="utf-8"))
        expected_blocked = {
            "reason": "缺少外部授权",
            "required_inputs": ["需求负责人授权"],
            "resume_phase": "project_initialization",
            "resume_node": CURRENT_NODE,
            "resume_step": 11,
        }
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["outputs"], [BACKLOG_PATH.as_posix()])
        self.assertEqual(result["blocked"], expected_blocked)
        self.assertIsNone(result["error"])
        state = read_state(run_dir)
        self.assertEqual(state["blocked"], expected_blocked)
        self.assertEqual((state["step"], state["current_step"], state["current_node"]), (11, 11, CURRENT_NODE))

    def test_complete_success_preserves_result_and_advanced_state_after_errors(self) -> None:
        for failure in (
            OSError("模拟失败"),
            RequirementBreakdownBlocked("缺少授权", ["外部授权"]),
        ):
            with self.subTest(failure=type(failure).__name__):
                run_dir = self.make_run(self.advanced_state())
                success = self.successful_result()
                write_json(run_dir / "steps/11.json", success)
                with (
                    patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
                    patch.object(self.cli, "run_step_eleven", AsyncMock(side_effect=failure)),
                ):
                    self.assertEqual(self.cli.main(), 1)
                self.assertEqual(json.loads((run_dir / "steps/11.json").read_text(encoding="utf-8")), success)
                self.assertEqual(read_state(run_dir), self.advanced_state())
                shutil.rmtree(run_dir)

    def test_incomplete_success_is_overwritten_and_rewinds_to_step_eleven(self) -> None:
        run_dir = self.make_run(self.advanced_state())
        write_json(run_dir / "steps/11.json", {"status": "success"})
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_eleven", AsyncMock(side_effect=OSError("模拟失败"))),
        ):
            self.assertEqual(self.cli.main(), 1)
        result = json.loads((run_dir / "steps/11.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["name"], "拆分 Backlog")
        state = read_state(run_dir)
        self.assertEqual(state["status"], "failed")
        self.assertEqual((state["step"], state["current_step"], state["current_node"]), (11, 11, CURRENT_NODE))


if __name__ == "__main__":
    unittest.main()
