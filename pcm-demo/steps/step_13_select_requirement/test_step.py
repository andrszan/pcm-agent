from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.files import write_json
from common.state import (
    read_state,
    requirement_step_result_path,
    write_requirement_step_result,
    write_state,
)
from steps.step_13_select_requirement.step import (
    CURRENT_NODE,
    NEXT_NODE,
    NoPendingRequirements,
    PHASE,
    STEP,
    _select,
    run,
)
import steps.step_13_select_requirement.step as selection_step


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=check
    )


def commit(repository: Path, message: str = "test commit") -> None:
    git("add", "-A", cwd=repository)
    git(
        "-c",
        "user.name=PCM Test",
        "-c",
        "user.email=pcm@example.invalid",
        "commit",
        "-m",
        message,
        cwd=repository,
    )


class SelectRequirementTests(unittest.TestCase):
    @staticmethod
    def catalog() -> list[dict]:
        return [
            {"id": "REQ-001", "title": "账户", "order": 1, "depends_on": []},
            {"id": "REQ-002", "title": "订单", "order": 2, "depends_on": ["REQ-001"]},
            {"id": "REQ-003", "title": "通知", "order": 3, "depends_on": []},
        ]

    @staticmethod
    def source() -> dict:
        return {
            "path": "docs/backlog/backlog.md",
            "sha256": "a" * 64,
            "root_main_sha": "b" * 40,
        }

    def make_run(
        self,
        root: Path,
        names: list[str] | None = None,
        requirements: list[dict] | None = None,
    ) -> tuple[Path, list[dict], dict]:
        names = names or ["root", "frontend", "backend"]
        requirements = requirements or [
            {**item, "status": "pending", "completion": None} for item in self.catalog()
        ]
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace = root / "workspace"
        workspace.mkdir()
        repositories: list[dict] = []
        for name in names:
            repository = workspace if name == "root" else workspace / name
            repository.mkdir(exist_ok=True)
            (repository / "README.md").write_text(f"{name}\n", encoding="utf-8")
            git("init", "-b", "main", cwd=repository)
            commit(repository)
            if name != "root":
                with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
                    exclude.write(f"{name}/\n")
            repositories.append(
                {
                    "name": name,
                    "path": str(repository.resolve()),
                    "branch": "main",
                    "worktree_clean": True,
                }
            )
        write_json(
            run_dir / "steps/08.json",
            {
                "step": 8,
                "name": "首次提交适用仓库",
                "status": "success",
                "summary": "全部仓库已提交。",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "applicable_repositories": names,
                "repositories": [
                    {
                        "name": name,
                        "path": "." if name == "root" else name,
                        "branch": "main",
                        "worktree_clean": True,
                    }
                    for name in names
                ],
            },
        )
        write_json(
            run_dir / "steps/12.json",
            {
                "step": 12,
                "name": "解析 Backlog 并初始化需求注册表",
                "status": "success",
                "summary": "已初始化。",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "source": self.source(),
                "requirement_catalog": self.catalog(),
            },
        )
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(root.resolve()), "final_path": str(workspace.resolve())},
            "applicable_repositories": names,
            "repositories": repositories,
            "requirement_registry": {
                "schema_version": 1,
                "source": self.source(),
                "requirements": requirements,
            },
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, repositories, state

    def test_selects_lowest_ready_requirement_and_creates_dynamic_repository_branches(self) -> None:
        requirements = [
            {**self.catalog()[0], "status": "completed", "completion": {"step": 18}},
            {**self.catalog()[1], "status": "pending", "completion": None},
            {**self.catalog()[2], "status": "pending", "completion": None},
        ]
        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(
                Path(directory), ["root", "backend", "frontend"], requirements
            )
            saved = run(run_dir, state)

            self.assertEqual((saved["requirement_id"], saved["branch"]), ("REQ-002", "req/req-002"))
            self.assertEqual([item["name"] for item in saved["repositories"]], ["root", "backend", "frontend"])
            self.assertEqual([item["path"] for item in saved["repositories"]], [".", "backend", "frontend"])
            self.assertEqual(saved["outputs"], [])
            self.assertFalse((run_dir / "steps/13.json").exists())
            self.assertTrue((run_dir / "steps/requirements/REQ-002/13.json").is_file())
            completed = read_state(run_dir)
            self.assertEqual(
                (completed["step"], completed["current_step"], completed["current_node"]),
                (14, 14, NEXT_NODE),
            )
            self.assertEqual(completed["active_requirement"], "REQ-002")
            self.assertEqual(completed["requirement_registry"]["requirements"][1]["status"], "active")
            self.assertEqual(
                set(completed["requirement_cycle"]["repositories"]),
                {"root", "backend", "frontend"},
            )
            for repository in repositories:
                path = Path(repository["path"])
                self.assertEqual(git("branch", "--show-current", cwd=path).stdout.strip(), "req/req-002")
                self.assertEqual(git("status", "--porcelain=v1", cwd=path).stdout, "")

    def test_active_dependencies_are_not_treated_as_completed(self) -> None:
        requirements = [
            {"id": "REQ-001", "order": 1, "depends_on": [], "status": "active"},
            {"id": "REQ-002", "order": 2, "depends_on": ["REQ-001"], "status": "pending"},
        ]
        with self.assertRaisesRegex(RuntimeError, "没有依赖已完成"):
            _select(requirements)

    def test_fresh_preflight_failure_leaves_state_and_all_repositories_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            (Path(repositories[1]["path"]) / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "fresh"):
                run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            for repository in repositories:
                path = Path(repository["path"])
                self.assertEqual(git("branch", "--show-current", cwd=path).stdout.strip(), "main")
                self.assertFalse(git("show-ref", "--verify", "refs/heads/req/req-001", cwd=path, check=False).returncode == 0)

    def test_fresh_branch_collision_is_not_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            root = Path(repositories[0]["path"])
            git("branch", "req/req-001", cwd=root)
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "fresh"):
                run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            self.assertEqual(git("branch", "--show-current", cwd=root).stdout.strip(), "main")
            self.assertEqual(git("branch", "--show-current", cwd=Path(repositories[1]["path"])).stdout.strip(), "main")

    def test_fresh_rejects_non_main_symlink_and_unborn_repositories_without_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            git("switch", "-c", "other", cwd=Path(repositories[0]["path"]))
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaises(RuntimeError):
                run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            root = Path(repositories[0]["path"])
            root_link = Path(directory) / "root-link"
            root_link.symlink_to(root, target_is_directory=True)
            state["repositories"][0]["path"] = str(root_link)
            write_state(run_dir, state)
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaises(RuntimeError):
                run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            root = Path(repositories[0]["path"])
            shutil.rmtree(root / ".git")
            git("init", "-b", "main", cwd=root)
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "Git"):
                run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

    def test_recovery_rejects_wrong_target_base_and_third_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            bases = {
                repository["name"]: git("rev-parse", "HEAD", cwd=Path(repository["path"])).stdout.strip()
                for repository in repositories
            }
            root = Path(repositories[0]["path"])
            git("switch", "-c", "req/req-001", cwd=root)
            (root / "later.txt").write_text("later\n", encoding="utf-8")
            commit(root, "later")
            state["active_requirement"] = "REQ-001"
            state["requirement_registry"]["requirements"][0]["status"] = "active"
            state["requirement_cycle"] = {
                "requirement_id": "REQ-001",
                "branch": "req/req-001",
                "repositories": {name: {"base_sha": base} for name, base in bases.items()},
                "return_node_after_completion": CURRENT_NODE,
            }
            write_state(run_dir, state)
            with self.assertRaisesRegex(RuntimeError, "不指向记录基线"):
                run(run_dir, state)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            bases = {
                repository["name"]: git("rev-parse", "HEAD", cwd=Path(repository["path"])).stdout.strip()
                for repository in repositories
            }
            root = Path(repositories[0]["path"])
            git("branch", "req/req-001", cwd=root)
            git("switch", "-c", "other", cwd=root)
            state["active_requirement"] = "REQ-001"
            state["requirement_registry"]["requirements"][0]["status"] = "active"
            state["requirement_cycle"] = {
                "requirement_id": "REQ-001",
                "branch": "req/req-001",
                "repositories": {name: {"base_sha": base} for name, base in bases.items()},
                "return_node_after_completion": CURRENT_NODE,
            }
            write_state(run_dir, state)
            with self.assertRaisesRegex(RuntimeError, "不在 main 或记录的需求分支"):
                run(run_dir, state)

    def test_handoff_rejects_requirement_ids_that_cannot_form_scoped_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _repositories, state = self.make_run(Path(directory))
            invalid_catalog = [
                {"id": "REQ.001", "title": "账户", "order": 1, "depends_on": []},
                *self.catalog()[1:],
            ]
            write_json(
                run_dir / "steps/12.json",
                {
                    "step": 12,
                    "name": "解析 Backlog 并初始化需求注册表",
                    "status": "success",
                    "summary": "已初始化。",
                    "applicable": True,
                    "outputs": [],
                    "blocked": None,
                    "error": None,
                    "source": self.source(),
                    "requirement_catalog": invalid_catalog,
                },
            )
            before = (run_dir / "state.json").read_bytes()
            with patch.object(selection_step.subprocess, "run", side_effect=AssertionError("不得调用 Git")):
                with self.assertRaisesRegex(RuntimeError, "第 12 步"):
                    run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

    def test_workspace_descriptor_must_match_the_recorded_workspace_before_git_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _repositories, state = self.make_run(Path(directory))
            external = Path(directory) / "external"
            external.mkdir()
            (external / "README.md").write_text("external\n", encoding="utf-8")
            git("init", "-b", "main", cwd=external)
            commit(external)
            state["repositories"][0]["path"] = str(external.resolve())
            write_state(run_dir, state)
            before = (run_dir / "state.json").read_bytes()
            with patch.object(selection_step.subprocess, "run", side_effect=AssertionError("不得调用 Git")):
                with self.assertRaisesRegex(RuntimeError, "仓库描述"):
                    run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

    def test_completed_requirement_requires_a_non_null_completion(self) -> None:
        requirements = [
            {**self.catalog()[0], "status": "completed", "completion": None},
            *[{**item, "status": "pending", "completion": None} for item in self.catalog()[1:]],
        ]
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _repositories, state = self.make_run(Path(directory), requirements=requirements)
            before = (run_dir / "state.json").read_bytes()
            with patch.object(selection_step.subprocess, "run", side_effect=AssertionError("不得调用 Git")):
                with self.assertRaisesRegex(RuntimeError, "动态字段"):
                    run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

    def test_in_progress_merge_is_rejected_before_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            root = Path(repositories[0]["path"])
            git("switch", "-c", "feature", cwd=root)
            (root / "feature.txt").write_text("feature\n", encoding="utf-8")
            commit(root, "feature")
            git("switch", "main", cwd=root)
            (root / "main.txt").write_text("main\n", encoding="utf-8")
            commit(root, "main")
            git("merge", "--no-commit", "feature", cwd=root)
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "未完成"):
                run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

    def test_partial_branch_creation_recovers_from_recorded_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            original_recover = selection_step._recover_branch
            calls = 0

            def interrupt_after_first(*args: object, **kwargs: object) -> None:
                nonlocal calls
                calls += 1
                original_recover(*args, **kwargs)
                if calls == 1:
                    raise OSError("simulated interruption")

            with patch.object(selection_step, "_recover_branch", side_effect=interrupt_after_first):
                with self.assertRaises(OSError):
                    run(run_dir, state)
            interrupted = read_state(run_dir)
            self.assertEqual(interrupted["active_requirement"], "REQ-001")
            self.assertEqual(interrupted["step"], 13)
            self.assertEqual(git("branch", "--show-current", cwd=Path(repositories[0]["path"])).stdout.strip(), "req/req-001")
            self.assertEqual(run(run_dir, interrupted)["status"], "success")
            for repository in repositories:
                self.assertEqual(
                    git("branch", "--show-current", cwd=Path(repository["path"])).stdout.strip(),
                    "req/req-001",
                )

    def test_failed_scoped_result_is_overwritten_by_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _repositories, state = self.make_run(Path(directory))
            original_recover = selection_step._recover_branch
            calls = 0

            def interrupt_after_first(*args: object, **kwargs: object) -> None:
                nonlocal calls
                calls += 1
                original_recover(*args, **kwargs)
                if calls == 1:
                    raise OSError("simulated interruption")

            with patch.object(selection_step, "_recover_branch", side_effect=interrupt_after_first):
                with self.assertRaises(OSError):
                    run(run_dir, state)
            interrupted = read_state(run_dir)
            write_requirement_step_result(
                run_dir,
                "REQ-001",
                STEP,
                {"status": "failed", "error": {"message": "simulated"}},
            )
            saved = run(run_dir, interrupted)
            self.assertEqual(saved["status"], "success")
            self.assertEqual(
                read_state(run_dir)["current_node"],
                NEXT_NODE,
            )

    def test_recovery_switches_an_exact_recorded_branch_from_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            bases = {
                repository["name"]: git("rev-parse", "HEAD", cwd=Path(repository["path"])).stdout.strip()
                for repository in repositories
            }
            for repository in repositories:
                git("branch", "req/req-001", cwd=Path(repository["path"]))
            state["active_requirement"] = "REQ-001"
            state["requirement_registry"]["requirements"][0]["status"] = "active"
            state["requirement_cycle"] = {
                "requirement_id": "REQ-001",
                "branch": "req/req-001",
                "repositories": {name: {"base_sha": base} for name, base in bases.items()},
                "return_node_after_completion": CURRENT_NODE,
            }
            write_state(run_dir, state)
            run(run_dir, state)
            for repository in repositories:
                self.assertEqual(
                    git("branch", "--show-current", cwd=Path(repository["path"])).stdout.strip(),
                    "req/req-001",
                )

    def test_saved_result_recovers_state_without_git_write_and_advanced_state_is_byte_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _repositories, state = self.make_run(Path(directory))
            original_write_state = selection_step.write_state

            def interrupt_advance(path: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("simulated state interruption")
                original_write_state(path, value)

            with patch.object(selection_step, "write_state", side_effect=interrupt_advance):
                with self.assertRaises(OSError):
                    run(run_dir, state)
            interrupted = read_state(run_dir)
            self.assertTrue((run_dir / "steps/requirements/REQ-001/13.json").is_file())
            with patch.object(selection_step.subprocess, "run", wraps=subprocess.run) as mocked:
                run(run_dir, interrupted)
            self.assertFalse(any(call.args[0][1] == "switch" for call in mocked.call_args_list))
            advanced = read_state(run_dir)
            result_bytes = (run_dir / "steps/requirements/REQ-001/13.json").read_bytes()
            state_bytes = (run_dir / "state.json").read_bytes()
            with patch.object(selection_step.subprocess, "run", side_effect=AssertionError("不得调用 Git")):
                run(run_dir, advanced)
            self.assertEqual((run_dir / "steps/requirements/REQ-001/13.json").read_bytes(), result_bytes)
            self.assertEqual((run_dir / "state.json").read_bytes(), state_bytes)

    def test_saved_success_refuses_tampered_branch_before_advancing_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, repositories, state = self.make_run(Path(directory))
            original_write_state = selection_step.write_state

            def interrupt_advance(path: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("simulated state interruption")
                original_write_state(path, value)

            with patch.object(selection_step, "write_state", side_effect=interrupt_advance):
                with self.assertRaises(OSError):
                    run(run_dir, state)
            interrupted = read_state(run_dir)
            root = Path(repositories[0]["path"])
            git("switch", "main", cwd=root)
            with self.assertRaisesRegex(RuntimeError, "需求分支"):
                run(run_dir, interrupted)
            self.assertEqual(read_state(run_dir)["current_node"], CURRENT_NODE)

    def test_no_pending_leaves_the_entry_state_and_result_store_unchanged(self) -> None:
        requirements = [
            {**item, "status": "completed", "completion": {"step": 18}}
            for item in self.catalog()
        ]
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _repositories, state = self.make_run(Path(directory), requirements=requirements)
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaises(NoPendingRequirements):
                run(run_dir, state)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            self.assertFalse((run_dir / "steps/requirements").exists())

    def test_requirement_result_paths_reject_traversal_and_symlink_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            (run_dir / "steps").mkdir(parents=True)
            for identifier in ("", " BR-001", "BR-001 ", "../BR-001", "BR/001", ".", ".."):
                with self.subTest(identifier=identifier):
                    with self.assertRaises(ValueError):
                        requirement_step_result_path(run_dir, identifier, STEP)
            external = Path(directory) / "external"
            external.mkdir()
            (run_dir / "steps/requirements").symlink_to(external, target_is_directory=True)
            with self.assertRaises(ValueError):
                write_requirement_step_result(run_dir, "BR-001", STEP, {"status": "success"})

    def test_requirement_result_write_does_not_follow_a_legacy_temporary_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            result_path = run_dir / "steps/requirements/REQ-001/13.json"
            result_path.parent.mkdir(parents=True)
            external = Path(directory) / "external.json"
            external.write_text("unchanged\n", encoding="utf-8")
            result_path.with_name(".13.json.tmp").symlink_to(external)
            write_requirement_step_result(run_dir, "REQ-001", STEP, {"status": "success"})
            self.assertEqual(external.read_text(encoding="utf-8"), "unchanged\n")
            self.assertEqual(
                json.loads(result_path.read_text(encoding="utf-8")),
                {"status": "success"},
            )

    def test_production_git_commands_use_only_the_selection_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _repositories, state = self.make_run(Path(directory), ["root", "frontend"])
            with (
                patch.dict(
                    selection_step.os.environ,
                    {
                        "GIT_DIR": str(Path(directory) / "redirected-git-dir"),
                        "GIT_INDEX_FILE": str(Path(directory) / "redirected-index"),
                    },
                ),
                patch.object(selection_step.subprocess, "run", wraps=subprocess.run) as mocked,
            ):
                run(run_dir, state)
            commands = [tuple(call.args[0][1:]) for call in mocked.call_args_list]
            self.assertTrue(
                all(
                    "env" in call.kwargs
                    and not any(key.startswith("GIT_") for key in call.kwargs["env"])
                    for call in mocked.call_args_list
                )
            )
            allowed = {"rev-parse", "branch", "status", "show-ref", "check-ref-format", "switch"}
            self.assertTrue(commands)
            self.assertTrue(all(command[0] in allowed for command in commands))
            self.assertIn(("rev-parse", "-q", "--verify", "MERGE_HEAD"), commands)
            self.assertIn(("rev-parse", "--git-path", "rebase-merge"), commands)
            self.assertTrue(
                all(
                    command[0] != "switch" or command[1:3] == ("-c", "req/req-001")
                    for command in commands
                )
            )
            self.assertFalse({"add", "commit", "merge", "push", "fetch", "reset", "checkout", "clean"} & {item[0] for item in commands})


if __name__ == "__main__":
    unittest.main()
