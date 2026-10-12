from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import gitlab
from probes.probe_quality import prepare_fixture
from quality.git import git as quality_git
from steps.step_01_create_workspace import workspace
from steps.step_08_initialize_repositories import step as initialize
from steps.step_08_initialize_repositories.test_step import command, commit_all, isolated_git_environment
from steps.step_09_engineering_architecture import step as architecture
from steps.step_10_ui_ux_framework import step as framework
from steps.step_11_requirement_breakdown import step as breakdown
from steps.step_13_select_requirement import step as selection
from steps.step_17_commit import step as commit
from steps.step_18_merge import step as merge


class GitEnvironmentTests(unittest.TestCase):
    def test_git_children_cannot_receive_gitlab_token_and_keep_other_pcm_variables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with isolated_git_environment(root):
                repository = root / "repository"
                repository.mkdir()
                command("init", "-b", "main", cwd=repository)
                (repository / "tracked.txt").write_text("base\n")
                commit_all(repository)
                real_git = shutil.which("git")
                self.assertIsNotNone(real_git)
                bin_dir = root / "bin"
                bin_dir.mkdir()
                checked = root / "children.log"
                shim = bin_dir / "git"
                shim.write_text(
                    f"#!{sys.executable}\nimport os, sys\n"
                    "assert not any(key.upper() == 'PCM_GITLAB_TOKEN' for key in os.environ)\n"
                    "assert os.environ.get('PCM_TEST_PRESERVED') == 'keep-me'\n"
                    f"with open({str(checked)!r}, 'a') as log: log.write('checked\\n')\n"
                    f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n"
                )
                shim.chmod(0o755)
                with patch.dict(os.environ, {
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "PCM_GITLAB_TOKEN": "test-token-must-not-reach-git",
                    "pcm_gitlab_token": "test-lowercase-token",
                    "Pcm_Gitlab_Token": "test-mixed-case-token",
                    "PCM_TEST_PRESERVED": "keep-me",
                }):
                    for module in (initialize, architecture, framework, breakdown):
                        with self.subTest(step=module.STEP):
                            self.assertTrue(module._repository_facts(repository, ["root"])[0]["worktree_clean"])
                    initialize._configure_git_identity(
                        {"git_identity": {"name": "PCM Test", "email": "pcm@example.invalid"}},
                        [{"path": str(repository)}],
                    )
                    self.assertTrue(gitlab._git(repository, "rev-parse", "HEAD"))
                    self.assertTrue(quality_git(repository, "rev-parse", "HEAD"))
                    self.assertTrue(selection._git(repository, "rev-parse", "HEAD"))
                    self.assertEqual(commit._git(repository, "rev-parse", "HEAD").returncode, 0)
                    self.assertEqual(merge._git(repository, "rev-parse", "HEAD").returncode, 0)
                    merge._git_write(repository, "switch", "main")
                    self.assertTrue(workspace.git("rev-parse", "HEAD", cwd=repository))
                    self.assertFalse(workspace.git_path_is_ignored(repository, "tracked.txt"))
                    self.assertEqual(workspace.inspect_repository(repository, expected_head="present")["branch"], "main")
                    prepare_fixture(root / "probe")
                self.assertGreater(len(checked.read_text().splitlines()), 30)

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
