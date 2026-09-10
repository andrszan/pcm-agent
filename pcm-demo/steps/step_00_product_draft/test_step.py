"""第 0 步测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[3]
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

    def test_freeform_draft_passes_without_modifying_input(self) -> None:
        for content in (
            "做一个供档案修复人员使用的手稿拼合 Web 工具。",
            "# 想法\n\n我想在浏览器中拼合破损手稿。\n\n## 还没想清楚\n保存方式。\n",
            "## A. 产品身份与文档边界\n",
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                prd_path = Path(directory) / "idea.txt"
                raw = content.encode("utf-8")
                prd_path.write_bytes(raw)
                result = run(prd_path)
                self.assertEqual(result["status"], "success")
                self.assertFalse(result["applicable"])
                self.assertEqual(result["outputs"], [])
                self.assertEqual(prd_path.read_bytes(), raw)

    def test_empty_or_whitespace_draft_fails(self) -> None:
        for content in ("", " \t\n　"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                prd_path = Path(directory) / "idea.txt"
                prd_path.write_text(content, encoding="utf-8")
                result = run(prd_path)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"]["type"], "empty_product_draft")

    def test_unreadable_draft_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "idea.txt"
            with self.assertRaises(FileNotFoundError):
                run(path)
            path.write_bytes(b"\xff")
            with self.assertRaises(UnicodeDecodeError):
                run(path)

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
