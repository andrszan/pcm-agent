from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import timing
from common.files import write_json


def execution(**changes):
    return {
        "step": 15,
        "name": "实现与验证",
        "requirement_id": "BR-001",
        "started_at": "2026-09-05T09:00:00+00:00",
        "finished_at": "2026-09-05T09:10:00+00:00",
        "elapsed_seconds": 600.0,
        "attempt_count": 1,
        "status": "success",
        "applicable": True,
        "reused_success": False,
        "history_missing": False,
        **changes,
    }


class TimingSummaryTests(unittest.TestCase):
    def test_runtime_and_span_have_different_resume_semantics(self):
        first = execution(status="failed")
        second = execution(
            started_at="2026-09-05T10:00:00+00:00",
            finished_at="2026-09-05T10:20:00+00:00",
            elapsed_seconds=1200,
        )
        summary, = timing.summarize([first, second])
        self.assertEqual(summary["elapsed_seconds"], 1800)
        self.assertEqual(summary["span_seconds"], 4800)
        self.assertEqual(summary["started_at"], first["started_at"])
        self.assertEqual(summary["completed_at"], second["finished_at"])
        self.assertFalse(summary["incomplete"])

    def test_first_completion_is_frozen_after_reuse_or_mistaken_rerun(self):
        summary, = timing.summarize([
            execution(),
            execution(reused_success=True, elapsed_seconds=1),
            execution(status="failed", elapsed_seconds=30),
        ])
        self.assertEqual(summary["elapsed_seconds"], 600)
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["reused_count"], 1)

    def test_requirements_and_steps_are_separate(self):
        entries = [execution(), execution(requirement_id="BR-002"), execution(step=14)]
        self.assertEqual(len(timing.summarize(entries)), 3)

    def test_unclosed_execution_is_not_measured_until_resume(self):
        summary, = timing.summarize([
            execution(status=None, finished_at=None, elapsed_seconds=None),
            execution(elapsed_seconds=300),
        ])
        self.assertEqual(summary["elapsed_seconds"], 300)
        self.assertTrue(summary["incomplete"])
        self.assertIsNone(summary["span_seconds"])

    def test_interruption_with_known_duration_is_partial(self):
        summary, = timing.summarize([execution(status=None), execution()])
        self.assertEqual(summary["elapsed_seconds"], 1200)
        self.assertTrue(summary["incomplete"])

    def test_historical_success_reuse_does_not_invent_original_duration(self):
        summary, = timing.summarize([execution(reused_success=True, history_missing=True)])
        self.assertIsNone(summary["elapsed_seconds"])
        self.assertIsNone(summary["started_at"])
        self.assertIsNone(summary["completed_at"])
        self.assertIsNone(summary["span_seconds"])
        self.assertTrue(summary["incomplete"])

    def test_unmeasured_success_after_recorded_failure_remains_partial(self):
        summary, = timing.summarize([
            execution(status="failed"),
            execution(reused_success=True),
        ])
        self.assertEqual(summary["elapsed_seconds"], 600)
        self.assertTrue(summary["incomplete"])
        self.assertIsNone(summary["completed_at"])

    def test_negative_wall_clock_span_does_not_change_monotonic_duration(self):
        summary, = timing.summarize([execution(finished_at="2026-09-05T08:00:00+00:00")])
        self.assertEqual(summary["elapsed_seconds"], 600)
        self.assertIsNone(summary["span_seconds"])

    def test_duration_is_readable_and_unknown_is_not_zero(self):
        self.assertEqual(timing.format_duration(None), "未记录")
        self.assertEqual(timing.format_duration(0.045), "0.04 秒")
        self.assertEqual(timing.format_duration(75.5), "1 分 15 秒")
        self.assertEqual(timing.format_duration(3661), "1 小时 01 分 01 秒")


class TimingPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.directory.name)
        (self.run_dir / "steps").mkdir()
        write_json(self.run_dir / "state.json", {"status": "success", "current_step": 15, "active_requirement": "BR-001"})
        self.stderr = io.StringIO()
        self.redirect = contextlib.redirect_stderr(self.stderr)
        self.redirect.__enter__()

    def tearDown(self):
        self.redirect.__exit__(None, None, None)
        self.directory.cleanup()

    def test_start_is_durable_before_execution_and_finish_uses_monotonic(self):
        with patch.object(timing.time, "monotonic", side_effect=[100.0, 145.25]), patch.object(
            timing, "utc_now", side_effect=["2026-09-05T09:00:00+00:00", "2026-09-05T08:00:00+00:00"]
        ):
            clock = timing.StepTiming()
            clock.begin_attempt(15)
            clock.bind_run(self.run_dir, existing=True)
            clock.announce()
            pending = json.loads((self.run_dir / "timings.json").read_text())["executions"][0]
            self.assertIsNone(pending["finished_at"])
            self.assertIsNone(pending["elapsed_seconds"])
            self.assertEqual(pending["requirement_id"], "BR-001")
            clock.observe_result(self.run_dir, {"name": "实现与验证", "status": "success", "applicable": True})
            clock.finish(returned=True)
        entry, = json.loads((self.run_dir / "timings.json").read_text())["executions"]
        self.assertEqual(entry["elapsed_seconds"], 45.25)
        self.assertIn("开始", self.stderr.getvalue())
        self.assertIn("累计运行：45.25 秒", self.stderr.getvalue())

    def test_started_before_run_creation_is_bound_without_changing_state(self):
        missing = self.run_dir / "new-run"
        clock = timing.StepTiming()
        clock.begin_attempt(0)
        clock.bind_run(missing, existing=True)
        self.assertFalse(missing.exists())
        missing.mkdir()
        clock.observe_result(missing, {"status": "success", "applicable": False})
        clock.finish(returned=True)
        entry, = json.loads((missing / "timings.json").read_text())["executions"]
        self.assertFalse(entry["history_missing"])
        self.assertFalse(entry["applicable"])
        self.assertFalse((missing / "state.json").exists())

    def test_existing_failed_run_without_timer_is_marked_partial(self):
        write_json(self.run_dir / "state.json", {"status": "failed", "current_step": 15, "active_requirement": "BR-001"})
        clock = timing.StepTiming()
        clock.begin_attempt(15)
        clock.bind_run(self.run_dir, existing=True)
        clock.observe_result(self.run_dir, {"status": "success", "applicable": True})
        clock.finish(returned=True)
        summary, = timing.summarize(json.loads((self.run_dir / "timings.json").read_text())["executions"])
        self.assertTrue(summary["incomplete"])
        self.assertIsNone(summary["span_seconds"])

    def test_corrupt_or_incomplete_sidecar_is_preserved_and_warned(self):
        for content in ("{broken", json.dumps({"schema_version": 1, "executions": [{"step": 15}]})):
            with self.subTest(content=content):
                path = self.run_dir / "timings.json"
                path.write_text(content)
                clock = timing.StepTiming()
                clock.begin_attempt(15)
                clock.bind_run(self.run_dir, existing=True)
                clock.observe_result(self.run_dir, {"status": "success"})
                clock.finish(returned=True)
                self.assertEqual(path.read_text(), content)
        self.assertIn("业务执行不受影响", self.stderr.getvalue())

    def test_symlink_sidecar_does_not_overwrite_external_target(self):
        target = self.run_dir / "external.json"
        target.write_text("do not change")
        (self.run_dir / "timings.json").symlink_to(target)
        clock = timing.StepTiming()
        clock.begin_attempt(15)
        clock.bind_run(self.run_dir, existing=True)
        clock.observe_result(self.run_dir, {"status": "success"})
        clock.finish(returned=True)
        self.assertEqual(target.read_text(), "do not change")
        self.assertTrue((self.run_dir / "timings.json").is_symlink())

    def test_summary_lists_historical_results_as_unrecorded(self):
        write_json(self.run_dir / "steps" / "06.json", {"step": 6, "name": "项目化", "status": "success", "applicable": True})
        timing.print_timing_summary(self.run_dir)
        self.assertIn("第 6 步 项目化", self.stderr.getvalue())
        self.assertIn("累计 未记录", self.stderr.getvalue())
        self.assertFalse((self.run_dir / "timings.json").exists())

    def test_summary_is_read_only_and_marks_skip_and_reuse(self):
        path = self.run_dir / "timings.json"
        write_json(path, {"schema_version": 1, "executions": [execution(applicable=False), execution(reused_success=True)]})
        before = path.read_bytes()
        timing.print_timing_summary(self.run_dir)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("不适用跳过", self.stderr.getvalue())
        self.assertIn("成功复用 1 次", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
