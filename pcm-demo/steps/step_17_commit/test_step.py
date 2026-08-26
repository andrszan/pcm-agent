from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.state import read_state, write_requirement_step_result, write_state
from steps.step_17_commit.step import (
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    REPOSITORY_REPAIR_PROMPT,
    STEP,
    _working_tree_fingerprint,
    result,
    run,
)


def command(*args: str, cwd: Path, check: bool = True) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=check
    ).stdout.strip()


def commit_all(repository: Path, message: str = "test commit") -> str:
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


def empty_commit(repository: Path) -> str:
    command(
        "-c",
        "user.name=PCM Test",
        "-c",
        "user.email=pcm@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "empty",
        cwd=repository,
    )
    return command("rev-parse", "HEAD", cwd=repository)


def init_update(cwd: Path, session: str = "commit-session-1") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": ["commit-changes"],
            "slash_commands": ["commit-changes"],
        },
        text="",
        result_subtype=None,
        is_error=False,
        session_id=session,
        stop_reason=None,
        num_turns=None,
        total_cost_usd=None,
        exception=None,
    )


def agent_result(cwd: Path, session: str = "commit-session-1") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": ["commit-changes"],
            "slash_commands": ["commit-changes"],
        },
        text="已完成提交。",
        result_subtype="success",
        is_error=False,
        session_id=session,
        stop_reason="end_turn",
        num_turns=1,
        total_cost_usd=0.1,
        exception=None,
    )


def completed_decision() -> tuple[dict, int, str]:
    data = {
        "verdict": "completed",
        "answer": "",
        "reason": "提交已完成",
        "required_inputs": [],
    }
    return data, 1, json.dumps(data, ensure_ascii=False)


class RequirementCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_run(self, children: list[str]) -> tuple[Path, Path, dict, dict[str, str]]:
        run_dir = self.root / "run"
        (run_dir / "steps/requirements/BR-001").mkdir(parents=True)
        workspace_root = self.root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)

        repositories: list[tuple[str, Path]] = [("root", workspace)]
        for name in children:
            child = workspace / name
            child.mkdir()
            repositories.append((name, child))

        bases: dict[str, str] = {}
        for name, repository in repositories:
            command("init", "-b", "main", cwd=repository)
            (repository / "base.txt").write_text(f"{name} base\n", encoding="utf-8")
            bases[name] = commit_all(repository, "base")
            command("switch", "-c", "req/br-001", cwd=repository)
        if children:
            exclude = workspace / ".git/info/exclude"
            with exclude.open("a", encoding="utf-8") as file:
                for name in children:
                    file.write(f"{name}/\n")

        names = [name for name, _ in repositories]
        state = {
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {
                "root": str(workspace_root.resolve()),
                "final_path": str(workspace.resolve()),
            },
            "applicable_repositories": names,
            "repositories": [
                {
                    "name": name,
                    "path": str(repository.resolve()),
                    "branch": "main",
                    "worktree_clean": True,
                }
                for name, repository in repositories
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
                    name: {"base_sha": bases[name]} for name in names
                },
                "trd_path": "docs/trd/BR-001.md",
                "development_session_id": "development-session-1",
                "return_node_after_completion": "phase_1:select_requirement",
            },
            "blocked": None,
            "error": None,
        }
        write_requirement_step_result(
            run_dir,
            "BR-001",
            16,
            {
                "step": 16,
                "name": "规则复盘",
                "status": "success",
                "summary": "已完成。",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "requirement_id": "BR-001",
                "development_session_id": "development-session-1",
            },
        )
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
            repository = workspace if name == "root" else workspace / name
            commit_all(repository, f"feat: {name} change")

    def run_step(self, run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    def test_all_clean_dynamic_repositories_skip_agent_without_empty_commits(self) -> None:
        for children in ([], ["web"], ["web", "api"]):
            with self.subTest(children=children):
                self.tearDown()
                self.setUp()
                run_dir, workspace, state, bases = self.make_run(children)
                calls: list[object] = []

                async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                    calls.append((args, kwargs))
                    raise AssertionError("全 clean 不应调用 Agent")

                saved = self.run_step(
                    run_dir,
                    state,
                    agent_runner=unexpected,
                    decision_runner=unexpected,
                )

                self.assertEqual(calls, [])
                self.assertEqual([item["name"] for item in saved["repositories"]], ["root", *children])
                self.assertTrue(
                    all(item["tip_sha"] == bases[item["name"]] for item in saved["repositories"])
                )
                completed = read_state(run_dir)
                self.assertEqual((completed["step"], completed["current_node"]), (18, NEXT_NODE))
                self.assertTrue(
                    all(
                        value["merged"] is False
                        for value in completed["requirement_cycle"]["repositories"].values()
                    )
                )
                self.assertEqual(command("branch", "--show-current", cwd=workspace), "req/br-001")

    def test_dirty_repositories_use_one_product_root_session(self) -> None:
        run_dir, workspace, state, bases = self.make_run(["web", "api"])
        names = ["root", "web", "api"]
        self.dirty(workspace, names)
        calls: list[dict] = []

        async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            kwargs["on_update"](init_update(kwargs["cwd"]))  # type: ignore[index,operator,arg-type]
            self.commit_names(workspace, names)
            return agent_result(kwargs["cwd"])  # type: ignore[arg-type,index]

        async def completed(messages, config, *, system_prompt):
            return completed_decision()

        saved = self.run_step(
            run_dir,
            state,
            agent_runner=fake_agent,
            decision_runner=completed,
            config_loader=lambda: object(),
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["cwd"].resolve(), workspace.resolve())
        self.assertIsNone(calls[0]["resume_session_id"])
        self.assertEqual(calls[0]["prompt"].count("/commit-changes"), 1)
        for name in names:
            self.assertIn(f"- {name}:", calls[0]["prompt"])
        completed_state = read_state(run_dir)
        self.assertEqual(completed_state["current_node"], NEXT_NODE)
        for repository in saved["repositories"]:
            self.assertEqual(repository["base_sha"], bases[repository["name"]])
            self.assertNotEqual(repository["tip_sha"], repository["base_sha"])

    def test_clean_repository_stays_at_base_while_dirty_repository_commits(self) -> None:
        run_dir, workspace, state, bases = self.make_run(["web"])
        self.dirty(workspace, ["root"])

        async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
            kwargs["on_update"](init_update(kwargs["cwd"]))  # type: ignore[index,operator,arg-type]
            self.commit_names(workspace, ["root"])
            return agent_result(kwargs["cwd"])  # type: ignore[arg-type,index]

        async def completed(messages, config, *, system_prompt):
            return completed_decision()

        saved = self.run_step(
            run_dir,
            state,
            agent_runner=fake_agent,
            decision_runner=completed,
            config_loader=lambda: object(),
        )
        evidence = {item["name"]: item for item in saved["repositories"]}
        self.assertNotEqual(evidence["root"]["tip_sha"], bases["root"])
        self.assertEqual(evidence["web"]["tip_sha"], bases["web"])

    def test_completed_with_dirty_repair_resumes_same_session(self) -> None:
        run_dir, workspace, state, _ = self.make_run([])
        self.dirty(workspace, ["root"])
        calls: list[dict] = []

        async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            kwargs["on_update"](init_update(kwargs["cwd"]))  # type: ignore[index,operator,arg-type]
            if len(calls) == 2:
                self.commit_names(workspace, ["root"])
            return agent_result(kwargs["cwd"])  # type: ignore[arg-type,index]

        async def completed(messages, config, *, system_prompt):
            return completed_decision()

        self.run_step(
            run_dir,
            state,
            agent_runner=fake_agent,
            decision_runner=completed,
            config_loader=lambda: object(),
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["prompt"], REPOSITORY_REPAIR_PROMPT)
        self.assertEqual(calls[1]["resume_session_id"], "commit-session-1")
        self.assertNotIn("/commit-changes", calls[1]["prompt"])

    def test_partial_multi_repository_commit_recovers_same_session(self) -> None:
        run_dir, workspace, state, _ = self.make_run(["web"])
        self.dirty(workspace, ["root", "web"])

        async def interrupted(prompt: str, **kwargs: object) -> ClaudeRunResult:
            kwargs["on_update"](init_update(kwargs["cwd"]))  # type: ignore[index,operator,arg-type]
            self.commit_names(workspace, ["root"])
            raise OSError("simulated disconnect")

        with self.assertRaisesRegex(RuntimeError, "Agent SDK 执行异常"):
            self.run_step(
                run_dir,
                state,
                agent_runner=interrupted,
                decision_runner=lambda *args, **kwargs: None,
                config_loader=lambda: object(),
            )

        resumed_calls: list[dict] = []

        async def resumed(prompt: str, **kwargs: object) -> ClaudeRunResult:
            resumed_calls.append({"prompt": prompt, **kwargs})
            self.commit_names(workspace, ["web"])
            return agent_result(kwargs["cwd"])  # type: ignore[arg-type,index]

        async def completed(messages, config, *, system_prompt):
            return completed_decision()

        saved = self.run_step(
            run_dir,
            read_state(run_dir),
            agent_runner=resumed,
            decision_runner=completed,
            config_loader=lambda: object(),
        )
        self.assertEqual(len(resumed_calls), 1)
        self.assertEqual(resumed_calls[0]["resume_session_id"], "commit-session-1")
        self.assertNotEqual(saved["repositories"][0]["tip_sha"], saved["repositories"][0]["base_sha"])
        self.assertNotEqual(saved["repositories"][1]["tip_sha"], saved["repositories"][1]["base_sha"])

    def test_clean_repository_empty_commit_is_rejected(self) -> None:
        run_dir, workspace, state, _ = self.make_run(["web"])
        self.dirty(workspace, ["root"])

        async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
            kwargs["on_update"](init_update(kwargs["cwd"]))  # type: ignore[index,operator,arg-type]
            self.commit_names(workspace, ["root"])
            empty_commit(workspace / "web")
            return agent_result(kwargs["cwd"])  # type: ignore[arg-type,index]

        async def completed(messages, config, *, system_prompt):
            return completed_decision()

        with self.assertRaisesRegex(RuntimeError, "完成核验失败"):
            self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )

    def test_clean_filter_normalization_preserves_valid_commit(self) -> None:
        run_dir, workspace, state, _ = self.make_run([])
        command("config", "filter.upper.clean", "tr a-z A-Z", cwd=workspace)
        command("config", "filter.upper.smudge", "cat", cwd=workspace)
        (workspace / ".gitattributes").write_text(
            "filtered.txt filter=upper\n", encoding="utf-8"
        )
        (workspace / "filtered.txt").write_text("lowercase\n", encoding="utf-8")

        async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
            kwargs["on_update"](init_update(kwargs["cwd"]))  # type: ignore[index,operator,arg-type]
            commit_all(workspace, "feat: filtered content")
            return agent_result(kwargs["cwd"])  # type: ignore[arg-type,index]

        async def completed(messages, config, *, system_prompt):
            return completed_decision()

        saved = self.run_step(
            run_dir,
            state,
            agent_runner=fake_agent,
            decision_runner=completed,
            config_loader=lambda: object(),
        )
        self.assertEqual(saved["status"], "success")
        blob = command("show", "HEAD:filtered.txt", cwd=workspace)
        self.assertEqual(blob, "LOWERCASE")

    def test_discarding_initial_change_and_committing_replacement_is_rejected(self) -> None:
        run_dir, workspace, state, _ = self.make_run([])
        self.dirty(workspace, ["root"])

        async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
            kwargs["on_update"](init_update(kwargs["cwd"]))  # type: ignore[index,operator,arg-type]
            (workspace / "root-change.txt").unlink()
            (workspace / "replacement.txt").write_text("replacement\n", encoding="utf-8")
            commit_all(workspace, "feat: replacement")
            return agent_result(kwargs["cwd"])  # type: ignore[arg-type,index]

        async def completed(messages, config, *, system_prompt):
            return completed_decision()

        with self.assertRaisesRegex(RuntimeError, "完成核验失败"):
            self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )

    def test_completed_merge_commit_is_rejected(self) -> None:
        run_dir, workspace, state, bases = self.make_run([])
        self.dirty(workspace, ["root"])

        async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
            kwargs["on_update"](init_update(kwargs["cwd"]))  # type: ignore[index,operator,arg-type]
            tree = command("rev-parse", f"{bases['root']}^{{tree}}", cwd=workspace)
            side = command(
                "-c",
                "user.name=PCM Test",
                "-c",
                "user.email=pcm@example.invalid",
                "commit-tree",
                tree,
                "-p",
                bases["root"],
                "-m",
                "side",
                cwd=workspace,
            )
            command("branch", "side", side, cwd=workspace)
            commit_all(workspace, "feat: account access")
            command(
                "-c",
                "user.name=PCM Test",
                "-c",
                "user.email=pcm@example.invalid",
                "merge",
                "--no-ff",
                "side",
                "-m",
                "merge side",
                cwd=workspace,
            )
            return agent_result(kwargs["cwd"])  # type: ignore[arg-type,index]

        async def completed(messages, config, *, system_prompt):
            return completed_decision()

        with self.assertRaisesRegex(RuntimeError, "完成核验失败"):
            self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )

    def test_success_result_recovers_state_without_agent(self) -> None:
        run_dir, workspace, state, bases = self.make_run([])
        self.dirty(workspace, ["root"])
        state["requirement_commit_BR-001"] = {
            "repositories": [
                {
                    "name": "root",
                    "dirty": True,
                    "tree_sha256": _working_tree_fingerprint(workspace),
                }
            ]
        }
        commit_all(workspace, "feat: account access")
        tip = command("rev-parse", "HEAD", cwd=workspace)
        saved = result(
            "success",
            "已完成。",
            requirement_id="BR-001",
            branch="req/br-001",
            repositories=[
                {
                    "name": "root",
                    "path": ".",
                    "base_sha": bases["root"],
                    "tip_sha": tip,
                }
            ],
        )
        write_requirement_step_result(run_dir, "BR-001", STEP, saved)
        write_state(run_dir, state)

        async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
            raise AssertionError("result→state 恢复不应调用 Agent")

        recovered = self.run_step(
            run_dir,
            read_state(run_dir),
            agent_runner=unexpected,
            decision_runner=unexpected,
        )
        self.assertEqual(recovered, saved)
        self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_advanced_success_is_idempotent_without_git_or_agent(self) -> None:
        run_dir, workspace, state, _ = self.make_run([])
        self.dirty(workspace, ["root"])

        async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
            kwargs["on_update"](init_update(kwargs["cwd"]))  # type: ignore[index,operator,arg-type]
            self.commit_names(workspace, ["root"])
            return agent_result(kwargs["cwd"])  # type: ignore[arg-type,index]

        async def completed(messages, config, *, system_prompt):
            return completed_decision()

        first = self.run_step(
            run_dir,
            state,
            agent_runner=fake_agent,
            decision_runner=completed,
            config_loader=lambda: object(),
        )
        before_state = (run_dir / "state.json").read_bytes()
        before_result = (run_dir / "steps/requirements/BR-001/17.json").read_bytes()
        workspace.rename(workspace.with_name("project-moved"))

        async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
            raise AssertionError("推进后幂等不应调用 Agent")

        second = self.run_step(
            run_dir,
            read_state(run_dir),
            agent_runner=unexpected,
            decision_runner=unexpected,
        )
        self.assertEqual(second, first)
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)
        self.assertEqual((run_dir / "steps/requirements/BR-001/17.json").read_bytes(), before_result)


if __name__ == "__main__":
    unittest.main()
