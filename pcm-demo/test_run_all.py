from __future__ import annotations

import contextlib
import io
import json
import signal
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch

import run_all
from common.files import write_json


class RunAllTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.runs = self.root / "runs"
        self.runs.mkdir()
        self.patchers = [
            patch.object(run_all, "RUNS_DIR", self.runs),
            patch.object(run_all, "COORDINATION_ROOT", self.runs / ".coordination"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    def args(
        self,
        *,
        resume: str | None = "test-run",
        product_draft: Path | None = None,
        run_id: str | None = None,
        workspace_root: Path | None = None,
        catalog_path: Path | None = None,
    ) -> Namespace:
        return Namespace(
            resume=resume,
            product_draft=product_draft,
            run_id=run_id,
            workspace_root=workspace_root,
            catalog_path=catalog_path,
            product_status=None,
            release_product=None,
        )

    def make_run(self, state: dict[str, object], run_id: str = "test-run") -> Path:
        run_dir = self.runs / run_id
        (run_dir / "steps").mkdir(parents=True)
        write_json(run_dir / "state.json", state)
        return run_dir

    def test_canonical_nodes_route_to_exact_steps(self) -> None:
        for node, expected in run_all.NODE_TO_STEP.items():
            with self.subTest(node=node):
                run_dir = self.make_run(
                    {
                        "status": "running",
                        "step": expected,
                        "current_step": expected,
                        "current_node": node,
                    },
                    f"run-{expected}",
                )
                state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
                self.assertEqual(run_all.step_for_state(run_dir, state), expected)

    def test_canonical_position_mismatch_is_rejected(self) -> None:
        run_dir = self.make_run(
            {
                "status": "failed",
                "step": 14,
                "current_step": 15,
                "current_node": "requirement:14_trd_design",
            }
        )
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            run_all.step_for_state(run_dir, state)

    def test_legacy_success_and_failure_positions_are_supported(self) -> None:
        for current_step, status, expected in (
            (0, "success", 1),
            (1, "success", 2),
            (2, "success", 3),
            (0, "failed", 0),
            (1, "blocked", 1),
            (2, "running", 2),
            (3, "failed", 3),
        ):
            with self.subTest(current_step=current_step, status=status):
                run_dir = self.make_run(
                    {"status": status, "current_step": current_step},
                    f"legacy-{current_step}-{status}",
                )
                if status == "success":
                    write_json(
                        run_dir / "steps" / f"{current_step:02d}.json",
                        {"status": "success"},
                    )
                state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
                self.assertEqual(run_all.step_for_state(run_dir, state), expected)

    def test_phase_one_completion_requires_nonempty_completed_registry(self) -> None:
        base = {
            "status": "success",
            "phase": "phase_1_requirement_development",
            "step": 13,
            "current_step": 13,
            "current_node": "phase_1:select_requirement",
            "active_requirement": None,
            "requirement_cycle": None,
        }
        completed = {
            **base,
            "requirement_registry": {
                "schema_version": 1,
                "source": {"root_main_sha": "legacy"},
                "requirements": [
                    {
                        "id": "BR-001",
                        "title": "需求一",
                        "order": 1,
                        "depends_on": [],
                        "status": "completed",
                        "completion": {"step": 18},
                    }
                ],
            },
        }
        self.assertTrue(run_all.phase_one_completed(completed))
        self.assertFalse(
            run_all.phase_one_completed(
                {**base, "requirement_registry": {"requirements": []}}
            )
        )
        self.assertFalse(
            run_all.phase_one_completed(
                {
                    **base,
                    "requirement_registry": {
                        "schema_version": 1,
                        "source": {},
                        "requirements": [
                            {
                                "id": "BR-001",
                                "status": "completed",
                                "completion": {"step": 18},
                            }
                        ],
                    },
                }
            )
        )
        self.assertFalse(
            run_all.phase_one_completed(
                {
                    **base,
                    "requirement_registry": {
                        "schema_version": 1,
                        "source": {},
                        "requirements": [
                            {
                                "id": "BR-001",
                                "title": "需求一",
                                "order": 1,
                                "depends_on": [],
                                "status": "pending",
                                "completion": None,
                            }
                        ],
                    },
                }
            )
        )

    def test_build_command_only_forwards_step_specific_overrides(self) -> None:
        workspace_root = self.root / "workspace root"
        catalog_path = self.root / "catalog.json"
        draft = self.root / "draft.md"
        args = self.args(
            resume=None,
            run_id="test-run",
            product_draft=draft,
            workspace_root=workspace_root,
            catalog_path=catalog_path,
        )
        step_zero = run_all.build_step_command(0, "test-run", args, None)
        step_one = run_all.build_step_command(1, "test-run", args, {})
        step_three = run_all.build_step_command(3, "test-run", args, {})
        self.assertIn("--product-draft", step_zero)
        self.assertNotIn("--workspace-root", step_zero)
        self.assertIn("--workspace-root", step_one)
        self.assertNotIn("--catalog-path", step_one)
        self.assertIn("--catalog-path", step_three)

    def test_full_fresh_sequence_stops_after_first_completed_requirement(self) -> None:
        draft = self.root / "draft.md"
        draft.write_text("产品初稿", encoding="utf-8")
        args = self.args(
            resume=None,
            product_draft=draft,
            run_id="fresh-run",
        )
        run_dir = self.runs / "fresh-run"
        calls: list[int] = []
        nodes = {step: node for node, step in run_all.NODE_TO_STEP.items()}

        def fake_run_child(command: list[str], _pass_fds: tuple[int, ...] = ()) -> int:
            step = int(command[command.index("--step") + 1])
            calls.append(step)
            (run_dir / "steps").mkdir(parents=True, exist_ok=True)
            if step < 12:
                next_step = step + 1
                state: dict[str, object] = {
                    "run_id": "fresh-run",
                    "status": "success",
                    "phase": "project_initialization",
                    "step": next_step,
                    "current_step": next_step,
                    "current_node": nodes[next_step],
                }
            elif step == 12:
                state = {
                    "run_id": "fresh-run",
                    "status": "success",
                    "phase": "phase_1_requirement_development",
                    "step": 13,
                    "current_step": 13,
                    "current_node": nodes[13],
                    "active_requirement": None,
                    "requirement_cycle": None,
                    "requirement_registry": {
                        "schema_version": 1,
                        "source": {},
                        "requirements": [
                            {
                                "id": "BR-001",
                                "title": "需求一",
                                "order": 1,
                                "depends_on": [],
                                "status": "pending",
                                "completion": None,
                            }
                        ],
                    },
                }
            elif step < 18:
                next_step = step + 1
                state = {
                    "run_id": "fresh-run",
                    "status": "success",
                    "phase": "phase_1_requirement_development",
                    "step": next_step,
                    "current_step": next_step,
                    "current_node": nodes[next_step],
                    "active_requirement": "BR-001",
                    "requirement_cycle": {
                        "requirement_id": "BR-001",
                        "branch": "req/br-001",
                        "repositories": {},
                        "return_node_after_completion": "phase_1:select_requirement",
                    },
                    "requirement_registry": {
                        "schema_version": 1,
                        "source": {},
                        "requirements": [
                            {
                                "id": "BR-001",
                                "title": "需求一",
                                "order": 1,
                                "depends_on": [],
                                "status": "active",
                                "completion": None,
                            }
                        ],
                    },
                }
            else:
                state = {
                    "run_id": "fresh-run",
                    "status": "success",
                    "phase": "phase_1_requirement_development",
                    "step": 13,
                    "current_step": 13,
                    "current_node": nodes[13],
                    "active_requirement": None,
                    "requirement_cycle": None,
                    "requirement_registry": {
                        "schema_version": 1,
                        "source": {},
                        "requirements": [
                            {
                                "id": "BR-001",
                                "title": "需求一",
                                "order": 1,
                                "depends_on": [],
                                "status": "completed",
                                "completion": {"step": 18},
                            }
                        ],
                    },
                }
            write_json(run_dir / "state.json", state)
            return 0

        with patch.object(run_all, "run_child", side_effect=fake_run_child):
            self.assertEqual(run_all.orchestrate(args), 0)

        self.assertEqual(calls, list(range(19)))

    def test_failed_step_stops_without_outer_retry(self) -> None:
        run_dir = self.make_run(
            {
                "run_id": "different-state-id",
                "status": "failed",
                "phase": "phase_1_requirement_development",
                "step": 15,
                "current_step": 15,
                "current_node": "requirement:15_development",
            }
        )
        calls: list[list[str]] = []
        stderr = io.StringIO()

        def failed(command: list[str], _pass_fds: tuple[int, ...] = ()) -> int:
            calls.append(command)
            return 1

        with (
            patch.object(run_all, "run_child", side_effect=failed),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(run_all.orchestrate(self.args()), 1)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index("--run-id") + 1], run_dir.name)
        self.assertIn("--resume test-run", stderr.getvalue())

    def test_completed_resume_does_not_start_step_thirteen(self) -> None:
        run_dir = self.make_run(
            {
                "status": "success",
                "phase": "phase_1_requirement_development",
                "step": 13,
                "current_step": 13,
                "current_node": "phase_1:select_requirement",
                "active_requirement": None,
                "requirement_cycle": None,
                "requirement_registry": {
                    "schema_version": 1,
                    "source": {},
                    "requirements": [
                        {
                            "id": "BR-001",
                            "title": "需求一",
                            "order": 1,
                            "depends_on": [],
                            "status": "completed",
                            "completion": {"step": 18},
                        }
                    ],
                },
            }
        )
        with patch.object(run_all, "run_child") as child:
            self.assertEqual(run_all.orchestrate(self.args()), 0)
        child.assert_not_called()
        self.assertTrue((run_dir / "state.json").is_file())

    def test_damaged_state_stops_with_recovery_command(self) -> None:
        run_dir = self.runs / "test-run"
        run_dir.mkdir()
        (run_dir / "state.json").write_text("{broken", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(run_all.orchestrate(self.args()), 1)
        self.assertIn("运行状态不可读取", stderr.getvalue())
        self.assertIn("--resume test-run", stderr.getvalue())

    def test_same_run_conflict_is_reported_without_waiting(self) -> None:
        first = run_all.acquire_execution_locks(
            run_all.COORDINATION_ROOT, "test-run", 2
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "运行锁已被占用"):
                run_all.acquire_execution_locks(
                    run_all.COORDINATION_ROOT, "test-run", 2
                )
        finally:
            first.close()

    def test_product_status_and_release_commands(self) -> None:
        product = self.root / "products" / "alpha"
        key, canonical = run_all.product_key(product)
        with run_all.acquire_product_lock(
            run_all.COORDINATION_ROOT, "run-a", key, canonical
        ):
            record = run_all.claim_product(
                run_all.COORDINATION_ROOT, "run-a", key, canonical
            )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(run_all._product_status(product), 0)
        status = json.loads(stdout.getvalue())
        self.assertEqual(status["ports"], record["ports"])
        self.assertFalse(status["product_lock_held"])

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(run_all._release_product(product), 0)
        self.assertIn("产品端口已释放", stdout.getvalue())
        self.assertEqual(
            run_all.get_product(run_all.COORDINATION_ROOT, key)["lifecycle"],
            "released",
        )

    def test_negative_signal_return_code_is_normalized(self) -> None:
        child = Mock(pid=1234)
        child.wait.return_value = -signal.SIGTERM
        with patch.object(run_all.subprocess, "Popen", return_value=child):
            self.assertEqual(run_all.run_child(["python", "step.py"]), 143)

    def test_cli_requires_exactly_one_fresh_or_resume_entry(self) -> None:
        with self.assertRaises(SystemExit):
            run_all.parse_args([])
        with self.assertRaises(SystemExit):
            run_all.parse_args(["--product-draft", "draft.md", "--resume", "run"])
        with self.assertRaises(SystemExit):
            run_all.parse_args(["--resume", "run", "--run-id", "other"])


if __name__ == "__main__":
    unittest.main()
