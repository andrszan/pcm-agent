from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from quality.git import changed_paths, clean_repository, git
from quality.workflow import _pool_boundary


class QualityGitTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "测试")
        git(self.root, "config", "user.email", "test@example.com")
        (self.root / "base.txt").write_text("base\n")
        git(self.root, "add", "base.txt")
        git(self.root, "commit", "-m", "初始版本")
        self.base = git(self.root, "rev-parse", "HEAD")

    def test_nul_paths_preserve_leading_space_and_pool_rejects_outside_file(self):
        relative = " docs/backlog.md"
        path = self.root / relative
        path.parent.mkdir()
        path.write_text("不属于允许范围\n")
        state = {
            "workspace": {"root": str(self.root.parent), "final_path": str(self.root)},
            "applicable_repositories": ["root"],
            "repositories": [{"name": "root", "path": str(self.root)}],
        }
        intent = {"branch": "main", "base": self.base, "versions": {"root": self.base},
                  "allowed_paths": ["docs/backlog.md"]}
        for tracked in (False, True):
            with self.subTest(tracked=tracked):
                if tracked:
                    git(self.root, "add", relative)
                self.assertEqual(changed_paths(self.root, self.base), {relative})
                with self.assertRaisesRegex(RuntimeError, "范围外"):
                    _pool_boundary(state, intent)
                self.assertEqual(path.read_text(), "不属于允许范围\n")
        self.assertEqual(git(self.root, "branch", "--show-current"), "main")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.base)

    def test_clean_main_bisect_is_rejected_until_bisect_reset(self):
        git(self.root, "bisect", "start")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "branch", "--show-current"), "main")
        with self.assertRaisesRegex(RuntimeError, "Git 操作"):
            clean_repository(self.root, "main")
        git(self.root, "bisect", "reset")
        self.assertEqual(clean_repository(self.root, "main"), self.base)

    def test_clean_main_sequencer_is_rejected_until_sequence_quit(self):
        git(self.root, "switch", "-c", "topic")
        commits = []
        for text in ("topic first\n", "topic second\n"):
            (self.root / "base.txt").write_text(text)
            git(self.root, "commit", "-am", text.strip())
            commits.append(git(self.root, "rev-parse", "HEAD"))
        git(self.root, "switch", "main")
        (self.root / "base.txt").write_text("main change\n")
        git(self.root, "commit", "-am", "主线变更")
        tip = git(self.root, "rev-parse", "HEAD")
        result = subprocess.run(["git", "-C", str(self.root), "cherry-pick", *commits], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        git(self.root, "reset", "--hard", "HEAD")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertIsNone(git(self.root, "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD", optional=True))
        self.assertTrue((self.root / ".git/sequencer").is_dir())
        with self.assertRaisesRegex(RuntimeError, "Git 操作"):
            clean_repository(self.root, "main")
        git(self.root, "cherry-pick", "--quit")
        self.assertEqual(clean_repository(self.root, "main"), tip)


if __name__ == "__main__":
    unittest.main()
