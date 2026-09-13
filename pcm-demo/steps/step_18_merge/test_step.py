from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.state import read_state, write_requirement_step_result, write_state
import steps.step_18_merge.step as merge_step
from steps.step_18_merge.step import (
    CURRENT_NODE,
    NAME,
    NEXT_NODE,
    PHASE,
    STEP,
    failure_scope,
    has_complete_success,
    result,
    run,
)


def command(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


def commit_all(repository: Path, message: str) -> str:
    command("add", "-A", cwd=repository)
    command(
        "-c",
        "user.name=PCM Test",
        "-c",
        "user.email=pcm@example.invalid",
        "commit",
        "-m",
        message,
        cwd=repository,
    )
    return command("rev-parse", "HEAD", cwd=repository)


class RequirementMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_run(
        self, children: list[str] | None = None, *, changes: bool = True
    ) -> tuple[Path, Path, dict[str, Any], dict[str, Path], dict[str, str], dict[str, str]]:
        children = children or []
        run_dir = self.root / f"run-{len(list(self.root.glob('run-*')))}"
        (run_dir / "steps/requirements/BR-001").mkdir(parents=True)
        workspace_root = self.root / "workspace-root"
        workspace = workspace_root / run_dir.name
        workspace.mkdir(parents=True)
        command("init", "-b", "main", cwd=workspace)
        (workspace / "base.txt").write_text("root base\n", encoding="utf-8")
        root_base = commit_all(workspace, "root base")

        repositories: dict[str, Path] = {"root": workspace}
        bases = {"root": root_base}
        for name in children:
            repository = workspace / name
            repository.mkdir()
            command("init", "-b", "main", cwd=repository)
            (repository / "base.txt").write_text(f"{name} base\n", encoding="utf-8")
            repositories[name] = repository
            bases[name] = commit_all(repository, f"{name} base")
        if children:
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as file:
                for name in children:
                    file.write(f"{name}/\n")

        for repository in repositories.values():
            command("switch", "-c", "req/br-001", cwd=repository)
        tips = dict(bases)
        if changes:
            for name, repository in repositories.items():
                (repository / "change.txt").write_text(f"{name} change\n", encoding="utf-8")
                tips[name] = commit_all(repository, f"feat: {name}")

        names = list(repositories)
        state: dict[str, Any] = {
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "applicable_repositories": names,
            "repositories": [
                {
                    "name": name,
                    "path": str(repository),
                    "branch": "main",
                    "worktree_clean": True,
                }
                for name, repository in repositories.items()
            ],
            "requirement_registry": {
                "schema_version": 1,
                "requirements": [
                    {
                        "id": "BR-001",
                        "title": "账户访问",
                        "order": 1,
                        "depends_on": [],
                        "status": "active",
                        "completion": None,
                    }
                ],
            },
            "active_requirement": "BR-001",
            "requirement_cycle": {
                "requirement_id": "BR-001",
                "branch": "req/br-001",
                "repositories": {
                    name: {
                        "base_sha": bases[name],
                        "tip_sha": tips[name],
                        "merged": False,
                    }
                    for name in names
                },
                "trd_path": "docs/trd/BR-001.md",
                "development_session_id": "development-session-1",
                "return_node_after_completion": NEXT_NODE,
            },
            "blocked": None,
            "error": None,
        }
        write_requirement_step_result(
            run_dir,
            "BR-001",
            17,
            {
                "step": 17,
                "name": "统一提交需求变更",
                "status": "success",
                "summary": "已提交。",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "requirement_id": "BR-001",
                "branch": "req/br-001",
                "repositories": [
                    {
                        "name": name,
                        "path": "." if name == "root" else name,
                        "base_sha": bases[name],
                        "tip_sha": tips[name],
                    }
                    for name in names
                ],
            },
        )
        write_state(run_dir, state)
        return run_dir, workspace, state, repositories, bases, tips

    @staticmethod
    def update_recorded_repository(
        run_dir: Path,
        state: dict[str, Any],
        name: str,
        *,
        base: str | None = None,
        tip: str | None = None,
    ) -> None:
        recorded = state["requirement_cycle"]["repositories"][name]
        commit_path = run_dir / "steps/requirements/BR-001/17.json"
        commit_result = json.loads(commit_path.read_text(encoding="utf-8"))
        repository_result = next(
            item for item in commit_result["repositories"] if item["name"] == name
        )
        if base is not None:
            recorded["base_sha"] = base
            repository_result["base_sha"] = base
        if tip is not None:
            recorded["tip_sha"] = tip
            repository_result["tip_sha"] = tip
        write_requirement_step_result(run_dir, "BR-001", 17, commit_result)
        write_state(run_dir, state)

    @staticmethod
    def merge_and_delete(repositories: dict[str, Path]) -> None:
        for repository in [*list(repositories.values())[1:], repositories["root"]]:
            command("switch", "main", cwd=repository)
            command("merge", "--ff-only", "req/br-001", cwd=repository)
            command("branch", "-d", "req/br-001", cwd=repository)

    def assert_final(self, repositories: dict[str, Path], tips: dict[str, str]) -> None:
        for name, repository in repositories.items():
            with self.subTest(repository=name):
                self.assertEqual(command("branch", "--show-current", cwd=repository), "main")
                self.assertEqual(command("rev-parse", "HEAD", cwd=repository), tips[name])
                self.assertEqual(command("rev-parse", "main", cwd=repository), tips[name])
                self.assertEqual(
                    command("status", "--porcelain=v1", "--untracked-files=all", cwd=repository),
                    "",
                )
                self.assertEqual(
                    subprocess.run(
                        ["git", "show-ref", "--verify", "--quiet", "refs/heads/req/br-001"],
                        cwd=repository,
                    ).returncode,
                    1,
                )

    def test_dynamic_multi_repository_merges_and_cleans_non_root_first(self) -> None:
        run_dir, _workspace, state, repositories, _bases, tips = self.make_run(["web", "api"])
        writes: list[tuple[Path, tuple[str, ...]]] = []
        original = merge_step._git_write

        def recorded(path: Path, *args: str) -> None:
            writes.append((path, args))
            original(path, *args)

        with patch.object(merge_step, "_git_write", side_effect=recorded):
            saved = run(run_dir, state)

        self.assertEqual(saved["name"], NAME)
        self.assertEqual([item["name"] for item in saved["repositories"]], ["root", "web", "api"])
        merge_order = [path for path, args in writes if args[:2] == ("merge", "--ff-only")]
        delete_order = [path for path, args in writes if args[:2] == ("branch", "-d")]
        self.assertEqual(
            [path.resolve() for path in merge_order],
            [repositories["web"].resolve(), repositories["api"].resolve(), repositories["root"].resolve()],
        )
        self.assertEqual(
            [path.resolve() for path in delete_order],
            [repositories["web"].resolve(), repositories["api"].resolve(), repositories["root"].resolve()],
        )
        self.assert_final(repositories, tips)
        final = read_state(run_dir)
        self.assertEqual((final["step"], final["current_step"], final["current_node"]), (13, 13, NEXT_NODE))
        self.assertIsNone(final["active_requirement"])
        self.assertIsNone(final["requirement_cycle"])
        self.assertEqual(final["requirement_registry"]["requirements"][0]["completion"], {"step": 18})
        self.assertIsNone(failure_scope(run_dir, final))
        self.assertFalse(has_complete_success(run_dir, final))

    def test_target_ignore_rule_allows_hidden_artifacts_across_switch(self) -> None:
        run_dir, _workspace, state, repositories, _bases, tips = self.make_run(["web"])
        repository = repositories["web"]
        (repository / ".gitignore").write_text("/.generated/\n", encoding="utf-8")
        tip = commit_all(repository, "ignore generated artifacts")
        generated = repository / ".generated/result.yml"
        generated.parent.mkdir()
        generated.write_text("temporary\n", encoding="utf-8")
        self.assertEqual(
            command("status", "--porcelain=v1", "--untracked-files=all", cwd=repository),
            "",
        )

        tips["web"] = tip
        state["requirement_cycle"]["repositories"]["web"]["tip_sha"] = tip
        commit_path = run_dir / "steps/requirements/BR-001/17.json"
        commit_result = json.loads(commit_path.read_text(encoding="utf-8"))
        next(item for item in commit_result["repositories"] if item["name"] == "web")[
            "tip_sha"
        ] = tip
        write_requirement_step_result(run_dir, "BR-001", 17, commit_result)
        write_state(run_dir, state)

        run(run_dir, state)

        self.assert_final(repositories, tips)
        self.assertTrue(generated.exists())

    def test_intermediate_main_fast_forwards_to_saved_tip_sha(self) -> None:
        run_dir, _workspace, state, repositories, bases, tips = self.make_run()
        repository = repositories["root"]
        middle = tips["root"]
        (repository / "later.txt").write_text("later\n", encoding="utf-8")
        saved_tip = commit_all(repository, "feat: saved tip")
        tips["root"] = saved_tip
        self.update_recorded_repository(run_dir, state, "root", tip=saved_tip)
        command("branch", "-f", "main", middle, cwd=repository)
        writes: list[tuple[str, ...]] = []
        original = merge_step._git_write

        def recorded(path: Path, *args: str) -> None:
            writes.append(args)
            original(path, *args)

        with patch.object(merge_step, "_git_write", side_effect=recorded):
            run(run_dir, state)

        self.assertNotEqual(bases["root"], middle)
        self.assertIn(("merge", "--ff-only", saved_tip), writes)
        self.assertNotIn(("merge", "--ff-only", "req/br-001"), writes)
        self.assert_final(repositories, tips)

    def test_no_op_still_rejects_base_that_is_not_main_ancestor(self) -> None:
        run_dir, _workspace, state, repositories, _bases, tips = self.make_run()
        repository = repositories["root"]
        command("switch", "main", cwd=repository)
        command("merge", "--ff-only", tips["root"], cwd=repository)
        command("switch", "req/br-001", cwd=repository)
        command("switch", "-c", "invalid-base", cwd=repository)
        (repository / "invalid-base.txt").write_text("invalid\n", encoding="utf-8")
        invalid_base = commit_all(repository, "invalid base")
        command("switch", "req/br-001", cwd=repository)
        self.update_recorded_repository(run_dir, state, "root", base=invalid_base)

        with self.assertRaisesRegex(RuntimeError, "root.*base 不是 main 的祖先"):
            run(run_dir, state)

    def test_main_move_during_switch_is_rejected_against_captured_main(self) -> None:
        run_dir, _workspace, state, repositories, _bases, tips = self.make_run()
        repository = repositories["root"]
        middle = tips["root"]
        (repository / "later.txt").write_text("later\n", encoding="utf-8")
        saved_tip = commit_all(repository, "feat: saved tip")
        tips["root"] = saved_tip
        self.update_recorded_repository(run_dir, state, "root", tip=saved_tip)
        command("branch", "-f", "main", state["requirement_cycle"]["repositories"]["root"]["base_sha"], cwd=repository)
        original = merge_step._git_write
        moved = False

        def racing_switch(path: Path, *args: str) -> None:
            nonlocal moved
            if args == ("switch", "main") and not moved:
                moved = True
                command("branch", "-f", "main", middle, cwd=repository)
            original(path, *args)

        with patch.object(merge_step, "_git_write", side_effect=racing_switch):
            with self.assertRaisesRegex(RuntimeError, "root.*captured main"):
                run(run_dir, state)

        self.assertEqual(command("rev-parse", "main", cwd=repository), middle)
        self.assertNotEqual(command("rev-parse", "main", cwd=repository), saved_tip)

    def test_reference_move_before_merge_does_not_merge_unrecorded_tip(self) -> None:
        run_dir, _workspace, state, repositories, _bases, tips = self.make_run()
        repository = repositories["root"]
        saved_tip = tips["root"]
        original = merge_step._git_write
        moved_tip: str | None = None

        def racing_write(path: Path, *args: str) -> None:
            nonlocal moved_tip
            if args[:2] == ("merge", "--ff-only") and moved_tip is None:
                command("switch", "req/br-001", cwd=repository)
                (repository / "late.txt").write_text("late\n", encoding="utf-8")
                moved_tip = commit_all(repository, "late unrecorded tip")
                command("switch", "main", cwd=repository)
            original(path, *args)

        with patch.object(merge_step, "_git_write", side_effect=racing_write):
            with self.assertRaisesRegex(RuntimeError, "root.*target.*saved tip"):
                run(run_dir, state)

        self.assertIsNotNone(moved_tip)
        self.assertEqual(command("rev-parse", "main", cwd=repository), saved_tip)
        self.assertNotEqual(command("rev-parse", "main", cwd=repository), moved_tip)

    def test_base_equal_tip_is_a_legal_no_op(self) -> None:
        run_dir, _workspace, state, repositories, bases, tips = self.make_run(["web"], changes=False)
        writes: list[tuple[str, ...]] = []
        original = merge_step._git_write

        def recorded(path: Path, *args: str) -> None:
            writes.append(args)
            original(path, *args)

        with patch.object(merge_step, "_git_write", side_effect=recorded):
            run(run_dir, state)

        self.assertEqual(bases, tips)
        self.assertFalse(any(args[0] == "merge" for args in writes))
        self.assert_final(repositories, tips)

    def test_partial_merge_recovery_marks_existing_main_tip_without_remerge(self) -> None:
        run_dir, _workspace, state, repositories, _bases, tips = self.make_run(["web", "api"])
        command("switch", "main", cwd=repositories["web"])
        command("merge", "--ff-only", "req/br-001", cwd=repositories["web"])
        writes: list[tuple[Path, tuple[str, ...]]] = []
        original = merge_step._git_write

        def recorded(path: Path, *args: str) -> None:
            writes.append((path, args))
            original(path, *args)

        with patch.object(merge_step, "_git_write", side_effect=recorded):
            run(run_dir, state)

        self.assertFalse(any(path == repositories["web"] and args[0] == "merge" for path, args in writes))
        self.assert_final(repositories, tips)

    def test_all_merged_and_saved_success_cannot_bypass_base_ancestry(self) -> None:
        for saved_success in (False, True):
            with self.subTest(saved_success=saved_success):
                run_dir, _workspace, state, repositories, bases, tips = self.make_run()
                repository = repositories["root"]
                command("switch", "-c", "invalid-base", cwd=repository)
                (repository / "invalid-base.txt").write_text("invalid\n", encoding="utf-8")
                invalid_base = commit_all(repository, "invalid base")
                command("switch", "req/br-001", cwd=repository)
                self.merge_and_delete(repositories)
                state["requirement_cycle"]["repositories"]["root"]["merged"] = True
                self.update_recorded_repository(run_dir, state, "root", base=invalid_base)
                if saved_success:
                    saved = result(
                        "success", "已完成。", requirement_id="BR-001", branch="req/br-001",
                        repositories=[{
                            "name": "root", "path": ".", "base_sha": invalid_base,
                            "tip_sha": tips["root"],
                        }],
                    )
                    write_requirement_step_result(run_dir, "BR-001", STEP, saved)

                with self.assertRaisesRegex(RuntimeError, "root.*base 不是 main 的祖先"):
                    run(run_dir, state)

                self.assertEqual(command("rev-parse", "main", cwd=repository), tips["root"])
                self.assertNotEqual(bases["root"], invalid_base)

    def test_success_result_recovers_state_read_only(self) -> None:
        run_dir, _workspace, state, repositories, bases, tips = self.make_run(["web"])
        self.merge_and_delete(repositories)
        for repository in state["requirement_cycle"]["repositories"].values():
            repository["merged"] = True
        write_state(run_dir, state)
        saved = result(
            "success",
            "已完成。",
            requirement_id="BR-001",
            branch="req/br-001",
            repositories=[
                {
                    "name": name,
                    "path": "." if name == "root" else name,
                    "base_sha": bases[name],
                    "tip_sha": tips[name],
                }
                for name in repositories
            ],
        )
        saved["evidence"] = {"source": "step18"}
        saved["repositories"][0]["merge_mode"] = "ff-only"
        write_requirement_step_result(run_dir, "BR-001", STEP, saved)
        self.assertTrue(has_complete_success(run_dir, state))
        with patch.object(merge_step, "_git_write", side_effect=AssertionError("不能写 Git")):
            self.assertEqual(run(run_dir, state), saved)
        self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_partial_cleanup_recovery_allows_only_already_merged_missing_branch(self) -> None:
        run_dir, _workspace, state, repositories, _bases, tips = self.make_run(["web", "api"])
        for repository in [*list(repositories.values())[1:], repositories["root"]]:
            command("switch", "main", cwd=repository)
            command("merge", "--ff-only", "req/br-001", cwd=repository)
        for item in state["requirement_cycle"]["repositories"].values():
            item["merged"] = True
        command("branch", "-d", "req/br-001", cwd=repositories["web"])
        write_state(run_dir, state)

        run(run_dir, state)

        self.assert_final(repositories, tips)

    def test_cleanup_waits_until_every_repository_main_is_tip(self) -> None:
        run_dir, _workspace, state, repositories, _bases, _tips = self.make_run(["web", "api"])
        for name in ("root", "web"):
            repository = repositories[name]
            command("switch", "main", cwd=repository)
            command("merge", "--ff-only", "req/br-001", cwd=repository)
        for item in state["requirement_cycle"]["repositories"].values():
            item["merged"] = True
        write_state(run_dir, state)
        writes: list[tuple[str, ...]] = []

        with patch.object(
            merge_step,
            "_git_write",
            side_effect=lambda _path, *args: writes.append(args),
        ):
            with self.assertRaisesRegex(RuntimeError, "api.*saved tip"):
                run(run_dir, state)

        self.assertEqual(writes, [])
        for repository in repositories.values():
            self.assertEqual(
                subprocess.run(
                    ["git", "show-ref", "--verify", "--quiet", "refs/heads/req/br-001"],
                    cwd=repository,
                ).returncode,
                0,
            )

    def test_failed_or_incomplete_result_does_not_block_rerun(self) -> None:
        for saved in (
            result("failed", "失败。", requirement_id="BR-001", branch="req/br-001"),
            {"status": "failed"},
        ):
            with self.subTest(saved=saved):
                run_dir, _workspace, state, repositories, _bases, tips = self.make_run(["web"])
                write_requirement_step_result(run_dir, "BR-001", STEP, saved)
                run(run_dir, state)
                self.assert_final(repositories, tips)

    def test_conflicting_commit_result_is_rejected_before_git_writes(self) -> None:
        for field, value in (
            ("step", 16),
            ("status", "failed"),
            ("requirement_id", "BR-002"),
            ("branch", "req/br-002"),
            ("applicable", False),
            ("blocked", {"reason": "blocked"}),
            ("error", {"type": "RuntimeError", "message": "failed"}),
        ):
            with self.subTest(conflicting_field=field):
                run_dir, _workspace, state, _repositories, _bases, _tips = self.make_run(["web"])
                commit_path = run_dir / "steps/requirements/BR-001/17.json"
                commit_result = json.loads(commit_path.read_text(encoding="utf-8"))
                commit_result[field] = value
                write_requirement_step_result(run_dir, "BR-001", 17, commit_result)
                with patch.object(merge_step, "_git_write") as writes:
                    with self.assertRaisesRegex(RuntimeError, "第 17 步"):
                        run(run_dir, state)
                writes.assert_not_called()
                self.assertEqual(read_state(run_dir), state)
                self.assertFalse((run_dir / "steps/requirements/BR-001/18.json").exists())

    def test_mismatched_commit_repositories_are_rejected_before_git_writes(self) -> None:
        for field, value in (
            ("name", "other"),
            ("path", "other"),
            ("base_sha", "0" * 40),
            ("tip_sha", "0" * 40),
            ("missing", None),
            ("extra", None),
            ("order", None),
        ):
            with self.subTest(conflicting_field=field):
                run_dir, _workspace, state, _repositories, _bases, _tips = self.make_run(["web"])
                commit_path = run_dir / "steps/requirements/BR-001/17.json"
                commit_result = json.loads(commit_path.read_text(encoding="utf-8"))
                repositories = commit_result["repositories"]
                if field == "missing":
                    repositories.pop()
                elif field == "extra":
                    repositories.append(dict(repositories[0]))
                elif field == "order":
                    repositories.reverse()
                else:
                    repositories[0][field] = value
                write_requirement_step_result(run_dir, "BR-001", 17, commit_result)
                with patch.object(merge_step, "_git_write") as writes:
                    with self.assertRaisesRegex(RuntimeError, "第 17 步"):
                        run(run_dir, state)
                writes.assert_not_called()
                self.assertEqual(read_state(run_dir), state)
                self.assertFalse((run_dir / "steps/requirements/BR-001/18.json").exists())

    def test_commit_display_fields_do_not_block_merge(self) -> None:
        for metadata in (
            {"name": "提交结果", "summary": "", "outputs": ["commit-report.json"]},
            {},
        ):
            with self.subTest(metadata=metadata):
                run_dir, _workspace, state, repositories, _bases, tips = self.make_run(["web"])
                commit_path = run_dir / "steps/requirements/BR-001/17.json"
                commit_result = json.loads(commit_path.read_text(encoding="utf-8"))
                for field in ("name", "summary", "outputs"):
                    commit_result.pop(field)
                commit_result.update(metadata)
                write_requirement_step_result(run_dir, "BR-001", 17, commit_result)

                run(run_dir, state)

                self.assert_final(repositories, tips)
                final = read_state(run_dir)
                self.assertEqual(final["requirement_registry"]["requirements"][0]["status"], "completed")
                self.assertIsNone(final["active_requirement"])
                self.assertIsNone(final["requirement_cycle"])

    def test_upstream_incremental_fields_do_not_block_merge(self) -> None:
        run_dir, _workspace, state, repositories, _bases, tips = self.make_run(["web"])
        state["requirement_cycle"]["repositories"]["root"]["note"] = "upstream metadata"
        commit_path = run_dir / "steps/requirements/BR-001/17.json"
        commit_result = json.loads(commit_path.read_text(encoding="utf-8"))
        commit_result["evidence"] = {"source": "step17"}
        commit_result["repositories"][0]["commit_count"] = 1
        write_requirement_step_result(run_dir, "BR-001", 17, commit_result)
        write_state(run_dir, state)

        run(run_dir, state)

        self.assert_final(repositories, tips)

    def test_unsafe_git_states_fail_without_repair(self) -> None:
        for case in ("dirty", "in_progress", "detached", "wrong_branch", "non_fast_forward", "main_ahead"):
            with self.subTest(case=case):
                run_dir, _workspace, state, repositories, _bases, tips = self.make_run()
                repository = repositories["root"]
                if case == "dirty":
                    (repository / "untracked.txt").write_text("dirty\n", encoding="utf-8")
                elif case == "in_progress":
                    git_dir = Path(command("rev-parse", "--git-dir", cwd=repository))
                    if not git_dir.is_absolute():
                        git_dir = repository / git_dir
                    (git_dir / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="ascii")
                elif case == "detached":
                    command("checkout", "--detach", cwd=repository)
                elif case == "wrong_branch":
                    command("switch", "-c", "other", cwd=repository)
                elif case == "main_ahead":
                    command("switch", "main", cwd=repository)
                    command("merge", "--ff-only", tips["root"], cwd=repository)
                    (repository / "later.txt").write_text("later\n", encoding="utf-8")
                    commit_all(repository, "main ahead")
                    command("switch", "req/br-001", cwd=repository)
                else:
                    command("switch", "main", cwd=repository)
                    (repository / "other.txt").write_text("other\n", encoding="utf-8")
                    commit_all(repository, "main diverges")
                with self.assertRaisesRegex(RuntimeError, "root"):
                    run(run_dir, state)
                self.assertFalse((run_dir / "steps/requirements/BR-001/18.json").exists())

    def test_git_environment_is_filtered_and_writes_are_whitelisted(self) -> None:
        run_dir, _workspace, state, _repositories, _bases, _tips = self.make_run(["web"])
        original = merge_step.subprocess.run
        environments: list[dict[str, str]] = []
        commands: list[tuple[str, ...]] = []

        def inspected(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            command_args = tuple(args[0])
            if command_args and command_args[0] == "git":
                environments.append(kwargs["env"])
                commands.append(command_args[1:])
            return original(*args, **kwargs)

        previous = {key: os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE")}
        os.environ["GIT_DIR"] = "/not/a/repository"
        os.environ["GIT_WORK_TREE"] = "/not/a/worktree"
        try:
            with patch.object(merge_step.subprocess, "run", side_effect=inspected):
                run(run_dir, state)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertTrue(environments)
        self.assertTrue(
            all(not any(key.startswith("GIT_") for key in environment) for environment in environments)
        )
        writes = [
            args
            for args in commands
            if args[0] in {"switch", "merge"} or args[:2] == ("branch", "-d")
        ]
        self.assertTrue(writes)
        self.assertTrue(
            all(
                args == ("switch", "main")
                or (len(args) == 3 and args[:2] == ("merge", "--ff-only"))
                or (len(args) == 3 and args[:2] == ("branch", "-d"))
                for args in writes
            )
        )
        with self.assertRaisesRegex(RuntimeError, "不允许"):
            merge_step._git_write(self.root, "reset", "--hard")


if __name__ == "__main__":
    unittest.main()
