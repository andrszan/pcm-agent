from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from common import files, timing
from common.files import write_json


def agent_result(**changes):
    return SimpleNamespace(
        **{
            "result_subtype": "success", "is_error": False, "has_errors": False,
            "exception": None, "exception_type": None, "api_error_status": None,
            "terminal_reason": "completed", **changes,
        }
    )


def legacy_execution(**changes):
    return {
        "step": 15, "name": "实现与验证", "requirement_id": "BR-001",
        "started_at": "2026-09-05T06:00:00+00:00",
        "finished_at": "2026-09-05T06:10:00+00:00",
        "elapsed_seconds": 600, "attempt_count": 1, "status": "success",
        "applicable": True, "reused_success": False, "history_missing": False,
        **changes,
    }


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.directory.name)
        (self.run_dir / "steps").mkdir()
        self.state = {"status": "success", "current_step": 15, "active_requirement": "BR-001"}
        write_json(self.run_dir / "state.json", self.state)
        self.stderr = io.StringIO()
        self.redirect = contextlib.redirect_stderr(self.stderr)
        self.redirect.__enter__()

    def tearDown(self):
        self.redirect.__exit__(None, None, None)
        self.directory.cleanup()

    def start(self, step=15, existing=True):
        clock = timing.StepTiming()
        clock.begin_attempt(step)
        clock.bind_run(self.run_dir, existing=existing)
        return clock

    def data(self):
        return json.loads((self.run_dir / "timings.json").read_text())

    def complete(self, clock, status="success"):
        clock.observe_result(self.run_dir, {"status": status, "step": clock.step})
        clock.finish(returned=True)

    def test_beijing_offset_and_conversion_preserve_instant(self):
        value = "2026-09-05T06:51:19.141561+00:00"
        converted = timing._beijing(value)
        self.assertEqual(converted, "2026-09-05T14:51:19.141561+08:00")
        self.assertEqual(datetime.fromisoformat(value), datetime.fromisoformat(converted))
        self.assertEqual(datetime.fromisoformat(timing.beijing_now()).utcoffset(), timedelta(hours=8))
        with self.assertRaises(ValueError):
            timing._beijing("2026-09-05T06:00:00")

    def test_new_step_is_durable_with_two_explicit_metrics(self):
        clock = self.start()
        entry, = self.data()["steps"]
        self.assertEqual(self.data()["schema_version"], 2)
        self.assertEqual(entry["requirement_id"], "BR-001")
        self.assertEqual(entry["agent_elapsed_seconds"], 0)
        self.assertIsNone(entry["wall_elapsed_seconds"])
        self.assertIsNone(entry["finished_at"])
        self.assertEqual(entry["agent_executions"], [])
        self.assertTrue(entry["started_at"].endswith("+08:00"))
        self.assertFalse({"applicable", "reused_success", "history_missing", "attempt_count", "elapsed_seconds"} & entry.keys())
        self.assertNotIn("note", entry)
        self.complete(clock)
        self.assertIsNotNone(self.data()["steps"][0]["wall_elapsed_seconds"])

    def test_agent_calls_exclude_outside_wait_and_preserve_arguments(self):
        now = [0.0]
        calls = []
        clock = self.start()

        async def runner(prompt, **kwargs):
            calls.append((prompt, kwargs))
            now[0] += 10
            return agent_result()

        async def work():
            await timing.run_timed_agent(runner, "原始指令", resume_session_id="session-1")
            now[0] += 80
            await timing.run_timed_agent(runner, "继续", resume_session_id="session-1")

        with clock.activate(), patch.object(timing.time, "monotonic", side_effect=lambda: now[0]):
            asyncio.run(work())
        self.complete(clock)
        entry, = self.data()["steps"]
        self.assertEqual(entry["agent_elapsed_seconds"], 20)
        self.assertEqual(len(entry["agent_executions"]), 2)
        self.assertEqual([call["elapsed_seconds"] for call in entry["agent_executions"]], [10, 10])
        self.assertTrue(all(call["end_reason"] == "returned" and call["interrupted_at"] is None for call in entry["agent_executions"]))
        self.assertEqual(calls, [("原始指令", {"resume_session_id": "session-1"}), ("继续", {"resume_session_id": "session-1"})])

    def test_agent_start_is_persisted_before_runner_executes(self):
        clock = self.start()

        async def runner():
            call, = self.data()["steps"][0]["agent_executions"]
            self.assertIsNone(call["finished_at"])
            self.assertIsNone(call["elapsed_seconds"])
            self.assertIsNone(call["interrupted_at"])
            return agent_result()

        with clock.activate():
            asyncio.run(timing.run_timed_agent(runner))
        self.complete(clock)

    def test_sdk_end_reasons_and_interruption_times(self):
        cases = [
            ({"api_error_status": 500}, "api_error"),
            ({"terminal_reason": "api_error"}, "api_error"),
            ({"result_subtype": "error_max_turns"}, "turn_limit"),
            ({"result_subtype": "error_max_budget_usd"}, "budget_limit"),
            ({"has_errors": True}, "error"),
            ({"exception_type": "RuntimeError"}, "error"),
            ({"terminal_reason": "aborted_streaming"}, "error"),
        ]
        clock = self.start()
        with clock.activate():
            for fields, expected in cases:
                async def runner():
                    return agent_result(**fields)
                asyncio.run(timing.run_timed_agent(runner))
                call = self.data()["steps"][0]["agent_executions"][-1]
                self.assertEqual(call["end_reason"], expected)
                self.assertEqual(call["interrupted_at"], call["finished_at"])
        self.complete(clock, "failed")
        self.assertIsNone(self.data()["steps"][0]["finished_at"])

    def test_exception_is_measured_and_reraised_without_storing_secret(self):
        clock = self.start()
        failure = RuntimeError("private-value-not-for-timing")

        async def runner():
            raise failure

        with clock.activate(), self.assertRaises(RuntimeError) as caught:
            asyncio.run(timing.run_timed_agent(runner))
        self.assertIs(caught.exception, failure)
        call, = self.data()["steps"][0]["agent_executions"]
        self.assertEqual(call["end_reason"], "exception")
        self.assertIsNotNone(call["interrupted_at"])
        self.assertNotIn("private-value-not-for-timing", (self.run_dir / "timings.json").read_text())

    def test_cancelled_error_is_measured_and_propagated(self):
        clock = self.start()

        async def runner():
            raise asyncio.CancelledError

        with clock.activate(), self.assertRaises(asyncio.CancelledError):
            asyncio.run(timing.run_timed_agent(runner))
        clock.finish(returned=False)
        call, = self.data()["steps"][0]["agent_executions"]
        self.assertEqual(call["end_reason"], "cancelled")
        self.assertIsNotNone(call["elapsed_seconds"])
        self.assertIsNotNone(call["interrupted_at"])

    def test_resumed_step_accumulates_agent_time_and_includes_gap_only_in_wall(self):
        utc = iter(["2026-09-05T14:00:00+08:00", "2026-09-05T15:00:00+08:00", "2026-09-05T15:20:00+08:00"])
        with patch.object(timing, "beijing_now", side_effect=lambda: next(utc)):
            first = self.start()
            self.complete(first, "blocked")
            second = self.start()
            self.complete(second)
        entry, = self.data()["steps"]
        self.assertEqual(entry["started_at"], "2026-09-05T14:00:00+08:00")
        self.assertEqual(entry["finished_at"], "2026-09-05T15:20:00+08:00")
        self.assertEqual(entry["wall_elapsed_seconds"], 4800)
        self.assertEqual(entry["agent_elapsed_seconds"], 0)

    def test_success_reuse_keeps_original_times_and_no_new_agent_call(self):
        first = self.start()
        self.complete(first)
        before = self.data()["steps"][0]
        second = self.start()
        second.observe_result(self.run_dir, {"status": "success", "step": 15, "summary": "changed"})
        second.finish(returned=True)
        self.assertEqual(self.data()["steps"][0], before)
        self.assertIn("成功复用", self.stderr.getvalue())

    def test_unclosed_old_agent_interval_is_unknown_not_retimed(self):
        first = self.start()
        measurement = first.begin_agent()
        before = self.data()["steps"][0]["agent_executions"][0]
        second = self.start()
        self.complete(second)
        entry, = self.data()["steps"]
        call, = entry["agent_executions"]
        self.assertEqual(call["started_at"], before["started_at"])
        self.assertIsNone(call["elapsed_seconds"])
        self.assertIsNone(call["interrupted_at"])
        self.assertIsNone(call["finished_at"])
        self.assertEqual(call["end_reason"], "unknown")
        self.assertIn("未闭合", entry["note"])
        self.assertIsNotNone(entry["wall_elapsed_seconds"])
        self.assertIsNotNone(measurement)

    def test_legacy_projection_is_read_only_and_never_converts_command_duration_to_agent(self):
        path = self.run_dir / "timings.json"
        write_json(path, {"schema_version": 1, "executions": [legacy_execution()]})
        before = path.read_bytes()
        data, legacy = timing._read_timings(self.run_dir)
        entry, = data["steps"]
        self.assertEqual(legacy, before)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.run_dir / "timings.v1.json").exists())
        self.assertEqual(entry["started_at"], "2026-09-05T14:00:00+08:00")
        self.assertEqual(entry["finished_at"], "2026-09-05T14:10:00+08:00")
        self.assertEqual(entry["wall_elapsed_seconds"], 600)
        self.assertIsNone(entry["agent_elapsed_seconds"])
        self.assertEqual(entry["agent_executions"], [])
        self.assertIn("旧版", entry["note"])
        self.assertFalse({"applicable", "reused_success", "history_missing"} & entry.keys())

    def test_upgrade_archives_original_bytes_only_when_new_writer_binds(self):
        path = self.run_dir / "timings.json"
        write_json(path, {"schema_version": 1, "executions": [legacy_execution()]})
        before = path.read_bytes()
        clock = self.start(16)
        self.complete(clock)
        self.assertEqual((self.run_dir / "timings.v1.json").read_bytes(), before)
        self.assertEqual(self.data()["schema_version"], 2)
        self.assertEqual(len(self.data()["steps"]), 2)
        self.assertIsNone(self.data()["steps"][0]["agent_elapsed_seconds"])

    def test_conflicting_legacy_archive_does_not_overwrite_either_file(self):
        path = self.run_dir / "timings.json"
        write_json(path, {"schema_version": 1, "executions": [legacy_execution()]})
        before = path.read_bytes()
        archive = self.run_dir / "timings.v1.json"
        archive.write_bytes(b"keep this archive")
        clock = self.start(16)
        self.complete(clock)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(archive.read_bytes(), b"keep this archive")
        self.assertIn("警告", self.stderr.getvalue())

    def test_legacy_resume_with_missing_agent_end_can_still_have_known_wall_span(self):
        entries = [
            legacy_execution(status=None, finished_at=None, elapsed_seconds=None),
            legacy_execution(started_at="2026-09-05T07:00:00+00:00", finished_at="2026-09-05T07:10:00+00:00"),
        ]
        write_json(self.run_dir / "timings.json", {"schema_version": 1, "executions": entries})
        data, _ = timing._read_timings(self.run_dir)
        entry, = data["steps"]
        self.assertEqual(entry["wall_elapsed_seconds"], 4200)
        self.assertIsNone(entry["agent_elapsed_seconds"])

    def test_previously_successful_step_without_timing_does_not_invent_completion(self):
        target = self.run_dir / "steps" / "requirements" / "BR-001" / "15.json"
        target.parent.mkdir(parents=True)
        write_json(target, {"step": 15, "status": "success", "requirement_id": "BR-001"})
        clock = self.start()
        self.complete(clock)
        entry, = self.data()["steps"]
        self.assertIsNone(entry["started_at"])
        self.assertIsNone(entry["finished_at"])
        self.assertIsNone(entry["agent_elapsed_seconds"])
        self.assertIsNone(entry["wall_elapsed_seconds"])
        self.assertIn("首次完成时间未记录", entry["note"])

    def test_old_running_state_without_timing_preserves_unknown_initial_start(self):
        write_json(self.run_dir / "state.json", {**self.state, "status": "running"})
        clock = self.start()
        self.complete(clock)
        entry, = self.data()["steps"]
        self.assertIsNone(entry["started_at"])
        self.assertIsNone(entry["wall_elapsed_seconds"])
        self.assertIsNotNone(entry["finished_at"])

    def test_unbound_wrapper_does_not_create_records_or_change_result(self):
        returned = agent_result()
        async def runner():
            return returned
        self.assertIs(asyncio.run(timing.run_timed_agent(runner)), returned)
        self.assertFalse((self.run_dir / "timings.json").exists())

    def test_bad_data_symlink_and_write_error_preserve_business_flow(self):
        path = self.run_dir / "timings.json"
        path.write_text("{broken")
        clock = self.start()
        self.complete(clock)
        self.assertEqual(path.read_text(), "{broken")
        path.unlink()
        target = self.run_dir / "outside.json"
        path.symlink_to(target)
        clock = self.start()
        self.complete(clock)
        self.assertTrue(path.is_symlink())
        self.assertFalse(target.exists())
        path.unlink()
        with patch.object(timing, "write_json", side_effect=OSError("写入失败")):
            clock = self.start()
            self.complete(clock)
        self.assertFalse(path.exists())

    def test_summary_keeps_historical_data_read_only_and_shows_both_metrics(self):
        path = self.run_dir / "timings.json"
        write_json(path, {"schema_version": 1, "executions": [legacy_execution()]})
        before = path.read_bytes()
        timing.print_timing_summary(self.run_dir)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("Claude Code 累计 未记录", self.stderr.getvalue())
        self.assertIn("总历时 10 分", self.stderr.getvalue())
        self.assertFalse((self.run_dir / "timings.v1.json").exists())

    def test_agent_duration_excludes_timing_writes_and_result_classification(self):
        now = [0.0]
        with patch.object(timing.time, "monotonic", side_effect=lambda: now[0]):
            clock = self.start()
            save = clock._save
            classify = timing._agent_end_reason

            def slow_save():
                now[0] += 2
                save()

            def slow_classify(value):
                now[0] += 7
                return classify(value)

            async def runner():
                now[0] += 10
                return agent_result()

            with clock.activate(), patch.object(clock, "_save", side_effect=slow_save), patch.object(
                timing, "_agent_end_reason", side_effect=slow_classify
            ):
                asyncio.run(timing.run_timed_agent(runner))
        call, = self.data()["steps"][0]["agent_executions"]
        self.assertEqual(call["elapsed_seconds"], 10)
        self.assertEqual(self.data()["steps"][0]["agent_elapsed_seconds"], 10)

    def test_cancellation_after_observed_success_preserves_first_finish(self):
        clock = self.start()
        clock.observe_result(self.run_dir, {"step": 15, "status": "success"})
        before = self.data()["steps"][0]
        self.assertIsNotNone(before["finished_at"])
        clock.finish(returned=False)
        self.assertEqual(self.data()["steps"][0], before)
        resumed = self.start()
        self.complete(resumed)
        self.assertEqual(self.data()["steps"][0], before)

    def test_failed_archive_write_never_publishes_partial_final_file(self):
        path = self.run_dir / "timings.json"
        write_json(path, {"schema_version": 1, "executions": [legacy_execution()]})
        before = path.read_bytes()
        fdopen = timing.os.fdopen
        for failure in (OSError("写入中断"), KeyboardInterrupt()):
            with self.subTest(error=type(failure).__name__):
                @contextlib.contextmanager
                def partial_writer(*args, **kwargs):
                    with fdopen(*args, **kwargs) as output:
                        def write(raw):
                            output.write(raw[:3])
                            output.flush()
                            raise failure
                        yield SimpleNamespace(write=write)

                with patch.object(timing.os, "fdopen", side_effect=partial_writer):
                    if isinstance(failure, KeyboardInterrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            self.start(16)
                    else:
                        clock = self.start(16)
                        self.complete(clock)
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse((self.run_dir / "timings.v1.json").exists())
                self.assertEqual(list(self.run_dir.glob(".timings.v1.*.tmp")), [])
        recovered = self.start(16)
        self.complete(recovered)
        self.assertEqual((self.run_dir / "timings.v1.json").read_bytes(), before)
        self.assertEqual(self.data()["schema_version"], 2)

    def test_new_selection_after_unassigned_failure_has_its_own_known_start(self):
        write_json(self.run_dir / "state.json", {
            "status": "success", "current_step": 13, "active_requirement": None,
        })
        times = iter([
            "2026-09-05T14:00:00+08:00", "2026-09-05T15:00:00+08:00",
            "2026-09-05T15:01:00+08:00",
        ])
        with patch.object(timing, "beijing_now", side_effect=lambda: next(times)):
            first = self.start(13)
            self.complete(first, "failed")
            previous = self.data()["steps"][0]
            write_json(self.run_dir / "state.json", {
                "status": "failed", "current_step": 13, "active_requirement": None,
            })
            second = self.start(13)
            second.observe_result(self.run_dir, {
                "step": 13, "status": "success", "requirement_id": "BR-002",
            })
            second.finish(returned=True)
        old, selected = self.data()["steps"]
        self.assertEqual(old, previous)
        self.assertIsNone(old["requirement_id"])
        self.assertEqual(selected["requirement_id"], "BR-002")
        self.assertEqual(selected["started_at"], "2026-09-05T15:00:00+08:00")
        self.assertEqual(selected["wall_elapsed_seconds"], 60)
        self.assertNotIn("note", selected)

    def test_archive_cleanup_failure_does_not_replace_cancellation(self):
        path = self.run_dir / "timings.json"
        write_json(path, {"schema_version": 1, "executions": [legacy_execution()]})
        before = path.read_bytes()
        fdopen = timing.os.fdopen
        for failure in (KeyboardInterrupt(), SystemExit(143)):
            with self.subTest(error=type(failure).__name__):
                @contextlib.contextmanager
                def interrupted_writer(*args, **kwargs):
                    with fdopen(*args, **kwargs) as output:
                        def write(raw):
                            output.write(raw[:3])
                            output.flush()
                            raise failure
                        yield SimpleNamespace(write=write)

                with (
                    patch.object(timing.os, "fdopen", side_effect=interrupted_writer),
                    patch.object(Path, "unlink", side_effect=OSError("清理失败")),
                    self.assertRaises(type(failure)) as caught,
                ):
                    self.start(16)
                self.assertIs(caught.exception, failure)
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse((self.run_dir / "timings.v1.json").exists())
        recovered = self.start(16)
        self.complete(recovered)
        self.assertEqual((self.run_dir / "timings.v1.json").read_bytes(), before)

    def test_atomic_json_cleanup_failure_does_not_replace_cancellation(self):
        path = self.run_dir / "original.json"
        path.write_bytes(b"original")
        for failure in (KeyboardInterrupt(), SystemExit(143), ValueError("原始错误")):
            with (
                self.subTest(error=type(failure).__name__),
                patch.object(files.json, "dump", side_effect=failure),
                patch.object(Path, "unlink", side_effect=OSError("清理失败")),
                self.assertRaises(type(failure)) as caught,
            ):
                files.write_json(path, {"value": "new"})
            self.assertIs(caught.exception, failure)
            self.assertEqual(path.read_bytes(), b"original")

    def test_duration_format_and_overflow_rejection(self):
        self.assertEqual(timing.format_duration(None), "未记录")
        self.assertEqual(timing.format_duration(75.5), "1 分 15 秒")
        self.assertEqual(timing.format_duration(3661), "1 小时 01 分 01 秒")
        record = timing._new_step(15, "BR-001", timing.beijing_now())
        record["agent_executions"] = [{"elapsed_seconds": 1e308}, {"elapsed_seconds": 1e308}]
        with self.assertRaises(ValueError):
            timing._update_totals(record)


if __name__ == "__main__":
    unittest.main()
