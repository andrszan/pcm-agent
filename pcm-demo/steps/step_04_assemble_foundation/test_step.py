from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[3]
PCM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.files import write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace.workspace import (
    WorkspaceBlocked,
    git,
    initialize_repository,
    inspect_root_repository,
)
from steps.step_03_foundation_selection.step import TemplateSelection
from steps.step_04_assemble_foundation.step import (
    CURRENT_NODE,
    MARKER,
    NEXT_NODE,
    ownership_marker,
    run,
    temporary_root,
    verify_tree,
)


def command(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


class AssembleFoundationTests(unittest.TestCase):
    def create_remote(
        self,
        root: Path,
        *,
        branch: str = "main",
        source_symlink: bool = False,
        escape_link: bool = False,
        git_link: bool = False,
        ignore_all_frontend: bool = False,
    ) -> tuple[Path, str]:
        source = root / "template-source"
        command("init", "-b", branch, str(source))
        command("config", "user.email", "test@example.com", cwd=source)
        command("config", "user.name", "Test", cwd=source)
        frontend = source / "templates" / "frontend"
        backend = source / "templates" / "backend"
        frontend.mkdir(parents=True)
        backend.mkdir(parents=True)
        (frontend / "frontend.txt").write_text("frontend", encoding="utf-8")
        (backend / "backend.txt").write_text("backend", encoding="utf-8")
        if source_symlink:
            frontend.rename(source / "templates" / "real-frontend")
            frontend.symlink_to("real-frontend", target_is_directory=True)
        if escape_link:
            (frontend / "escape").symlink_to("../../../../outside")
        if git_link:
            (frontend / "git-metadata").symlink_to("../../.git", target_is_directory=True)
        if ignore_all_frontend:
            (frontend / ".gitignore").write_text("*\n", encoding="utf-8")
        command("add", ".", cwd=source)
        if ignore_all_frontend:
            command(
                "add",
                "-f",
                "templates/frontend/.gitignore",
                "templates/frontend/frontend.txt",
                cwd=source,
            )
        command("commit", "-m", "templates", cwd=source)
        bare = root / "templates.git"
        command("clone", "--bare", str(source), str(bare))
        return bare, bare.as_uri()

    def selection(
        self, url: str, branch: str = "main", *, frontend: str | None = "templates/frontend", backend: str | None = "templates/backend"
    ) -> dict:
        def value(target: str, path: str | None) -> dict | None:
            if path is None:
                return None
            return TemplateSelection(
                id=f"{target}-template",
                git_url=url,
                default_branch=branch,
                path=path,
                reason="test",
            ).model_dump(mode="json")

        return {"frontend": value("frontend", frontend), "backend": value("backend", backend)}

    def make_run(
        self,
        root: Path,
        selection: dict,
        *,
        run_directory_name: str = "run-directory",
        state_run_id: str = "recorded-run",
        placeholders: bool = True,
    ) -> tuple[Path, Path, dict]:
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)
        command("init", "-b", "main", cwd=workspace)
        if placeholders:
            for target in ("frontend", "backend"):
                directory = workspace / target
                directory.mkdir()
                (directory / ".gitkeep").touch()
        run_dir = root / run_directory_name
        (run_dir / "steps").mkdir(parents=True)
        write_json(
            run_dir / "steps" / "03.json",
            {
                "step": 3,
                "status": "success",
                "template_selection": selection,
            },
        )
        state = {
            "run_id": state_run_id,
            "status": "success",
            "phase": "project_initialization",
            "current_node": CURRENT_NODE,
            "step": 4,
            "current_step": 4,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "root_repository": {"path": str(workspace.resolve()), "branch": "main", "head": None},
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    def test_dual_success_records_branch_evidence_and_cleans_temporary_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare, url = self.create_remote(root, branch="release")
            run_dir, workspace, state = self.make_run(
                root, self.selection(url, "release"), run_directory_name="legacy-run-directory"
            )

            saved = run(run_dir, state)

            self.assertEqual(saved["status"], "success")
            self.assertEqual(saved["outputs"], ["frontend", "backend"])
            self.assertEqual((workspace / "frontend" / "frontend.txt").read_text(), "frontend")
            self.assertEqual((workspace / "backend" / "backend.txt").read_text(), "backend")
            for target in ("frontend", "backend"):
                self.assertEqual(
                    inspect_root_repository(workspace / target),
                    {"path": str((workspace / target).resolve()), "branch": "main", "head": None},
                )
            self.assertEqual(saved["assembly"]["frontend"]["origin"], url)
            self.assertEqual(saved["assembly"]["frontend"]["branch"], "release")
            self.assertEqual(
                saved["assembly"]["frontend"]["commit_sha"], command("rev-parse", "HEAD", cwd=bare)
            )
            saved_state = read_state(run_dir)
            self.assertEqual((saved_state["current_step"], saved_state["current_node"]), (5, NEXT_NODE))
            self.assertFalse(temporary_root(workspace, "recorded-run").exists())

    def test_same_repository_is_cloned_once_and_success_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, _, state = self.make_run(root, self.selection(url))
            clones = 0

            def count_clone(*args: str, **kwargs: object) -> str:
                nonlocal clones
                if args[0] == "clone":
                    clones += 1
                return git(*args, **kwargs)

            saved = run(run_dir, state, git_runner=count_clone)
            self.assertEqual(clones, 1)
            self.assertEqual(saved["status"], "success")

            def reject_clone(*args: str, **kwargs: object) -> str:
                if args[0] == "clone":
                    raise AssertionError("成功复用不应重新 clone")
                return git(*args, **kwargs)

            self.assertEqual(run(run_dir, read_state(run_dir), git_runner=reject_clone), saved)

    def test_null_combinations_remove_only_applicable_targets(self) -> None:
        for frontend, backend, outputs in [
            ("templates/frontend", None, ["frontend"]),
            (None, "templates/backend", ["backend"]),
            (None, None, []),
        ]:
            with self.subTest(frontend=frontend, backend=backend), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, url = self.create_remote(root)
                run_dir, workspace, state = self.make_run(
                    root, self.selection(url, frontend=frontend, backend=backend)
                )
                saved = run(run_dir, state)
                self.assertEqual(saved["outputs"], outputs)
                for target in outputs:
                    self.assertEqual(inspect_root_repository(workspace / target)["head"], None)
                self.assertEqual((workspace / "frontend").exists(), frontend is not None)
                self.assertEqual((workspace / "backend").exists(), backend is not None)

    def test_missing_targets_are_allowed_but_non_placeholder_targets_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, workspace, state = self.make_run(root, self.selection(url))
            for target in ("frontend", "backend"):
                shutil.rmtree(workspace / target)
            self.assertEqual(run(run_dir, state)["status"], "success")

        for kind in ("empty", "extra", "symlink", "existing"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, url = self.create_remote(root)
                run_dir, workspace, state = self.make_run(root, self.selection(url))
                target = workspace / "frontend"
                if kind == "empty":
                    (target / ".gitkeep").unlink()
                elif kind == "extra":
                    (target / "extra").write_text("keep", encoding="utf-8")
                elif kind == "symlink":
                    shutil.rmtree(target)
                    outside = root / "outside"
                    outside.mkdir()
                    target.symlink_to(outside, target_is_directory=True)
                else:
                    shutil.rmtree(target)
                    target.mkdir()
                    (target / "project.py").write_text("keep", encoding="utf-8")
                saved = run(run_dir, state)
                self.assertEqual(saved["status"], "failed")
                if kind != "symlink":
                    self.assertTrue(target.exists())

    def test_invalid_template_paths_and_trees_do_not_publish_early(self) -> None:
        cases = [
            ("absolute", "/templates/frontend", False, False, False, False),
            ("parent", "templates/../frontend", False, False, False, False),
            ("missing", "templates/missing", False, False, False, False),
            ("source-link", "templates/frontend", True, False, False, False),
            ("escape-link", "templates/frontend", False, True, False, False),
            ("git-link", "templates/frontend", False, False, True, False),
            ("source-git", "templates/frontend", False, False, False, True),
        ]
        for name, path, source_symlink, escape_link, git_link, nested_git in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, url = self.create_remote(
                    root,
                    source_symlink=source_symlink,
                    escape_link=escape_link,
                    git_link=git_link,
                )
                selection = self.selection(url, frontend=path, backend="templates/backend")
                run_dir, workspace, state = self.make_run(root, selection)

                def inject_nested_git(*args: str, **kwargs: object) -> str:
                    value = git(*args, **kwargs)
                    if nested_git and args[0] == "clone":
                        (Path(args[-1]) / "templates" / "frontend" / ".git").mkdir()
                    return value

                saved = run(run_dir, state, git_runner=inject_nested_git)
                self.assertEqual(saved["status"], "failed")
                self.assertTrue((workspace / "frontend" / ".gitkeep").is_file())
                self.assertTrue((workspace / "backend" / ".gitkeep").is_file())

    def test_payload_initialization_failure_does_not_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, workspace, state = self.make_run(root, self.selection(url))
            original_initialize = initialize_repository

            def fail_backend(payload: Path) -> dict[str, str | None]:
                if payload.name == "backend":
                    raise RuntimeError("backend Git 初始化失败")
                return original_initialize(payload)

            with patch(
                "steps.step_04_assemble_foundation.step.initialize_repository",
                side_effect=fail_backend,
            ):
                saved = run(run_dir, state)

            self.assertEqual(saved["status"], "failed")
            for target in ("frontend", "backend"):
                self.assertTrue((workspace / target / ".gitkeep").is_file())
            temporary = temporary_root(workspace, state["run_id"])
            self.assertTrue((temporary / "payloads/frontend/.git").is_dir())
            self.assertTrue((temporary / "payloads/backend").is_dir())

    def test_payload_without_committable_files_does_not_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root, ignore_all_frontend=True)
            run_dir, workspace, state = self.make_run(
                root,
                self.selection(url, backend=None),
            )

            saved = run(run_dir, state)

            self.assertEqual(saved["status"], "failed")
            self.assertIn("没有可提交文件", saved["error"]["message"])
            self.assertTrue((workspace / "frontend/.gitkeep").is_file())

    def test_blocked_authentication_and_normal_git_failure_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, _, state = self.make_run(root, self.selection(url))

            def blocked_clone(*args: str, **kwargs: object) -> str:
                if args[0] == "clone":
                    raise WorkspaceBlocked("缺少模板仓库读取权限")
                return git(*args, **kwargs)

            self.assertEqual(run(run_dir, state, git_runner=blocked_clone)["status"], "blocked")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, _, state = self.make_run(root, self.selection(url))

            def rejected_clone(*args: str, **kwargs: object) -> str:
                raise RuntimeError("fatal: Authentication failed for template repository")

            self.assertEqual(run(run_dir, state, git_runner=rejected_clone)["status"], "blocked")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, _, state = self.make_run(root, self.selection(url))

            def missing_repository(*args: str, **kwargs: object) -> str:
                raise RuntimeError("fatal: repository not found")

            self.assertEqual(run(run_dir, state, git_runner=missing_repository)["status"], "failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, _, state = self.make_run(root, self.selection(url, "does-not-exist"))
            self.assertEqual(run(run_dir, state)["status"], "failed")

    def test_verified_residual_retries_and_unknown_residual_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, workspace, state = self.make_run(root, self.selection(url))
            temporary = temporary_root(workspace.resolve(), state["run_id"])
            temporary.mkdir()
            write_json(temporary / MARKER, ownership_marker(workspace.resolve(), state["run_id"]))
            (temporary / "partial").write_text("old", encoding="utf-8")
            self.assertEqual(run(run_dir, state)["status"], "success")
            self.assertFalse(temporary.exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, workspace, state = self.make_run(root, self.selection(url))
            temporary = temporary_root(workspace, state["run_id"])
            temporary.mkdir()
            write_json(temporary / MARKER, {"run_id": "other", "product_path": str(workspace), "step": 4})
            self.assertEqual(run(run_dir, state)["status"], "failed")
            self.assertTrue(temporary.exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, workspace, state = self.make_run(root, self.selection(url))
            original_rename = os.rename

            def fail_backend(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
                if Path(target).name == "backend":
                    raise OSError("backend publish failed")
                original_rename(source, target)

            with patch(
                "steps.step_04_assemble_foundation.step.os.rename",
                side_effect=fail_backend,
            ):
                self.assertEqual(run(run_dir, state)["status"], "failed")
            self.assertTrue((workspace / "frontend" / "frontend.txt").is_file())
            self.assertEqual(inspect_root_repository(workspace / "frontend")["head"], None)
            self.assertFalse((workspace / "backend").exists())
            temporary = temporary_root(workspace, state["run_id"])
            self.assertTrue(temporary.exists())
            self.assertTrue((temporary / "payloads/backend/.git").is_dir())
            self.assertEqual(run(run_dir, read_state(run_dir))["status"], "failed")
            self.assertTrue((workspace / "frontend" / "frontend.txt").is_file())

    def test_cli_runs_step_four_synchronously(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, _, _ = self.make_run(root, self.selection(url), run_directory_name="cli-run")
            demo_runs = PCM_ROOT / "runs"
            destination = demo_runs / "cli-run"
            if destination.exists():
                self.skipTest("本地 demo runs 已存在 cli-run")
            try:
                os.rename(run_dir, destination)
                completed = subprocess.run(
                    [sys.executable, str(PCM_ROOT / "run_step.py"), "--step", "4", "--run-id", "cli-run"],
                    cwd=PCM_ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("04.json", completed.stdout)
            finally:
                if destination.exists():
                    os.rename(destination, run_dir)

    def test_cli_reports_missing_or_unknown_run_id_with_step_four_schema(self) -> None:
        for arguments in ([], ["--run-id", "missing-run"]):
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    [sys.executable, str(PCM_ROOT / "run_step.py"), "--step", "4", *arguments],
                    cwd=PCM_ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn("第 4 步执行失败", completed.stderr)
                self.assertNotIn("TypeError", completed.stderr)

    def test_success_reuse_requires_matching_result_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, url = self.create_remote(root)
            run_dir, _, state = self.make_run(root, self.selection(url))
            saved = run(run_dir, state)
            saved["assembly"]["frontend"]["origin"] = "file:///different.git"
            write_json(run_dir / "steps" / "04.json", saved)
            failed = run(run_dir, read_state(run_dir))
            self.assertEqual(failed["status"], "failed")

    def test_git_errors_are_saved_without_remote_error_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_url = "https://user:secret@example.invalid/templates.git"
            run_dir, _, state = self.make_run(root, self.selection(secret_url))

            def failing_clone(*args: str, **kwargs: object) -> str:
                raise RuntimeError("fatal: https://user:secret@example.invalid/templates.git")

            saved = run(run_dir, state, git_runner=failing_clone)
            self.assertEqual(saved["error"]["message"], "模板仓库 clone 失败")
            self.assertNotIn("secret", json.dumps(saved, ensure_ascii=False))

    def test_verify_tree_rejects_nested_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clone = root / "clone"
            source = clone / "template"
            source.mkdir(parents=True)
            (source / ".git").mkdir()
            with self.assertRaisesRegex(RuntimeError, "包含 .git"):
                verify_tree(source)


if __name__ == "__main__":
    unittest.main()
