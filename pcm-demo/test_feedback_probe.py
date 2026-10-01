from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from probes.probe_feedback import changed_paths_since, git


class FeedbackProbeTests(unittest.TestCase):
    def test_git_paths_preserve_chinese_spaces_and_newlines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            git(root, "init", "-b", "main")
            git(root, "config", "user.name", "测试")
            git(root, "config", "user.email", "test@example.com")
            (root / "README.md").write_text("测试基线\n")
            git(root, "add", "--", "README.md")
            git(root, "commit", "-m", "test: 基线")
            base = git(root, "rev-parse", "HEAD")
            names = {"docs/feedback/中文 名称.md", "docs/feedback/多行\n名称.md"}
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("核验结果\n")
            git(root, "add", "--", *sorted(names))
            git(root, "commit", "-m", "docs: 反馈")
            self.assertEqual(set(changed_paths_since(root, base)), names)
            self.assertTrue(all(name.startswith("docs/feedback/") for name in changed_paths_since(root, base)))


if __name__ == "__main__":
    unittest.main()
