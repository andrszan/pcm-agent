from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

DEMO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_ROOT))

import run_step


class RunStepRetryTests(unittest.TestCase):
    def test_success_does_not_retry(self) -> None:
        runner = Mock(return_value=0)
        sleeper = Mock()
        with (
            patch.object(run_step, "main", runner),
            patch.object(run_step.time, "sleep", sleeper),
        ):
            self.assertEqual(run_step.retrying_main(), 0)
        runner.assert_called_once_with()
        sleeper.assert_not_called()

    def test_any_step_failure_retries_twice(self) -> None:
        runner = Mock(side_effect=[1, 1, 0])
        sleeper = Mock()
        stderr = io.StringIO()
        with (
            patch.object(run_step, "main", runner),
            patch.object(run_step.time, "sleep", sleeper),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(run_step.retrying_main(), 0)
        self.assertEqual(runner.call_count, 3)
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [10, 30])
        self.assertIn("10 秒后重试", stderr.getvalue())
        self.assertIn("30 秒后重试", stderr.getvalue())

    def test_failure_after_all_attempts_returns_failure(self) -> None:
        runner = Mock(return_value=1)
        with (
            patch.object(run_step, "main", runner),
            patch.object(run_step.time, "sleep"),
        ):
            self.assertEqual(run_step.retrying_main(), 1)
        self.assertEqual(runner.call_count, 3)

    def test_cli_error_does_not_retry(self) -> None:
        runner = Mock(return_value=2)
        sleeper = Mock()
        with (
            patch.object(run_step, "main", runner),
            patch.object(run_step.time, "sleep", sleeper),
        ):
            self.assertEqual(run_step.retrying_main(), 2)
        runner.assert_called_once_with()
        sleeper.assert_not_called()

    def test_cancellation_is_not_retried(self) -> None:
        runner = Mock(side_effect=KeyboardInterrupt)
        with (
            patch.object(run_step, "main", runner),
            patch.object(run_step.time, "sleep") as sleeper,
            self.assertRaises(KeyboardInterrupt),
        ):
            run_step.retrying_main()
        runner.assert_called_once_with()
        sleeper.assert_not_called()


if __name__ == "__main__":
    unittest.main()
