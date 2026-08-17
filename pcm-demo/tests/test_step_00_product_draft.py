from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.state import create_run_dir
from steps.step_00_product_draft import run


class ProductDraftStepTests(unittest.TestCase):
    def test_complete_draft_skips_without_modifying_input(self) -> None:
        content = "\n".join(
            (
                "## A. 产品身份与文档边界",
                "产品身份。",
                "## C. 用户与使用场景",
                "目标用户。",
                "## D. 核心价值与业务闭环",
                "核心闭环。",
                "## E. 产品范围",
                "当前范围。",
                "## P. 产品验收",
                "验收标准。",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            prd_path = Path(directory) / "prd.md"
            prd_path.write_text(content)
            result = run(prd_path)
            self.assertEqual(result["status"], "success")
            self.assertFalse(result["applicable"])
            self.assertEqual(prd_path.read_text(), content)

    def test_incomplete_draft_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prd_path = Path(directory) / "prd.md"
            prd_path.write_text("## A. 产品身份与文档边界\n")
            result = run(prd_path)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error"]["type"], "incomplete_product_draft")

    def test_empty_required_sections_fail(self) -> None:
        content = "\n".join(
            (
                "## A. 产品身份与文档边界",
                "## C. 用户与使用场景",
                "## D. 核心价值与业务闭环",
                "## E. 产品范围",
                "## P. 产品验收",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            prd_path = Path(directory) / "prd.md"
            prd_path.write_text(content, encoding="utf-8")
            result = run(prd_path)
            self.assertEqual(result["status"], "failed")

    def test_existing_run_directory_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs_dir = Path(directory) / "runs"
            create_run_dir(runs_dir, "same-run")
            with self.assertRaises(FileExistsError):
                create_run_dir(runs_dir, "same-run")

    def test_run_id_cannot_escape_runs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                create_run_dir(Path(directory) / "runs", "../outside")


if __name__ == "__main__":
    unittest.main()
