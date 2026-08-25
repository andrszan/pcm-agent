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
from steps.step_12_initialize_requirement_registry.step import (
    CURRENT_NODE,
    NAME,
    NEXT_NODE,
    PHASE,
    STEP,
)


class StepTwelveCLITests(unittest.TestCase):
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
    def catalog() -> list[dict]:
        return [
            {"id": "REQ-001", "title": "账户访问", "order": 1, "depends_on": []},
            {"id": "REQ-002", "title": "订单管理", "order": 2, "depends_on": ["REQ-001"]},
        ]

    @classmethod
    def source(cls) -> dict:
        return {
            "path": "docs/backlog/backlog.md",
            "sha256": "a" * 64,
            "root_main_sha": "b" * 40,
        }

    @classmethod
    def successful_result(cls) -> dict:
        return {
            "step": STEP,
            "name": NAME,
            "status": "success",
            "summary": "Backlog 静态需求已解析。",
            "applicable": True,
            "outputs": [],
            "blocked": None,
            "error": None,
            "source": cls.source(),
            "requirement_catalog": cls.catalog(),
        }

    @classmethod
    def advanced_state(cls) -> dict:
        catalog = cls.catalog()
        return {
            "status": "success",
            "phase": PHASE,
            "step": 13,
            "current_step": 13,
            "current_node": NEXT_NODE,
            "requirement_registry": {
                "schema_version": 1,
                "source": cls.source(),
                "requirements": [
                    {**requirement, "status": "pending", "completion": None}
                    for requirement in catalog
                ],
            },
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }

    @staticmethod
    def step_twelve_state() -> dict:
        return {
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }

    def make_run(self, state: dict) -> Path:
        run_dir = self.demo_root / "runs" / "test-run"
        (run_dir / "steps").mkdir(parents=True)
        write_state(run_dir, state)
        return run_dir

    @staticmethod
    def args(run_id: str, step: int = STEP) -> Namespace:
        return Namespace(
            step=step,
            product_draft=None,
            workspace_root=None,
            catalog_path=None,
            run_id=run_id,
        )

    def test_has_step_twelve_success_requires_exact_static_shape(self) -> None:
        run_dir = self.make_run(self.step_twelve_state())
        result_path = run_dir / "steps/12.json"
        success = self.successful_result()
        write_json(result_path, success)
        self.assertTrue(self.cli.has_step_success(run_dir, STEP))

        cases = {
            "missing": {"status": "success"},
            "extra": success | {"unexpected": "field"},
            "wrong-source": success | {"source": {"path": "docs/backlog/backlog.md"}},
            "dynamic-field": success | {"requirement_catalog": [{**self.catalog()[0], "status": "pending"}]},
            "duplicate-order": success | {"requirement_catalog": [self.catalog()[0], {**self.catalog()[1], "order": 1}]},
            "cycle": success | {"requirement_catalog": [{**self.catalog()[0], "depends_on": ["REQ-002"]}, self.catalog()[1]]},
            "wrong-step-type": success | {"step": "12"},
            "blank-summary": success | {"summary": "  "},
        }
        for label, value in cases.items():
            with self.subTest(label=label):
                write_json(result_path, value)
                self.assertFalse(self.cli.has_step_success(run_dir, STEP))
        self.assertFalse(self.cli.has_step_success(run_dir, 13))

    def test_dispatches_step_twelve_runner(self) -> None:
        run_dir = self.make_run(self.step_twelve_state())
        args = self.args(run_dir.name)
        runner = AsyncMock(return_value=(run_dir, self.successful_result()))
        with (
            patch.object(self.cli, "parse_args", return_value=args),
            patch.object(self.cli, "run_step_twelve", runner),
        ):
            self.assertEqual(self.cli.main(), 0)
        runner.assert_awaited_once_with(args)

    def test_exception_writes_sanitized_failure_at_registry_node(self) -> None:
        run_dir = self.make_run(self.step_twelve_state())
        secret = "api_key=do-not-leak"
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_twelve", AsyncMock(side_effect=RuntimeError(secret))),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads((run_dir / "steps/12.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["name"], NAME)
        self.assertEqual(saved["error"]["message"], "需求注册表初始化未完成。")
        self.assertNotIn(secret, json.dumps(saved, ensure_ascii=False))
        failed = read_state(run_dir)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual((failed["step"], failed["current_step"], failed["current_node"]), (STEP, STEP, CURRENT_NODE))

    def test_legacy_step_twelve_position_is_preserved_after_repeated_failure(self) -> None:
        legacy = self.step_twelve_state()
        legacy["current_node"] = NEXT_NODE
        run_dir = self.make_run(legacy)
        for _ in range(2):
            with patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)):
                self.assertEqual(self.cli.main(), 1)
            saved = read_state(run_dir)
            self.assertEqual(
                (saved["step"], saved["current_step"], saved["current_node"]),
                (STEP, STEP, NEXT_NODE),
            )
            self.assertEqual(saved["status"], "failed")

    def test_complete_success_protects_result_and_advanced_state_after_error(self) -> None:
        run_dir = self.make_run(self.advanced_state())
        success = self.successful_result()
        write_json(run_dir / "steps/12.json", success)
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_twelve", AsyncMock(side_effect=OSError("simulated"))),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual(json.loads((run_dir / "steps/12.json").read_text(encoding="utf-8")), success)
        self.assertEqual(read_state(run_dir), self.advanced_state())

    def test_incomplete_success_is_overwritten_and_unimplemented_range_returns_two(self) -> None:
        run_dir = self.make_run(self.advanced_state())
        write_json(run_dir / "steps/12.json", {"status": "success"})
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_twelve", AsyncMock(side_effect=OSError("simulated"))),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual(json.loads((run_dir / "steps/12.json").read_text(encoding="utf-8"))["status"], "failed")
        state = read_state(run_dir)
        self.assertEqual((state["step"], state["current_step"], state["current_node"]), (13, 13, NEXT_NODE))
        self.assertEqual(state["status"], "failed")

        with patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name, 16)):
            self.assertEqual(self.cli.main(), 2)
        shutil.rmtree(run_dir)


if __name__ == "__main__":
    unittest.main()
