from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steps.step_08_initialize_repositories import step as initialize
from steps.step_08_initialize_repositories.test_step import command, commit_all
from steps.step_09_engineering_architecture import step as architecture
from steps.step_10_ui_ux_framework import step as framework
from steps.step_11_requirement_breakdown import step as breakdown


class GitEnvironmentTests(unittest.TestCase):
    def test_real_dirty_index_cannot_be_hidden_by_alternate_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            command("init", "-b", "main", cwd=repository)
            tracked = repository / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            commit_all(repository)
            alternate = root / "clean-index"
            shutil.copyfile(repository / ".git/index", alternate)
            tracked.write_text("staged\n", encoding="utf-8")
            command("add", "tracked.txt", cwd=repository)
            tracked.write_text("base\n", encoding="utf-8")
            self.assertTrue(command("status", "--porcelain", cwd=repository))
            with patch.dict(os.environ, {"GIT_INDEX_FILE": str(alternate)}):
                self.assertEqual(command("status", "--porcelain", cwd=repository), "")
                for module in (initialize, architecture, framework, breakdown):
                    with self.subTest(step=module.STEP):
                        self.assertFalse(module._repository_facts(repository, ["root"])[0]["worktree_clean"])

    def test_repository_redirections_do_not_override_authoritative_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command("init", "-b", "main", cwd=root)
            redirections = {
                "GIT_DIR": str(root / "missing-git"),
                "GIT_WORK_TREE": str(root / "missing-worktree"),
                "GIT_COMMON_DIR": str(root / "missing-common"),
                "GIT_OBJECT_DIRECTORY": str(root / "missing-objects"),
            }
            with patch.dict(os.environ, redirections):
                for module in (initialize, architecture, framework, breakdown):
                    with self.subTest(step=module.STEP):
                        self.assertTrue(module._repository_facts(root, ["root"])[0]["worktree_clean"])
                initialize._configure_git_identity(
                    {"git_identity": {"name": "PCM Test", "email": "pcm@example.invalid"}},
                    [{"path": str(root)}],
                )
            self.assertEqual(command("config", "--local", "--get", "user.name", cwd=root), "PCM Test")
            self.assertEqual(command("config", "--local", "--get", "user.email", cwd=root), "pcm@example.invalid")
            self.assertFalse((root / "missing-git").exists())
