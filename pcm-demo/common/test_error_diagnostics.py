from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.error_diagnostics import (  # noqa: E402
    exception_diagnostics,
    redact_text,
    truncate_text,
    write_diagnostic,
)


class ErrorDiagnosticsTests(unittest.TestCase):
    def test_redacts_exact_credentials_without_removing_token_text(self) -> None:
        secret = "real secret+/="
        text = (
            f"request key={secret}; encoded=real%20secret%2B%2F%3D; "
            "Authorization: Bearer header-secret\n"
            "Cookie: session=cookie-secret\n"
            "api_key=api-secret access_token=access-secret password=pass-secret "
            "postgres://user:dsn-secret@example.invalid/db?client_secret=query-secret&token_count=8; "
            "token budget exhausted; secret=hidden"
        )

        redacted = redact_text(text, known_secrets=[secret])

        for value in (secret, "real%20secret%2B%2F%3D", "header-secret", "cookie-secret", "api-secret", "access-secret", "pass-secret", "dsn-secret", "query-secret", "hidden"):
            self.assertNotIn(value, redacted)
        self.assertIn("token_count=8", redacted)
        self.assertIn("token budget exhausted", redacted)
        self.assertIn("secret=[REDACTED]", redacted)

    def test_exception_chain_traceback_truncation_and_safe_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            try:
                try:
                    raise ValueError("password=inner-secret")
                except ValueError as cause:
                    raise RuntimeError("secret=outer-secret " + "x" * 5000) from cause
            except RuntimeError as error:
                diagnostic = exception_diagnostics(error)
                self.assertEqual(diagnostic["type"], "RuntimeError")
                self.assertEqual(diagnostic["chain"][0]["type"], "ValueError")
                self.assertTrue(diagnostic["traceback"])
                self.assertIn("[truncated]", diagnostic["message"])
                path = write_diagnostic(
                    run_dir,
                    "step-15-error.json",
                    source="test",
                    context={"step": 15},
                    error=error,
                )
            saved = json.loads((run_dir / path).read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], 1)
            self.assertNotIn("outer-secret", json.dumps(saved, ensure_ascii=False))
            self.assertNotIn("inner-secret", json.dumps(saved, ensure_ascii=False))
            self.assertEqual(truncate_text("x" * 5000).count("[truncated]"), 1)

            outside = Path(directory) / "outside"
            outside.mkdir()
            second = Path(directory) / "second"
            second.mkdir()
            (second / "logs").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "符号链接"):
                write_diagnostic(second, "step-15-error.json", source="test")
            with self.assertRaisesRegex(ValueError, "文件名"):
                write_diagnostic(run_dir, "../escape.json", source="test")

    def test_diagnostic_snapshot_is_atomically_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            first = RuntimeError("first")
            second = RuntimeError("second")
            write_diagnostic(run_dir, "step-01-error.json", source="test", error=first)
            write_diagnostic(run_dir, "step-01-error.json", source="test", error=second)
            saved = json.loads((run_dir / "logs/step-01-error.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["exception"]["message"], "second")


if __name__ == "__main__":
    unittest.main()
