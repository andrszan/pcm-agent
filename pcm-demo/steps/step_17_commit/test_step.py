from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.state import read_state, write_requirement_step_result, write_state
from steps.step_17_commit.step import (
    CURRENT_NODE,
    MAX_BUDGET_USD,
    MAX_TURNS,
    NEXT_NODE,
    PHASE,
    STEP,
    result,
    run,
)


def command(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def commit_all(repository: Path, message: str = "test commit") -> str:
    command("add", "-A", cwd=repository)
    command("-c", "user.name=PCM Test", "-c", "user.email=pcm@example.invalid", "commit", "-m", message, cwd=repository)
    return command("rev-parse", "HEAD", cwd=repository)


def claude_result(session: str | None, *, subtype: str | None = "success", is_error: bool = False, has_errors: bool = False) -> ClaudeRunResult:
    return ClaudeRunResult(
        init=None,
        text="",
        result_subtype=subtype,
        is_error=is_error,
        session_id=session,
        stop_reason=None,
        num_turns=None,
        total_cost_usd=None,
        exception=None,
        has_errors=has_errors,
    )


class RequirementCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_run(self, children: list[str] = []) -> tuple[Path, Path, dict[str, Any], dict[str, str]]:
        run_dir = self.root / "run"
        (run_dir / "steps/requirements/BR-001").mkdir(parents=True)
        workspace_root, workspace = self.root / "workspace-root", self.root / "workspace-root/project"
        workspace.mkdir(parents=True)
        repositories = [("root", workspace), *[(name, workspace / name) for name in children]]
        for _name, repository in repositories[1:]:
            repository.mkdir()
        bases = {}
        for name, repository in repositories:
            command("init", "-b", "main", cwd=repository)
            (repository / "base.txt").write_text(f"{name} base\n", encoding="utf-8")
            bases[name] = commit_all(repository, "base")
            command("switch", "-c", "req/br-001", cwd=repository)
        if children:
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as file:
                for name in children:
                    file.write(f"{name}/\n")
        names = [name for name, _repository in repositories]
        state: dict[str, Any] = {
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "applicable_repositories": names,
            "repositories": [{"name": name, "path": str(repository)} for name, repository in repositories],
            "requirement_registry": {"schema_version": 1, "requirements": [{"id": "BR-001", "title": "账户访问", "order": 1, "depends_on": [], "status": "active", "completion": None}]},
            "active_requirement": "BR-001",
            "requirement_cycle": {
                "requirement_id": "BR-001",
                "branch": "req/br-001",
                "repositories": {name: {"base_sha": bases[name]} for name in names},
                "trd_path": "docs/trd/BR-001.md",
                "development_session_id": "development-session-1",
                "return_node_after_completion": "phase_1:select_requirement",
            },
            "blocked": None,
            "error": None,
        }
        write_requirement_step_result(run_dir, "BR-001", 16, {
            "step": 16, "name": "规则复盘", "status": "success", "summary": "已完成。", "applicable": True,
            "outputs": [], "blocked": None, "error": None, "requirement_id": "BR-001", "development_session_id": "development-session-1",
        })
        write_state(run_dir, state)
        return run_dir, workspace, state, bases

    @staticmethod
    def dirty(workspace: Path, names: list[str]) -> None:
        for name in names:
            repository = workspace if name == "root" else workspace / name
            (repository / f"{name}-change.txt").write_text("changed\n", encoding="utf-8")

    @staticmethod
    def commit_names(workspace: Path, names: list[str]) -> None:
        for name in names:
            commit_all(workspace if name == "root" else workspace / name, f"feat: {name}")

    @staticmethod
    def success(requirement_id: str, branch: str, bases: dict[str, str], tips: dict[str, str]) -> dict[str, Any]:
        return result("success", "已完成。", requirement_id=requirement_id, branch=branch, repositories=[
            {"name": name, "path": "." if name == "root" else name, "base_sha": bases[name], "tip_sha": tips[name]}
            for name in bases
        ])

    @staticmethod
    def execute(run_dir: Path, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return asyncio.run(run(run_dir, state, **kwargs))

    def test_all_clean_skips_agent(self) -> None:
        run_dir, _workspace, state, bases = self.make_run(["web"])
        calls: list[object] = []

        async def unexpected(*args: Any, **kwargs: Any) -> ClaudeRunResult:
            calls.append((args, kwargs))
            raise AssertionError("全 clean 不应调用 Agent")

        saved = self.execute(run_dir, state, agent_runner=unexpected)
        self.assertEqual(calls, [])
        self.assertEqual([item["tip_sha"] for item in saved["repositories"]], [bases["root"], bases["web"]])
        self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_dirty_repositories_use_one_product_root_call_and_save_session(self) -> None:
        run_dir, workspace, state, _bases = self.make_run(["web", "api"])
        self.dirty(workspace, ["root", "web", "api"])
        calls: list[dict[str, Any]] = []

        async def agent(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            kwargs["on_update"](claude_result("commit-session-1", subtype=None))
            self.commit_names(workspace, ["root", "web", "api"])
            return claude_result("commit-session-1")

        self.execute(run_dir, state, agent_runner=agent)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["cwd"].resolve(), workspace.resolve())
        self.assertIsNone(calls[0]["resume_session_id"])
        self.assertEqual(calls[0]["max_turns"], MAX_TURNS)
        self.assertEqual(calls[0]["max_budget_usd"], MAX_BUDGET_USD)
        self.assertTrue(calls[0]["prompt"].startswith("/commit-changes\n"))
        self.assertEqual(calls[0]["prompt"].count("/commit-changes"), 1)
        self.assertEqual(read_state(run_dir)["claude_sessions"]["requirement_commit_BR-001"], "commit-session-1")

    def test_exception_after_init_resumes_same_session_once_without_slash(self) -> None:
        run_dir, workspace, state, _bases = self.make_run(["web"])
        self.dirty(workspace, ["root", "web"])

        async def interrupted(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            kwargs["on_update"](claude_result("commit-session-1", subtype=None))
            self.commit_names(workspace, ["root"])
            raise OSError("disconnect")

        with self.assertRaisesRegex(RuntimeError, "Claude Agent 执行异常"):
            self.execute(run_dir, state, agent_runner=interrupted)

        calls: list[dict[str, Any]] = []
        async def resumed(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            self.commit_names(workspace, ["web"])
            return claude_result("commit-session-1")

        self.execute(run_dir, read_state(run_dir), agent_runner=resumed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["resume_session_id"], "commit-session-1")
        self.assertNotIn("/commit-changes", calls[0]["prompt"])

    def test_dirty_normal_return_fails_then_resumes_successfully(self) -> None:
        run_dir, workspace, state, _bases = self.make_run()
        self.dirty(workspace, ["root"])

        async def incomplete(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            kwargs["on_update"](claude_result("commit-session-1", subtype=None))
            return claude_result("commit-session-1")

        with self.assertRaisesRegex(RuntimeError, "需求提交未完成"):
            self.execute(run_dir, state, agent_runner=incomplete)
        write_requirement_step_result(run_dir, "BR-001", STEP, result("failed", "未完成。", requirement_id="BR-001", branch="req/br-001", error={"type": "RuntimeError", "message": "未完成"}))
        calls: list[dict[str, Any]] = []

        async def resumed(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            self.commit_names(workspace, ["root"])
            return claude_result("commit-session-1")

        self.execute(run_dir, read_state(run_dir), agent_runner=resumed)
        self.assertEqual(calls[0]["resume_session_id"], "commit-session-1")
        self.assertNotIn("/commit-changes", calls[0]["prompt"])

    def test_non_normal_clean_result_must_resume_before_success(self) -> None:
        run_dir, workspace, state, _bases = self.make_run()
        self.dirty(workspace, ["root"])

        async def failed(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            kwargs["on_update"](claude_result("commit-session-1", subtype=None))
            self.commit_names(workspace, ["root"])
            return claude_result(
                "commit-session-1", subtype="error", is_error=True, has_errors=True
            )

        with self.assertRaisesRegex(RuntimeError, "需求提交未完成"):
            self.execute(run_dir, state, agent_runner=failed)

        calls: list[dict[str, Any]] = []

        async def resumed(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            return claude_result("commit-session-1")

        saved = self.execute(run_dir, read_state(run_dir), agent_runner=resumed)
        self.assertEqual(saved["status"], "success")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["resume_session_id"], "commit-session-1")
        self.assertNotIn("/commit-changes", calls[0]["prompt"])

    def test_untracked_files_are_dirty_even_when_repository_config_hides_them(self) -> None:
        run_dir, workspace, state, _bases = self.make_run()
        command("config", "status.showUntrackedFiles", "no", cwd=workspace)
        self.dirty(workspace, ["root"])
        calls = 0

        async def agent(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            nonlocal calls
            calls += 1
            kwargs["on_update"](claude_result("commit-session-1", subtype=None))
            self.commit_names(workspace, ["root"])
            return claude_result("commit-session-1")

        self.execute(run_dir, state, agent_runner=agent)
        self.assertEqual(calls, 1)

    def test_symlinked_repository_path_is_rejected(self) -> None:
        run_dir, workspace, state, _bases = self.make_run(["web"])
        external = self.root / "outside-web"
        (workspace / "web").rename(external)
        (workspace / "web").symlink_to(external, target_is_directory=True)

        async def unexpected(*args: Any, **kwargs: Any) -> ClaudeRunResult:
            raise AssertionError("符号链接仓库不应调用 Agent")

        with self.assertRaisesRegex(RuntimeError, "适用仓库描述"):
            self.execute(run_dir, state, agent_runner=unexpected)

    def test_boundary_conflict_rejects_before_agent(self) -> None:
        run_dir, _workspace, state, _bases = self.make_run()
        state["requirement_cycle"]["repositories"]["root"]["base_sha"] = "0" * 40

        async def unexpected(*args: Any, **kwargs: Any) -> ClaudeRunResult:
            raise AssertionError("边界冲突不应调用 Agent")

        with self.assertRaisesRegex(RuntimeError, "Git 边界"):
            self.execute(run_dir, state, agent_runner=unexpected)

    def test_success_result_recovers_state_without_agent(self) -> None:
        run_dir, workspace, state, bases = self.make_run()
        self.dirty(workspace, ["root"])
        tip = commit_all(workspace, "feat: account access")
        saved = self.success("BR-001", "req/br-001", bases, {"root": tip})
        write_requirement_step_result(run_dir, "BR-001", STEP, saved)
        write_state(run_dir, state)

        async def unexpected(*args: Any, **kwargs: Any) -> ClaudeRunResult:
            raise AssertionError("result→state 恢复不应调用 Agent")

        self.assertEqual(self.execute(run_dir, read_state(run_dir), agent_runner=unexpected), saved)
        self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_advanced_success_preserves_legacy_artifacts_without_workspace(self) -> None:
        run_dir, workspace, state, bases = self.make_run()
        saved = self.success("BR-001", "req/br-001", bases, bases)
        state.update({"status": "success", "step": STEP + 1, "current_step": STEP + 1, "current_node": NEXT_NODE})
        state["requirement_cycle"]["repositories"] = {"root": {"base_sha": bases["root"], "tip_sha": bases["root"], "merged": False}}
        state["requirement_commit_BR-001"] = {"repositories": [{"tree_sha256": "a" * 64}]}
        state["decision_conversations"] = {"requirement_commit_BR-001": {"path": "conversations/old.json"}}
        state["claude_sessions"] = {"requirement_commit_BR-001": "commit-session-1"}
        write_requirement_step_result(run_dir, "BR-001", STEP, saved)
        write_state(run_dir, state)
        before_state = (run_dir / "state.json").read_bytes()
        before_result = (run_dir / "steps/requirements/BR-001/17.json").read_bytes()
        workspace.rename(workspace.with_name("workspace-moved"))

        async def unexpected(*args: Any, **kwargs: Any) -> ClaudeRunResult:
            raise AssertionError("推进后幂等不应调用 Agent")

        self.assertEqual(self.execute(run_dir, read_state(run_dir), agent_runner=unexpected), saved)
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)
        self.assertEqual((run_dir / "steps/requirements/BR-001/17.json").read_bytes(), before_result)


if __name__ == "__main__":
    unittest.main()
