from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.state import write_requirement_step_result, write_state
from steps.step_18_merge.step import CURRENT_NODE, NEXT_NODE, PHASE, STEP, result


def command(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


def commit_all(repository: Path, message: str) -> str:
    command("add", "-A", cwd=repository)
    command(
        "-c",
        "user.name=PCM Test",
        "-c",
        "user.email=pcm@example.invalid",
        "commit",
        "-m",
        message,
        cwd=repository,
    )
    return command("rev-parse", "HEAD", cwd=repository)


class RequirementMergeCLITests(unittest.TestCase):
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
    def args(run_id: str) -> Namespace:
        return Namespace(
            step=STEP,
            product_draft=None,
            workspace_root=None,
            catalog_path=None,
            run_id=run_id,
        )

    def make_run(
        self, *, final_git: bool = False, completed_state: bool = False
    ) -> tuple[Path, dict, dict]:
        run_dir = self.demo_root / "runs/test-run"
        workspace_root = self.demo_root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)
        (run_dir / "steps/requirements/BR-001").mkdir(parents=True)
        command("init", "-b", "main", cwd=workspace)
        (workspace / "base.txt").write_text("base\n", encoding="utf-8")
        base = commit_all(workspace, "base")
        command("switch", "-c", "req/br-001", cwd=workspace)
        (workspace / "change.txt").write_text("change\n", encoding="utf-8")
        tip = commit_all(workspace, "feat: requirement")
        if final_git:
            command("switch", "main", cwd=workspace)
            command("merge", "--ff-only", "req/br-001", cwd=workspace)
            command("branch", "-d", "req/br-001", cwd=workspace)

        state = {
            "status": "success",
            "phase": PHASE,
            "step": 13 if completed_state else STEP,
            "current_step": 13 if completed_state else STEP,
            "current_node": NEXT_NODE if completed_state else CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "applicable_repositories": ["root"],
            "repositories": [
                {
                    "name": "root",
                    "path": str(workspace),
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
                        "status": "completed" if completed_state else "active",
                        "completion": {"step": STEP} if completed_state else None,
                    }
                ],
            },
            "active_requirement": None if completed_state else "BR-001",
            "requirement_cycle": None
            if completed_state
            else {
                "requirement_id": "BR-001",
                "branch": "req/br-001",
                "repositories": {
                    "root": {
                        "base_sha": base,
                        "tip_sha": tip,
                        "merged": final_git,
                    }
                },
                "return_node_after_completion": NEXT_NODE,
            },
            "blocked": None,
            "error": None,
        }
        commit_result = {
            "step": 17,
            "name": "统一提交需求变更",
            "status": "success",
            "summary": "已提交。",
            "applicable": True,
            "outputs": [],
            "blocked": None,
            "error": None,
            "requirement_id": "BR-001",
            "branch": "req/br-001",
            "repositories": [
                {
                    "name": "root",
                    "path": ".",
                    "base_sha": base,
                    "tip_sha": tip,
                }
            ],
        }
        merge_result = result(
            "success",
            "已完成。",
            requirement_id="BR-001",
            branch="req/br-001",
            repositories=commit_result["repositories"],
        )
        write_requirement_step_result(run_dir, "BR-001", 17, commit_result)
        write_state(run_dir, state)
        return run_dir, state, merge_result

    def test_dispatches_step_eighteen_and_prints_scoped_path(self) -> None:
        run_dir, _state, success = self.make_run()
        stdout = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(self.cli, "run_step_eighteen", return_value=(run_dir, success)) as runner,
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(self.cli.main(), 0)
        runner.assert_called_once()
        self.assertEqual(
            stdout.getvalue().strip(),
            str(run_dir / "steps/requirements/BR-001/18.json"),
        )

    def test_real_cli_executes_merge_and_prints_scoped_path(self) -> None:
        run_dir, _state, _success = self.make_run()
        stdout = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(self.cli.main(), 0)
        result_path = run_dir / "steps/requirements/BR-001/18.json"
        self.assertEqual(Path(stdout.getvalue().strip()).resolve(), result_path.resolve())
        saved = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "success")
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual((state["step"], state["current_step"], state["current_node"]), (13, 13, NEXT_NODE))
        self.assertEqual(
            state["requirement_registry"]["requirements"][0]["completion"],
            {"step": STEP},
        )
        workspace = Path(state["workspace"]["final_path"])
        self.assertEqual(command("branch", "--show-current", cwd=workspace), "main")
        self.assertEqual(
            subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", "refs/heads/req/br-001"],
                cwd=workspace,
            ).returncode,
            1,
        )

    def test_failed_exception_is_sanitized_and_scoped(self) -> None:
        run_dir, _state, _success = self.make_run()
        stderr = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(
                self.cli,
                "run_step_eighteen",
                side_effect=RuntimeError("secret=hidden"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.cli.main(), 1)
        saved = json.loads(
            (run_dir / "steps/requirements/BR-001/18.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["error"]["message"], "secret=[REDACTED]")
        self.assertEqual(saved["error"]["diagnostic_path"], "logs/step-18-error.json")
        self.assertNotIn("secret=hidden", json.dumps(saved, ensure_ascii=False))
        self.assertIn("secret=[REDACTED]", stderr.getvalue())
        self.assertIn("logs/step-18-error.json", stderr.getvalue())
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual((state["step"], state["current_step"], state["current_node"]), (18, 18, CURRENT_NODE))

    def test_completed_state_is_not_downgraded_by_misuse(self) -> None:
        run_dir, _state, _success = self.make_run(final_git=True, completed_state=True)
        before_state = (run_dir / "state.json").read_bytes()
        stderr = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(
                self.cli,
                "run_step_eighteen",
                side_effect=RuntimeError("out of order"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)
        self.assertFalse((run_dir / "steps/requirements/BR-001/18.json").exists())

    def test_complete_scoped_success_protects_state_and_result(self) -> None:
        run_dir, _state, success = self.make_run(final_git=True)
        write_requirement_step_result(run_dir, "BR-001", STEP, success)
        result_path = run_dir / "steps/requirements/BR-001/18.json"
        before_result = result_path.read_bytes()
        before_state = (run_dir / "state.json").read_bytes()
        with (
            patch.object(self.cli, "parse_args", return_value=self.args(run_dir.name)),
            patch.object(
                self.cli,
                "run_step_eighteen",
                side_effect=OSError("simulated"),
            ),
        ):
            self.assertEqual(self.cli.main(), 1)
        self.assertEqual(result_path.read_bytes(), before_result)
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)


if __name__ == "__main__":
    unittest.main()
