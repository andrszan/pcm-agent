from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.files import write_json
from common.state import read_state, write_requirement_step_result, write_state
from steps.step_13_select_requirement.step import (
    CURRENT_NODE,
    NAME,
    NEXT_NODE,
    PHASE,
    STEP,
    failure_scope,
    result,
)


class SelectRequirementCLITests(unittest.TestCase):
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
            {"id": "BR-001", "title": "账户", "order": 1, "depends_on": []},
            {"id": "BR-002", "title": "订单", "order": 2, "depends_on": ["BR-001"]},
        ]

    @staticmethod
    def source() -> dict:
        return {
            "path": "docs/backlog/backlog.md",
            "sha256": "a" * 64,
        }

    def repositories(self) -> list[dict]:
        workspace = (self.demo_root / "workspace").resolve()
        return [
            {"name": "root", "path": str(workspace), "branch": "main", "worktree_clean": True},
            {"name": "frontend", "path": str(workspace / "frontend"), "branch": "main", "worktree_clean": True},
        ]

    def make_run(self, state: dict | None = None) -> Path:
        run_dir = self.demo_root / "runs" / "test-run"
        (run_dir / "steps").mkdir(parents=True)
        workspace = (self.demo_root / "workspace").resolve()
        (workspace / "frontend").mkdir(parents=True)
        repositories = self.repositories()
        names = [repository["name"] for repository in repositories]
        write_json(
            run_dir / "steps/08.json",
            {
                "step": 8,
                "name": "首次提交适用仓库",
                "status": "success",
                "summary": "已提交。",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "applicable_repositories": names,
                "repositories": [
                    {
                        "name": name,
                        "path": "." if name == "root" else name,
                        "branch": "main",
                        "worktree_clean": True,
                    }
                    for name in names
                ],
            },
        )
        write_json(
            run_dir / "steps/12.json",
            {
                "step": 12,
                "name": "解析 Backlog 并初始化需求注册表",
                "status": "success",
                "summary": "已初始化。",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "source": self.source(),
                "requirement_catalog": self.catalog(),
            },
        )
        default = {
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(self.demo_root.resolve()), "final_path": str(workspace)},
            "applicable_repositories": names,
            "repositories": repositories,
            "requirement_registry": {
                "schema_version": 1,
                "source": self.source(),
                "requirements": [
                    {**item, "status": "pending", "completion": None}
                    for item in self.catalog()
                ],
            },
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state or default)
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

    def active_state(self, requirement_id: str = "BR-001", *, advanced: bool = False) -> dict:
        repositories = self.repositories()
        requirements = [
            {
                **item,
                "status": "active" if item["id"] == requirement_id else "pending",
                "completion": None,
            }
            for item in self.catalog()
        ]
        bases = {repository["name"]: "c" * 40 for repository in repositories}
        return {
            "status": "success" if advanced else "running",
            "phase": PHASE,
            "step": 14 if advanced else STEP,
            "current_step": 14 if advanced else STEP,
            "current_node": NEXT_NODE if advanced else CURRENT_NODE,
            "workspace": {
                "root": str(self.demo_root.resolve()),
                "final_path": str((self.demo_root / "workspace").resolve()),
            },
            "applicable_repositories": [repository["name"] for repository in repositories],
            "repositories": repositories,
            "requirement_registry": {
                "schema_version": 1,
                "source": self.source(),
                "requirements": requirements,
            },
            "active_requirement": requirement_id,
            "requirement_cycle": {
                "requirement_id": requirement_id,
                "branch": f"req/{requirement_id.lower()}",
                "repositories": {name: {"base_sha": base} for name, base in bases.items()},
                "return_node_after_completion": CURRENT_NODE,
            },
            "blocked": None,
            "error": None,
        }

    def scoped_success(self, state: dict) -> dict:
        requirement_id = state["active_requirement"]
        return result(
            "success",
            "已完成。",
            requirement_id=requirement_id,
            branch=state["requirement_cycle"]["branch"],
            repositories=[
                {
                    "name": repository["name"],
                    "path": "." if repository["name"] == "root" else repository["name"],
                    "base_sha": state["requirement_cycle"]["repositories"][repository["name"]]["base_sha"],
                }
                for repository in state["repositories"]
            ],
        )

    def test_dispatches_step_thirteen_and_prints_its_scoped_result_path(self) -> None:
        run_dir = self.make_run()
        saved = result(
            "success",
            "已完成。",
            requirement_id="BR-001",
            branch="req/br-001",
            repositories=[
                {"name": "root", "path": ".", "base_sha": "c" * 40},
                {"name": "frontend", "path": "frontend", "base_sha": "c" * 40},
            ],
        )
        runner = Mock(return_value=(run_dir, saved))
        stdout = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_thirteen", runner),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(self.cli.main(), 0)
        runner.assert_called_once_with(self.args(run_dir.name))
        self.assertEqual(stdout.getvalue().strip(), str(run_dir / "steps/requirements/BR-001/13.json"))
        self.assertFalse((run_dir / "steps/13.json").exists())

    def test_pre_intent_failure_does_not_create_a_scoped_result(self) -> None:
        run_dir = self.make_run()
        stderr = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_thirteen", side_effect=RuntimeError("secret=hidden")),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertFalse((run_dir / "steps/requirements").exists())
        self.assertIn(str(run_dir / "state.json"), stderr.getvalue())
        self.assertNotIn("secret=hidden", stderr.getvalue())

    def test_failure_scope_requires_matching_active_registry_and_cycle(self) -> None:
        state = self.active_state()
        run_dir = self.make_run(state)
        self.assertEqual(failure_scope(run_dir, state), ("BR-001", "req/br-001"))
        state["requirement_registry"]["requirements"][0]["completion"] = {"invalid": True}
        self.assertIsNone(failure_scope(run_dir, state))
        state["requirement_registry"]["requirements"][0]["completion"] = None
        state["requirement_cycle"]["branch"] = "req/other"
        self.assertIsNone(failure_scope(run_dir, state))

    def test_damaged_active_intent_cannot_write_a_scoped_failure(self) -> None:
        state = self.active_state()
        state["requirement_registry"]["requirements"][0]["status"] = "pending"
        run_dir = self.make_run(state)
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_thirteen", side_effect=RuntimeError("simulated")),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertFalse((run_dir / "steps/requirements").exists())

    def test_intent_failure_preserves_cycle_and_writes_scoped_sanitized_failure(self) -> None:
        state = self.active_state()
        run_dir = self.make_run(state)
        stderr = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_thirteen", side_effect=RuntimeError("secret=hidden")),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads((run_dir / "steps/requirements/BR-001/13.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["error"]["message"], "需求选择未完成。")
        self.assertNotIn("secret=hidden", json.dumps(saved, ensure_ascii=False))
        failed = read_state(run_dir)
        self.assertEqual(failed["active_requirement"], "BR-001")
        self.assertEqual(failed["requirement_cycle"], state["requirement_cycle"])
        self.assertEqual((failed["step"], failed["current_step"], failed["current_node"]), (13, 13, CURRENT_NODE))
        self.assertIn(str(run_dir / "steps/requirements/BR-001/13.json"), stderr.getvalue())

    def test_complete_current_requirement_success_protects_result_and_state(self) -> None:
        state = self.active_state(advanced=True)
        state.update(
            {
                "step": 18,
                "current_step": 18,
                "current_node": "requirement:18_merge",
            }
        )
        state["requirement_cycle"].update(
            {
                "trd_path": "docs/trd/BR-001.md",
                "development_session_id": "development-session",
                "retrospective": {"outcome": "no_change"},
            }
        )
        for repository in state["requirement_cycle"]["repositories"].values():
            repository.update(
                {
                    "tip_sha": repository["base_sha"],
                    "merged": False,
                }
            )
        run_dir = self.make_run(state)
        success = self.scoped_success(state)
        write_requirement_step_result(run_dir, "BR-001", STEP, success)
        before_state = (run_dir / "state.json").read_bytes()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_thirteen", side_effect=OSError("simulated")),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual(json.loads((run_dir / "steps/requirements/BR-001/13.json").read_text(encoding="utf-8")), success)
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)

    def test_later_node_failure_cannot_downgrade_state_without_a_protected_success(self) -> None:
        state = self.active_state(advanced=True)
        state.update(
            {
                "step": 18,
                "current_step": 18,
                "current_node": "requirement:18_merge",
            }
        )
        state["requirement_cycle"]["development_session_id"] = "development-session"
        for repository in state["requirement_cycle"]["repositories"].values():
            repository.update(
                {
                    "tip_sha": repository["base_sha"],
                    "merged": False,
                }
            )
        run_dir = self.make_run(state)
        before_state = (run_dir / "state.json").read_bytes()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_thirteen", side_effect=OSError("simulated")),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)
        self.assertFalse((run_dir / "steps/requirements").exists())

    def test_incomplete_success_is_overwritten_and_historical_requirement_cannot_protect_current_one(self) -> None:
        state = self.active_state("BR-002")
        state["requirement_registry"]["requirements"][0].update(
            {"status": "completed", "completion": {"step": 18}}
        )
        run_dir = self.make_run(state)
        historical = self.active_state("BR-001", advanced=True)
        write_requirement_step_result(run_dir, "BR-001", STEP, self.scoped_success(historical))
        write_requirement_step_result(run_dir, "BR-002", STEP, {"status": "success"})
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_thirteen", side_effect=OSError("simulated")),
        ):
            self.assertEqual(self.cli.main(), 1)
        current = json.loads((run_dir / "steps/requirements/BR-002/13.json").read_text(encoding="utf-8"))
        self.assertEqual(current["status"], "failed")
        self.assertEqual(
            json.loads((run_dir / "steps/requirements/BR-001/13.json").read_text(encoding="utf-8"))["status"],
            "success",
        )

    def test_no_pending_cli_failure_leaves_state_byte_identical(self) -> None:
        state = self.active_state()
        state.update({"active_requirement": None, "requirement_cycle": None, "status": "success"})
        for requirement in state["requirement_registry"]["requirements"]:
            requirement.update({"status": "completed", "completion": {"step": 18}})
        run_dir = self.make_run(state)
        before = (run_dir / "state.json").read_bytes()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_thirteen", side_effect=self.cli.NoPendingRequirements("none")),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual((run_dir / "state.json").read_bytes(), before)
        self.assertFalse((run_dir / "steps/requirements").exists())


if __name__ == "__main__":
    unittest.main()
