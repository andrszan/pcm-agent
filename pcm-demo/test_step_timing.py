from __future__ import annotations

import contextlib
import io
import json
import select
import signal
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_ROOT))

import run_all
import run_step
from common import timing as timing_module


RECORD_FIELDS = {
    "step",
    "name",
    "requirement_id",
    "started_at",
    "finished_at",
    "elapsed_seconds",
    "attempt_count",
    "status",
    "applicable",
    "reused_success",
    "history_missing",
}


def make_result(
    step: int,
    status: str,
    *,
    requirement_id: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "step": step,
        "name": timing_module.STEP_NAMES[step],
        "status": status,
        "summary": f"第 {step} 步 {status}",
        "outputs": [],
        "applicable": True,
        "blocked": {"reason": "缺少不可替代的外部资源"} if status == "blocked" else None,
        "error": {"message": "任务执行失败"} if status == "failed" else None,
    }
    if requirement_id is not None:
        result["requirement_id"] = requirement_id
    return result


def make_record(
    step: int,
    status: str,
    elapsed_seconds: float,
    *,
    requirement_id: str | None = None,
    started_at: str = "2026-01-01T00:00:00+00:00",
    finished_at: str = "2026-01-01T00:00:10+00:00",
) -> dict[str, object]:
    return {
        "step": step,
        "name": timing_module.STEP_NAMES[step],
        "requirement_id": requirement_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "attempt_count": 1,
        "status": status,
        "applicable": True,
        "reused_success": False,
        "history_missing": False,
    }


class StepTimingIntegrationTests(unittest.TestCase):
    def test_automatic_retries_share_one_record_and_include_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            success = make_result(0, "success")
            retry_error = run_step.AgentExecutionFailure(
                "Agent SDK 执行失败",
                "logs/agent.json",
                retry_requested=True,
            )
            clock = [0.0]
            delays: list[int] = []

            def advance(delay: int) -> None:
                delays.append(delay)
                clock[0] += delay

            stderr = io.StringIO()
            with (
                patch.object(run_step, "parse_args", return_value=Namespace(step=0, run_id=None)),
                patch.object(
                    run_step,
                    "run_step_zero",
                    side_effect=[retry_error, retry_error, (run_dir, success)],
                ),
                patch.object(run_step.time, "sleep", side_effect=advance),
                patch.object(timing_module.time, "monotonic", side_effect=lambda: clock[0]),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_step.retrying_main(), 0)

            timings = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))
            self.assertEqual(timings["schema_version"], 1)
            self.assertEqual(len(timings["executions"]), 1)
            record = timings["executions"][0]
            self.assertEqual(record["attempt_count"], 3)
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["elapsed_seconds"], 40.0)
            self.assertEqual(delays, [10, 30])
            self.assertEqual(stderr.getvalue().count("开始  "), 1)
            self.assertEqual(stderr.getvalue().count("结束  "), 1)

    def test_new_invocation_after_failure_or_blocked_excludes_manual_wait(self) -> None:
        for first_status in ("failed", "blocked"):
            with self.subTest(first_status=first_status), tempfile.TemporaryDirectory() as directory:
                run_dir = Path(directory) / "run"
                run_dir.mkdir()
                results = [
                    (run_dir, make_result(0, first_status)),
                    (run_dir, make_result(0, "success")),
                ]
                monotonic_values = iter([0.0, 4.0, 104.0, 110.0])
                utc_values = iter(
                    [
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:04+00:00",
                        "2026-01-01T00:01:44+00:00",
                        "2026-01-01T00:01:50+00:00",
                    ]
                )
                with (
                    patch.object(run_step, "parse_args", return_value=Namespace(step=0, run_id=None)),
                    patch.object(run_step, "run_step_zero", side_effect=results),
                    patch.object(timing_module.time, "monotonic", side_effect=monotonic_values),
                    patch.object(timing_module, "utc_now", side_effect=utc_values),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(run_step.retrying_main(), 1)
                    self.assertEqual(run_step.retrying_main(), 0)

                executions = json.loads(
                    (run_dir / "timings.json").read_text(encoding="utf-8")
                )["executions"]
                self.assertEqual([item["elapsed_seconds"] for item in executions], [4.0, 6.0])
                summary = timing_module.summarize(executions)[0]
                self.assertEqual(summary["status"], "success")
                self.assertEqual(summary["elapsed_seconds"], 10.0)
                self.assertEqual(summary["span_seconds"], 110.0)
                self.assertFalse(summary["incomplete"])

    def test_main_dispatch_step_thirteen_captures_selected_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "selection-run"
            (run_dir / "steps").mkdir(parents=True)
            state = {
                "status": "running",
                "phase": "phase_1_requirement_development",
                "step": 13,
                "current_step": 13,
                "current_node": "phase_1:select_requirement",
                "active_requirement": None,
            }
            (run_dir / "state.json").write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8"
            )

            def select_requirement(_args: Namespace) -> tuple[Path, dict[str, object]]:
                state["active_requirement"] = "BR-013"
                (run_dir / "state.json").write_text(
                    json.dumps(state, ensure_ascii=False), encoding="utf-8"
                )
                return run_dir, make_result(13, "success")

            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=13, run_id="selection-run"),
                ),
                patch.object(run_step, "run_step_thirteen", side_effect=select_requirement),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_step.retrying_main(), 0)

            record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))[
                "executions"
            ][0]
            self.assertEqual(record["step"], 13)
            self.assertEqual(record["requirement_id"], "BR-013")

    def test_main_dispatch_step_eighteen_retains_requirement_after_active_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "merge-run"
            (run_dir / "steps").mkdir(parents=True)
            state = {
                "status": "running",
                "phase": "phase_1_requirement_development",
                "step": 18,
                "current_step": 18,
                "current_node": "requirement:18_merge",
                "active_requirement": "BR-018",
            }
            (run_dir / "state.json").write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8"
            )

            def merge_requirement(_args: Namespace) -> tuple[Path, dict[str, object]]:
                state["active_requirement"] = None
                (run_dir / "state.json").write_text(
                    json.dumps(state, ensure_ascii=False), encoding="utf-8"
                )
                return run_dir, make_result(18, "success")

            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=18, run_id="merge-run"),
                ),
                patch.object(run_step, "run_step_eighteen", side_effect=merge_requirement),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_step.retrying_main(), 0)

            record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))[
                "executions"
            ][0]
            self.assertEqual(record["step"], 18)
            self.assertEqual(record["requirement_id"], "BR-018")

    def test_reused_success_does_not_replace_original_total(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            (run_dir / "steps").mkdir(parents=True)
            result = make_result(0, "success")
            (run_dir / "state.json").write_text(
                json.dumps({"status": "success", "current_step": 1}), encoding="utf-8"
            )
            (run_dir / "steps" / "00.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            original = make_record(0, "success", 25.0)
            (run_dir / "timings.json").write_text(
                json.dumps({"schema_version": 1, "executions": [original]}),
                encoding="utf-8",
            )

            current = timing_module.StepTiming()
            with (
                patch.object(timing_module.time, "monotonic", side_effect=[100.0, 103.0]),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                current.begin_attempt(0)
                current.bind_run(run_dir, existing=True)
                current.observe_result(run_dir, result)
                current.finish(returned=True)

            executions = json.loads(
                (run_dir / "timings.json").read_text(encoding="utf-8")
            )["executions"]
            self.assertEqual(len(executions), 2)
            self.assertEqual(executions[0]["elapsed_seconds"], 25.0)
            self.assertTrue(executions[1]["reused_success"])
            summary = timing_module.summarize(executions)[0]
            self.assertEqual(summary["elapsed_seconds"], 25.0)
            self.assertEqual(summary["reused_count"], 1)

    def test_actual_registry_reuse_ignores_changed_summary(self) -> None:
        from functools import partial
        from common.files import sha256, write_json
        from steps.step_12_initialize_requirement_registry import step as registry_step
        from steps.step_12_initialize_requirement_registry import test_step as fixtures

        for recorded in (False, True):
            with self.subTest(recorded=recorded), tempfile.TemporaryDirectory() as directory:
                fixture = fixtures.RequirementRegistryTests()
                run_dir, workspace, state = fixture.make_run(Path(directory))
                source = {
                    "path": registry_step.BACKLOG_PATH.as_posix(),
                    "sha256": sha256(workspace / registry_step.BACKLOG_PATH),
                }
                registry_step._advance_success(run_dir, state, source, fixture.requirements())
                original_state = (run_dir / "state.json").read_bytes()
                original_result = (run_dir / "steps" / "12.json").read_bytes()
                if recorded:
                    write_json(run_dir / "timings.json", {
                        "schema_version": 1,
                        "executions": [make_record(12, "success", 42)],
                    })
                stderr = io.StringIO()
                with (
                    patch.object(run_step, "run_dir_for", return_value=run_dir),
                    patch.object(run_step, "parse_args", return_value=Namespace(step=12, run_id="test-run")),
                    patch.object(run_step, "run_requirement_registry", partial(
                        registry_step.run,
                        config_loader=lambda: self.fail("成功复用不得加载模型配置"),
                    )),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(stderr),
                ):
                    self.assertEqual(run_step.retrying_main(), 0)
                entries = json.loads((run_dir / "timings.json").read_text())["executions"]
                self.assertTrue(entries[-1]["reused_success"])
                summary, = timing_module.summarize(entries)
                self.assertEqual(summary["elapsed_seconds"], 42 if recorded else None)
                self.assertEqual(summary["reused_count"], 1)
                self.assertIn("成功复用", stderr.getvalue())
                self.assertEqual((run_dir / "state.json").read_bytes(), original_state)
                self.assertEqual((run_dir / "steps" / "12.json").read_bytes(), original_result)

    def test_overflowing_timing_total_does_not_override_business_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            (run_dir / "state.json").write_text(json.dumps({"status": "success", "current_step": 0}))
            (run_dir / "timings.json").write_text(json.dumps({
                "schema_version": 1,
                "executions": [make_record(0, "failed", 1e308), make_record(0, "success", 1e308)],
            }))
            stderr = io.StringIO()
            with (
                patch.object(run_step, "run_dir_for", return_value=run_dir),
                patch.object(run_step, "parse_args", return_value=Namespace(step=0, run_id="test-run")),
                patch.object(run_step, "run_step_zero", return_value=(run_dir, make_result(0, "success"))),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_step.retrying_main(), 0)
            with (
                patch.object(run_all, "run_dir_for", return_value=run_dir),
                patch.object(run_all, "_run_steps", return_value=0),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_all.orchestrate(Namespace(resume="test-run", run_id=None)), 0)
            self.assertIn("警告", stderr.getvalue())
            self.assertIn("退出码不受影响", stderr.getvalue())

    def test_run_all_refused_fresh_run_prints_read_only_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            path = run_dir / "timings.json"
            path.write_text(json.dumps({"schema_version": 1, "executions": [make_record(0, "success", 2)]}))
            before = path.read_bytes()
            stderr = io.StringIO()
            with (
                patch.object(run_all, "run_dir_for", return_value=run_dir),
                patch.object(run_all, "run_child") as child,
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_all.orchestrate(Namespace(resume=None, run_id="existing")), 2)
            child.assert_not_called()
            self.assertIn("拒绝覆盖", stderr.getvalue())
            self.assertIn("步骤耗时汇总", stderr.getvalue())
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_cli_arguments_do_not_create_timing_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "invalid-run"
            run_dir.mkdir(parents=True)
            stderr = io.StringIO()
            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    sys,
                    "argv",
                    ["run_step.py", "--step", "not-a-number", "--run-id", "invalid-run"],
                ),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                run_step.retrying_main()

            self.assertEqual(raised.exception.code, 2)
            self.assertIn("invalid int value", stderr.getvalue())
            self.assertFalse((run_dir / "timings.json").exists())

    def test_damaged_timing_file_does_not_change_success_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "damaged-run"
            run_dir.mkdir(parents=True)
            (run_dir / "timings.json").write_text("{broken", encoding="utf-8")
            stderr = io.StringIO()
            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=0, run_id="damaged-run"),
                ),
                patch.object(
                    run_step,
                    "run_step_zero",
                    return_value=(run_dir, make_result(0, "success")),
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_step.retrying_main(), 0)

            self.assertIn("计时记录不可读写", stderr.getvalue())
            self.assertEqual((run_dir / "timings.json").read_text(encoding="utf-8"), "{broken")

    def test_timing_write_failure_does_not_change_business_failure_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            stderr = io.StringIO()
            with (
                patch.object(run_step, "parse_args", return_value=Namespace(step=0, run_id=None)),
                patch.object(
                    run_step,
                    "run_step_zero",
                    return_value=(run_dir, make_result(0, "failed")),
                ),
                patch.object(timing_module, "write_json", side_effect=OSError("只读文件系统")),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_step.retrying_main(), 1)

            self.assertIn("计时记录不可读写", stderr.getvalue())
            self.assertFalse((run_dir / "timings.json").exists())

    def test_run_all_prints_summary_without_changing_stop_exit_code(self) -> None:
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as directory:
                run_dir = Path(directory) / "run"
                args = Namespace(resume=None, run_id="run")
                with (
                    patch.object(run_all, "run_dir_for", return_value=run_dir),
                    patch.object(run_all, "_run_steps", return_value=exit_code),
                    patch.object(run_all, "print_timing_summary") as print_summary,
                ):
                    self.assertEqual(run_all.orchestrate(args), exit_code)

                print_summary.assert_called_once_with(run_dir)

    def test_sigterm_leaves_open_record_and_next_timer_does_not_invent_old_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            child_code = (
                "import signal, sys\n"
                "from pathlib import Path\n"
                "from common.timing import StepTiming\n"
                "run_dir = Path(sys.argv[1])\n"
                "run_dir.mkdir()\n"
                "timing = StepTiming()\n"
                "timing.begin_attempt(0)\n"
                "timing.bind_run(run_dir)\n"
                "timing.announce()\n"
                "print('READY', flush=True)\n"
                "signal.pause()\n"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", child_code, str(run_dir)],
                cwd=DEMO_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self.assertIsNotNone(process.stdout)
                self.assertTrue(select.select([process.stdout], [], [], 10)[0], "子进程未就绪")
                self.assertEqual(process.stdout.readline().strip(), "READY")
                started = json.loads(
                    (run_dir / "timings.json").read_text(encoding="utf-8")
                )["executions"][0]
                self.assertIsNone(started["finished_at"])
                self.assertIsNone(started["elapsed_seconds"])
                self.assertIsNone(started["status"])

                process.send_signal(signal.SIGTERM)
                process.communicate(timeout=10)
                self.assertEqual(process.returncode, -signal.SIGTERM)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

            after_signal = json.loads(
                (run_dir / "timings.json").read_text(encoding="utf-8")
            )["executions"]
            self.assertEqual(len(after_signal), 1)
            self.assertIsNone(after_signal[0]["finished_at"])
            self.assertIsNone(after_signal[0]["elapsed_seconds"])

            resumed = timing_module.StepTiming()
            with (
                patch.object(timing_module.time, "monotonic", side_effect=[20.0, 23.0]),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                resumed.begin_attempt(0)
                resumed.bind_run(run_dir)
                resumed.observe_result(run_dir, make_result(0, "success"))
                resumed.finish(returned=True)

            executions = json.loads(
                (run_dir / "timings.json").read_text(encoding="utf-8")
            )["executions"]
            self.assertEqual(len(executions), 2)
            self.assertIsNone(executions[0]["elapsed_seconds"])
            self.assertEqual(executions[1]["elapsed_seconds"], 3.0)
            summary = timing_module.summarize(executions)[0]
            self.assertEqual(summary["elapsed_seconds"], 3.0)
            self.assertTrue(summary["incomplete"])

    def test_real_python_subprocess_step_zero_preserves_business_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = root / "draft.md"
            draft.write_text(
                "## A. 产品身份与文档边界\n产品。\n"
                "## C. 用户与使用场景\n用户。\n"
                "## D. 核心价值与业务闭环\n闭环。\n"
                "## E. 产品范围\n范围。\n"
                "## P. 产品验收\n验收。\n",
                encoding="utf-8",
            )
            child_code = (
                "import sys\n"
                "from pathlib import Path\n"
                "import run_step\n"
                "root, cli = Path(sys.argv[1]), sys.argv[2:]\n"
                "run_step.DEMO_ROOT = root\n"
                "sys.argv = ['run_step.py', *cli]\n"
                "raise SystemExit(run_step.retrying_main())\n"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(root),
                    "--step",
                    "0",
                    "--product-draft",
                    str(draft),
                    "--run-id",
                    "subprocess-run",
                ],
                cwd=DEMO_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            run_dir = root / "runs" / "subprocess-run"
            result_path = run_dir / "steps" / "00.json"
            self.assertEqual(completed.stdout.strip(), str(result_path.resolve()))
            self.assertIn("开始  项目 · 第 0 步", completed.stderr)
            self.assertIn("结束  项目 · 第 0 步", completed.stderr)
            self.assertIn("本次耗时", completed.stderr)

            timings = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))
            self.assertEqual(set(timings), {"schema_version", "executions"})
            self.assertEqual(timings["schema_version"], 1)
            self.assertEqual(len(timings["executions"]), 1)
            record = timings["executions"][0]
            self.assertEqual(set(record), RECORD_FIELDS)
            self.assertEqual(record["step"], 0)
            self.assertEqual(record["attempt_count"], 1)
            self.assertEqual(record["status"], "success")
            self.assertGreaterEqual(record["elapsed_seconds"], 0)

            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertNotIn("timing", json.dumps(state, ensure_ascii=False).lower())
            self.assertNotIn("timing", json.dumps(result, ensure_ascii=False).lower())


if __name__ == "__main__":
    unittest.main()
