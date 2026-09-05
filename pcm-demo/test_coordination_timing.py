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

import run_all
import run_step
from common import timing as timing_module
from common.coordination import (
    acquire_execution_locks,
    coordination_root,
    inherited_lock_argument,
    lock_status,
    run_lock_path,
)
from common.files import write_json
from test_step_timing import claude_result, make_result


class CoordinationTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(directory).resolve()
        self.coordination = coordination_root(self.root)
        self.run_dir = self.root / "runs" / "run"
        self.args = Namespace(step=2, run_id="run")
        for patcher in (
            patch.object(run_step, "DEMO_ROOT", self.root),
            patch.object(run_all, "RUNS_DIR", self.root / "runs"),
            patch.object(run_all, "COORDINATION_ROOT", self.coordination),
            patch.object(run_step, "load_settings", return_value=Namespace(pcm_max_concurrent_projects=2)),
            patch.object(run_all, "load_settings", return_value=Namespace(pcm_max_concurrent_projects=2)),
            patch.object(run_step, "parse_args", return_value=self.args),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.stack.enter_context(patcher)

    def prepare_run(self) -> None:
        (self.run_dir / "steps").mkdir(parents=True)
        write_json(self.run_dir / "state.json", {
            "run_id": "run", "status": "success", "current_step": 2,
            "step": 2, "current_node": "project:02_intake",
            "phase": "project_initialization",
        })

    def held(self) -> bool:
        return lock_status(run_lock_path(self.coordination, self.args.run_id))[0]

    def test_retries_and_all_timing_writes_hold_the_run_lock(self) -> None:
        self.prepare_run()
        attempts = []
        writes = []
        delays = []

        async def run_attempt(args):
            attempts.append(args.run_id)

            async def agent_call():
                if len(attempts) < 3:
                    raise run_step.AgentExecutionFailure(
                        "Agent SDK 执行失败", "logs/agent.json", retry_requested=True,
                    )
                return claude_result("完成", self.run_dir)

            await timing_module.run_timed_agent(agent_call)
            return self.run_dir, make_result(2, "success")

        def save(path, data):
            writes.append(self.held())
            write_json(path, data)

        def backoff(delay):
            delays.append(delay)
            self.assertTrue(self.held())
            with self.assertRaisesRegex(RuntimeError, "运行锁已被占用"):
                acquire_execution_locks(self.coordination, "run", 2)

        with (
            patch.object(run_step, "run_step_two", side_effect=run_attempt),
            patch.object(run_step.time, "sleep", side_effect=backoff),
            patch.object(timing_module, "write_json", side_effect=save),
        ):
            self.assertEqual(run_step.retrying_main(), 0, sys.stderr.getvalue())
        self.assertEqual(attempts, ["run"] * 3)
        self.assertEqual(delays, [10, 30])
        self.assertGreaterEqual(len(writes), 12)
        self.assertTrue(all(writes))
        self.assertFalse(self.held())
        record = json.loads((self.run_dir / "timings.json").read_bytes())["steps"][0]
        self.assertEqual(len(record["agent_executions"]), 3)
        self.assertEqual(record["status"], "success")

    def test_generated_run_id_and_locks_stay_fixed_across_attempts(self) -> None:
        self.args.run_id = None
        attempts = []

        def execute(args, locks, timing):
            attempts.append((args.run_id, locks, timing))
            self.assertTrue(self.held())
            return run_step._RETRY_REQUESTED_EXIT_CODE if len(attempts) < 3 else 0

        with (
            patch.object(run_step, "new_run_id", return_value="generated") as generate,
            patch.object(run_step, "parse_args", return_value=self.args) as parse,
            patch.object(run_step, "_execute", side_effect=execute),
            patch.object(run_step.time, "sleep"),
        ):
            self.assertEqual(run_step.retrying_main(), 0, sys.stderr.getvalue())
        parse.assert_called_once_with()
        generate.assert_called_once_with()
        self.assertEqual([entry[0] for entry in attempts], ["generated"] * 3)
        self.assertTrue(all(entry[1] is attempts[0][1] for entry in attempts))
        self.assertTrue(all(entry[2] is attempts[0][2] for entry in attempts))
        self.assertFalse(self.held())

    def test_cancellation_finishes_timing_before_releasing_locks(self) -> None:
        self.prepare_run()
        for error in (KeyboardInterrupt(), SystemExit(143)):
            with self.subTest(error=type(error).__name__):
                finishes = []
                original_finish = timing_module.StepTiming.finish

                def finish(timing, *, returned):
                    finishes.append((returned, self.held()))
                    original_finish(timing, returned=returned)

                with (
                    patch.object(run_step, "run_step_two", side_effect=error),
                    patch.object(timing_module.StepTiming, "finish", finish),
                    patch.object(run_step.time, "sleep") as sleeper,
                    self.assertRaises(type(error)) as raised,
                ):
                    run_step.retrying_main()
                self.assertIs(raised.exception, error)
                self.assertEqual(finishes, [(False, True)])
                sleeper.assert_not_called()
                self.assertFalse(self.held())

    def test_lock_conflict_has_no_timing_or_step_side_effects(self) -> None:
        self.prepare_run()
        path = self.run_dir / "timings.json"
        write_json(path, {"schema_version": 2, "steps": []})
        before = path.read_bytes()
        with (
            acquire_execution_locks(self.coordination, "run", 2),
            patch.object(run_step, "_execute") as execute,
            patch.object(timing_module.StepTiming, "begin_attempt") as begin,
            patch.object(run_step.time, "sleep") as sleeper,
        ):
            self.assertEqual(run_step.retrying_main(), 2)
        execute.assert_not_called()
        begin.assert_not_called()
        sleeper.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_partial_lock_preparation_releases_acquired_locks(self) -> None:
        self.prepare_run()
        write_json(self.run_dir / "state.json", {
            "coordination": {"product_path": str(self.root / "product")},
        })
        acquired = []

        def acquire(*args):
            locks = acquire_execution_locks(*args)
            acquired.append(locks)
            return locks

        with (
            patch.object(run_step, "acquire_execution_locks", side_effect=acquire),
            patch.object(run_step, "_ensure_product_claim", side_effect=RuntimeError("产品协调失败")),
        ):
            try:
                self.assertEqual(run_step.retrying_main(), 2)
                self.assertFalse(self.held())
                with acquire_execution_locks(self.coordination, "run", 1):
                    pass
            finally:
                for locks in acquired:
                    locks.close()
        self.assertFalse((self.run_dir / "timings.json").exists())

    def test_run_all_summaries_hold_lock_and_skip_contended_runs(self) -> None:
        self.prepare_run()
        for resume, exit_code in (("run", 0), ("run", 1), (None, 2)):
            with self.subTest(resume=resume, exit_code=exit_code):
                summaries = []
                args = Namespace(resume=resume, run_id="run")
                with (
                    patch.object(run_all, "_run_steps", return_value=exit_code),
                    patch.object(run_all, "print_timing_summary", side_effect=lambda path: summaries.append((path, self.held()))),
                ):
                    self.assertEqual(run_all.orchestrate(args), exit_code)
                self.assertEqual(summaries, [(self.run_dir, True)])
                self.assertFalse(self.held())
        with (
            acquire_execution_locks(self.coordination, "run", 2),
            patch.object(run_all, "print_timing_summary") as summary,
        ):
            self.assertEqual(run_all.orchestrate(Namespace(resume="run", run_id=None)), 2)
        summary.assert_not_called()

    def test_real_child_records_timing_under_inherited_locks(self) -> None:
        self.args.step = 0
        draft = self.root / "draft.md"
        draft.write_text(
            "## A. 产品身份与文档边界\n产品。\n"
            "## C. 用户与使用场景\n用户。\n"
            "## D. 核心价值与业务闭环\n闭环。\n"
            "## E. 产品范围\n范围。\n"
            "## P. 产品验收\n验收。\n",
            encoding="utf-8",
        )
        code = '''
import sys
from pathlib import Path
import run_step
from common import timing
from common.coordination import coordination_root, lock_status, run_lock_path
run_step.DEMO_ROOT = Path(sys.argv[1])
sys.argv = ['run_step.py', *sys.argv[2:]]
original = timing.write_json
checks = []
def save(path, data):
    checks.append(lock_status(run_lock_path(coordination_root(run_step.DEMO_ROOT), 'run'))[0])
    original(path, data)
timing.write_json = save
result = run_step.retrying_main()
assert checks and all(checks), checks
raise SystemExit(result)
'''
        with acquire_execution_locks(self.coordination, "run", 2) as locks:
            completed = subprocess.run(
                [sys.executable, "-c", code, str(self.root), "--step", "0",
                 "--run-id", "run", "--product-draft", str(draft),
                 "--coordination-locks", inherited_lock_argument(locks)],
                cwd=Path(run_step.__file__).parent,
                pass_fds=locks.file_descriptors(), capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(self.held())
            record = json.loads((self.run_dir / "timings.json").read_bytes())["steps"][0]
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["agent_elapsed_seconds"], 0.0)
            self.assertIsNotNone(record["finished_at"])
            self.assertIn("结束", completed.stderr)
        self.assertFalse(self.held())


if __name__ == "__main__":
    unittest.main()
