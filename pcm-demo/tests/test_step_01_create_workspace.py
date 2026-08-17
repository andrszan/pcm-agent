from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.files import sha256
from steps.step_01_create_workspace import run


class CreateWorkspaceStepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.capability_root = self.root / "capabilities"
        for relative_path, content in (
            (Path("CLAUDE.md"), "@AGENTS.md\n"),
            (Path("AGENTS.md"), "# 规范\n"),
            (Path(".claude/skills/project-intake/SKILL.md"), "# project-intake\n"),
        ):
            path = self.capability_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        (self.capability_root / ".claude/settings.json").write_text("{}", encoding="utf-8")
        other_skill = self.capability_root / ".claude/skills/other/SKILL.md"
        other_skill.parent.mkdir(parents=True)
        other_skill.write_text("other", encoding="utf-8")
        self.prd = self.root / "source.md"
        self.prd.write_text("# 产品需求\n", encoding="utf-8")
        self.workspace = self.root / "workspace"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_copies_prd_and_only_required_capabilities(self) -> None:
        source_hash = sha256(self.prd)
        result = run(self.prd, self.workspace, self.capability_root)

        copied_prd = self.workspace / "docs/prd/source.md"
        self.assertEqual(result["status"], "success")
        self.assertEqual(sha256(copied_prd), source_hash)
        self.assertEqual(sha256(self.prd), source_hash)
        self.assertTrue((self.workspace / "CLAUDE.md").is_file())
        self.assertTrue((self.workspace / "AGENTS.md").is_file())
        self.assertTrue(
            (self.workspace / ".claude/skills/project-intake/SKILL.md").is_file()
        )
        self.assertFalse((self.workspace / ".claude/settings.json").exists())
        self.assertFalse((self.workspace / ".claude/skills/other").exists())
        self.assertFalse((self.workspace / ".git").exists())

    def test_existing_workspace_is_blocked_without_overwrite(self) -> None:
        self.workspace.mkdir()
        marker = self.workspace / "keep.txt"
        marker.write_text("keep", encoding="utf-8")

        result = run(self.prd, self.workspace, self.capability_root)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_missing_capability_file_fails_before_workspace_creation(self) -> None:
        (self.capability_root / "AGENTS.md").unlink()

        result = run(self.prd, self.workspace, self.capability_root)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(self.workspace.exists())


if __name__ == "__main__":
    unittest.main()
