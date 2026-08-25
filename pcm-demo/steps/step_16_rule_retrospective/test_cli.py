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

from common.state import read_state, write_requirement_step_result, write_state
from steps.step_16_rule_retrospective.step import (
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    STEP,
    RuleRetrospectiveBlocked,
    result,
)


class RuleRetrospectiveCLITests(unittest.TestCase):
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
        self, *, advanced: bool = False, complete_success: bool = False
    ) -> tuple[Path, dict]:
        run_dir = self.demo_root / "runs/test-run"
        workspace_root = self.demo_root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)
        (run_dir / "steps").mkdir(parents=True)
        base_sha = "a" * 40
        key = "rule_retrospective_BR-001"
        cycle = {
            "requirement_id": "BR-001",
            "branch": "req/br-001",
            "repositories": {"root": {"base_sha": base_sha}},
            "trd_path": "docs/trd/BR-001.md",
            "development_session_id": "development-session-1",
        }
        state = {
            "status": "success" if advanced else "running",
            "phase": PHASE,
            "step": STEP + 1 if advanced else STEP,
            "current_step": STEP + 1 if advanced else STEP,
            "current_node": NEXT_NODE if advanced else CURRENT_NODE,
            "workspace": {
                "root": str(workspace_root.resolve()),
                "final_path": str(workspace.resolve()),
            },
            "applicable_repositories": ["root"],
            "repositories": [
                {
                    "name": "root",
                    "path": str(workspace.resolve()),
                    "branch": "main",
                    "worktree_clean": True,
                }
            ],
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
            "claude_sessions": {"development_BR-001": "development-session-1"},
            "blocked": None,
            "error": None,
        }
        if advanced or complete_success:
            state["claude_sessions"][key] = "development-session-1"
            state[key] = {
                "baseline": {
                    "version": 1,
                    "repositories": [
                        {
                            "name": "root",
                            "branch": "req/br-001",
                            "head": base_sha,
                            "main": base_sha,
                            "target": base_sha,
                            "refs": [
                                {
                                    "name": "refs/heads/main",
                                    "sha": base_sha,
                                    "symref": None,
                                },
                                {
                                    "name": "refs/heads/req/br-001",
                                    "sha": base_sha,
                                    "symref": None,
                                },
                            ],
                            "pseudo_refs": [
                                {
                                    "name": name,
                                    "exists": False,
                                    "content_sha256": None,
                                }
                                for name in (
                                    "ORIG_HEAD",
                                    "FETCH_HEAD",
                                    "MERGE_HEAD",
                                    "AUTO_MERGE",
                                    "CHERRY_PICK_HEAD",
                                    "REVERT_HEAD",
                                    "REBASE_HEAD",
                                    "BISECT_HEAD",
                                )
                            ],
                            "index_clean": True,
                            "index_sha256": "b" * 64,
                            "entries": [],
                        }
                    ],
                }
            }
        write_requirement_step_result(
            run_dir,
            "BR-001",
            15,
            {
                "step": 15,
                "name": "实现与验证",
                "status": "success",
                "summary": "已完成。",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "requirement_id": "BR-001",
                "trd_path": "docs/trd/BR-001.md",
                "development_session_id": "development-session-1",
            },
        )
        if complete_success:
            write_requirement_step_result(run_dir, "BR-001", STEP, self.success_result())
        write_state(run_dir, state)
        return run_dir, state

    @staticmethod
    def success_result() -> dict:
        return result(
            "success",
            "已完成。",
            requirement_id="BR-001",
            development_session_id="development-session-1",
        )

    def test_dispatches_step_sixteen_and_prints_scoped_path(self) -> None:
        run_dir, _ = self.make_run()
        runner = AsyncMock(return_value=(run_dir, self.success_result()))
        stdout = io.StringIO()
        args = self.args(run_dir.name)
        with (
            patch.object(self.cli, "parse_args", return_value=args),
            patch.object(self.cli, "run_step_sixteen", runner),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(self.cli.main(), 0)
        runner.assert_awaited_once_with(args)
        self.assertEqual(
            stdout.getvalue().strip(), str(run_dir / "steps/requirements/BR-001/16.json")
        )

    def test_blocked_exception_writes_scoped_blocked_result(self) -> None:
        run_dir, _ = self.make_run()
        blocked = RuleRetrospectiveBlocked(
            "缺少外部授权",
            ["外部授权"],
            requirement_id="BR-001",
            development_session_id="development-session-1",
        )
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_sixteen", side_effect=blocked),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads(
            (run_dir / "steps/requirements/BR-001/16.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["status"], "blocked")
        self.assertEqual(saved["development_session_id"], "development-session-1")
        self.assertEqual(read_state(run_dir)["current_node"], CURRENT_NODE)

    def test_failed_exception_is_sanitized_and_scoped(self) -> None:
        run_dir, _ = self.make_run()
        stderr = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(
                self.cli,
                "run_step_sixteen",
                side_effect=RuntimeError("secret=hidden"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads(
            (run_dir / "steps/requirements/BR-001/16.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["development_session_id"], "development-session-1")
        self.assertNotIn("secret=hidden", json.dumps(saved, ensure_ascii=False))
        self.assertNotIn("secret=hidden", stderr.getvalue())

    def test_complete_scoped_success_protects_state_and_result(self) -> None:
        run_dir, _ = self.make_run(advanced=True, complete_success=True)
        result_path = run_dir / "steps/requirements/BR-001/16.json"
        before_result = result_path.read_bytes()
        before_state = (run_dir / "state.json").read_bytes()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_sixteen", side_effect=OSError("simulated")),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual(result_path.read_bytes(), before_result)
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)


if __name__ == "__main__":
    unittest.main()
