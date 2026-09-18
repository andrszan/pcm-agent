from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.agent_decision_loop import BLOCKED_RESUME_PROMPT
from common.claude_agent import ClaudeRunResult
from common.decision import render_decision_system_prompt
from common.files import write_json
from common.state import read_state, write_state
from model_policy import get_agent_profile
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_08_initialize_repositories.step import (
    CURRENT_NODE,
    INITIALIZE_REPOSITORIES_DECISION_RULES,
    INITIALIZE_REPOSITORIES_MAX_TURNS,
    NEXT_NODE,
    REPOSITORY_REPAIR_PROMPT,
    InitializeRepositoriesBlocked,
    run,
)
import steps.step_08_initialize_repositories.step as initialize_step


def command(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


def commit_all(repository: Path, message: str = "test commit") -> None:
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


def agent_result(*, cwd: Path, text: str = "已处理", session: str = "session-1") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={"cwd": str(cwd), "skills": ["commit-changes"], "slash_commands": ["commit-changes"]},
        text=text,
        result_subtype="success",
        is_error=False,
        session_id=session,
        stop_reason="end_turn",
        num_turns=1,
        total_cost_usd=0.1,
        exception=None,
    )


def decision(
    verdict: str,
    *,
    answer: str = "",
    reason: str = "已核验",
    required_inputs: list[str] | None = None,
) -> tuple[dict, int, str]:
    data = {
        "verdict": verdict,
        "answer": answer,
        "reason": reason,
        "required_inputs": required_inputs or [],
    }
    return data, 1, json.dumps(data, ensure_ascii=False)


@contextmanager
def isolated_git_environment(root: Path):
    home = root / "home"
    home.mkdir()
    global_config = home / ".gitconfig"
    global_config.write_text(
        "[user]\n\tname = Global User\n\temail = global@example.com\n"
        "[commit]\n\tgpgsign = false\n",
        encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        GIT_CONFIG_GLOBAL=str(global_config),
        GIT_CONFIG_NOSYSTEM="1",
    )
    with patch.dict(os.environ, env, clear=True):
        yield global_config


class InitializeRepositoriesTests(unittest.TestCase):
    def make_run(self, root: Path, outputs: list[str]) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)
        initialize_root_repository(workspace)
        for name in outputs:
            child = workspace / name
            child.mkdir()
            initialize_root_repository(child)
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
                exclude.write(f"{name}/\n")
        write_json(
            run_dir / "steps/04.json",
            {"step": 4, "status": "success", "applicable": bool(outputs), "outputs": outputs},
        )
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": "project_initialization",
            "step": 8,
            "current_step": 8,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    def run_step(self, run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    @staticmethod
    def dirty(workspace: Path, names: list[str]) -> None:
        for name in names:
            repository = workspace if name == "root" else workspace / name
            (repository / f"{name}-change.txt").write_text("changed\n", encoding="utf-8")

    @staticmethod
    def commit_repositories(workspace: Path, names: list[str]) -> None:
        for name in names:
            commit_all(workspace if name == "root" else workspace / name)

    def test_root_only_and_multiple_clean_repositories_succeed_without_agent(self) -> None:
        for outputs in ([], ["frontend", "backend"]):
            with self.subTest(outputs=outputs), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), outputs)
                calls: list[object] = []

                async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                    calls.append((args, kwargs))
                    raise AssertionError("干净仓库不应调用 Agent")

                saved = self.run_step(
                    run_dir,
                    state,
                    agent_runner=unexpected,
                    decision_runner=unexpected,
                )

                names = ["root", *outputs]
                self.assertEqual(calls, [])
                self.assertEqual(saved["applicable_repositories"], names)
                self.assertNotIn("initial_commits", saved)
                self.assertEqual([item["name"] for item in saved["repositories"]], names)
                self.assertTrue(all(item["worktree_clean"] for item in saved["repositories"]))
                self.assertEqual([item["path"] for item in saved["repositories"]], [".", *outputs])
                completed_state = read_state(run_dir)
                self.assertEqual((completed_state["step"], completed_state["current_node"]), (9, NEXT_NODE))
                self.assertEqual(
                    [item["name"] for item in completed_state["repositories"]], names
                )
                self.assertTrue(
                    all(Path(item["path"]).is_absolute() for item in completed_state["repositories"])
                )
                self.assertNotIn("claude_sessions", completed_state)
                self.assertNotIn("decision_conversations", completed_state)
                self.assertEqual(
                    workspace.resolve(), Path(completed_state["repositories"][0]["path"])
                )

    def test_project_identity_controls_real_commits_without_changing_global_or_other_repositories(self) -> None:
        for name, email in (("rulefolio", "rulefolio@example.com"), ("规则研发团队", "team@example.com")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with isolated_git_environment(root) as global_config:
                    original_global = global_config.read_bytes()
                    run_dir, workspace, state = self.make_run(root, ["frontend", "backend"])
                    state["git_identity"] = {"name": name, "email": email}
                    write_state(run_dir, state)
                    names = ["root", "frontend", "backend"]
                    self.dirty(workspace, names)
                    outside = root / "other-project"
                    outside.mkdir()
                    initialize_root_repository(outside)
                    outside_config = (outside / ".git/config").read_bytes()

                    async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                        for repository_name in names:
                            repository = workspace if repository_name == "root" else workspace / repository_name
                            command("add", "-A", cwd=repository)
                            command("commit", "-m", "首次提交", cwd=repository)
                        value = agent_result(cwd=workspace)
                        kwargs["on_update"](value)
                        return value

                    async def completed(messages, config, *, system_prompt):
                        return decision("completed")

                    saved = self.run_step(
                        run_dir, state, agent_runner=fake_agent,
                        decision_runner=completed, config_loader=lambda: object(),
                    )
                    self.assertEqual(saved["status"], "success")
                    expected = f"{name}|{email}|{name}|{email}"
                    for repository_name in names:
                        repository = workspace if repository_name == "root" else workspace / repository_name
                        self.assertEqual(command("config", "--local", "user.name", cwd=repository), name)
                        self.assertEqual(command("config", "--local", "user.email", cwd=repository), email)
                        self.assertEqual(command("log", "-1", "--format=%an|%ae|%cn|%ce", cwd=repository), expected)
                        (repository / "later.txt").write_text("后续开发\n", encoding="utf-8")
                        command("add", "later.txt", cwd=repository)
                        command("commit", "-m", "后续提交", cwd=repository)
                        self.assertEqual(command("log", "-1", "--format=%an|%ae|%cn|%ce", cwd=repository), expected)
                    self.assertEqual(global_config.read_bytes(), original_global)
                    self.assertEqual((outside / ".git/config").read_bytes(), outside_config)
                    self.assertEqual(command("config", "user.name", cwd=outside), "Global User")
                    self.assertEqual(command("config", "user.email", cwd=outside), "global@example.com")

    def test_clean_new_repositories_receive_identity_and_retries_are_idempotent(self) -> None:
        for outputs in ([], ["frontend"], ["frontend", "backend"]):
            with self.subTest(outputs=outputs), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with isolated_git_environment(root):
                    run_dir, workspace, state = self.make_run(root, outputs)
                    state["git_identity"] = {"name": "rulefolio", "email": "rulefolio@example.com"}
                    write_state(run_dir, state)

                    async def unexpected(*args: object, **kwargs: object):
                        raise AssertionError("干净仓库不应调用模型")

                    for _ in range(2):
                        self.assertEqual(self.run_step(
                            run_dir, dict(state), agent_runner=unexpected, decision_runner=unexpected,
                        )["status"], "success")
                    for repository in [workspace, *(workspace / name for name in outputs)]:
                        self.assertEqual(command("config", "--local", "--get-all", "user.name", cwd=repository), "rulefolio")
                        self.assertEqual(command("config", "--local", "--get-all", "user.email", cwd=repository), "rulefolio@example.com")

    def test_legacy_run_keeps_existing_repository_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root) as global_config:
                run_dir, workspace, state = self.make_run(root, ["frontend", "backend"])
                originals = {}
                for repository in (workspace, workspace / "frontend", workspace / "backend"):
                    command("config", "--local", "user.name", "Existing User", cwd=repository)
                    command("config", "--local", "user.email", "existing@example.com", cwd=repository)
                    originals[repository] = (repository / ".git/config").read_bytes()
                global_bytes = global_config.read_bytes()
                self.run_step(run_dir, state)
                self.assertNotIn("git_identity", read_state(run_dir))
                self.assertEqual(global_config.read_bytes(), global_bytes)
                for repository, original in originals.items():
                    self.assertEqual((repository / ".git/config").read_bytes(), original)

    def test_invalid_saved_identity_fails_before_config_or_agent(self) -> None:
        for identity in (None, {}, {"name": "rulefolio"}, {"name": "rulefolio", "email": "bad"}):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with isolated_git_environment(root):
                    run_dir, workspace, state = self.make_run(root, [])
                    state["git_identity"] = identity
                    original = (workspace / ".git/config").read_bytes()
                    with self.assertRaisesRegex(RuntimeError, "Git 提交身份"):
                        self.run_step(run_dir, state)
                    self.assertEqual((workspace / ".git/config").read_bytes(), original)

    def test_effective_author_and_committer_overrides_fail_before_agent(self) -> None:
        overrides = (
            {"GIT_AUTHOR_NAME": "Another Author"},
            {"GIT_AUTHOR_EMAIL": "another@example.com"},
            {"GIT_COMMITTER_NAME": "Another Committer"},
            {"GIT_COMMITTER_EMAIL": "another@example.com"},
        )
        for override in overrides:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with isolated_git_environment(root):
                    run_dir, workspace, state = self.make_run(root, [])
                    state["git_identity"] = {"name": "rulefolio", "email": "rulefolio@example.com"}
                    self.dirty(workspace, ["root"])
                    with patch.dict(os.environ, override):
                        with self.assertRaisesRegex(RuntimeError, "实际提交身份"):
                            self.run_step(run_dir, state)
                    self.assertFalse((run_dir / "conversations").exists())
                    self.assertNotEqual(subprocess.run(
                        ["git", "rev-parse", "--verify", "HEAD"], cwd=workspace,
                        capture_output=True,
                    ).returncode, 0)

    def test_author_specific_global_config_is_not_silently_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root) as global_config:
                with global_config.open("a", encoding="utf-8") as stream:
                    stream.write("[author]\n\tname = Another Author\n")
                original = global_config.read_bytes()
                run_dir, _workspace, state = self.make_run(root, [])
                state["git_identity"] = {"name": "rulefolio", "email": "rulefolio@example.com"}
                with self.assertRaisesRegex(RuntimeError, "实际提交身份"):
                    self.run_step(run_dir, state)
                self.assertEqual(global_config.read_bytes(), original)

    def test_configuration_failure_stops_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root, [])
                state["git_identity"] = {"name": "rulefolio", "email": "rulefolio@example.com"}
                original = (workspace / ".git/config").read_bytes()
                (workspace / ".git/config.lock").touch()
                with self.assertRaisesRegex(RuntimeError, "无法配置仓库本地 Git 提交身份"):
                    self.run_step(run_dir, state)
                self.assertEqual((workspace / ".git/config").read_bytes(), original)
                self.assertFalse((run_dir / "conversations").exists())

    def test_repository_boundaries_are_checked_before_any_identity_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root, [])
                state["git_identity"] = {"name": "rulefolio", "email": "rulefolio@example.com"}
                (workspace / "frontend").mkdir()
                write_json(run_dir / "steps/04.json", {
                    "step": 4, "status": "success", "outputs": ["frontend"],
                })
                original = (workspace / ".git/config").read_bytes()
                with self.assertRaisesRegex(RuntimeError, "顶层目录"):
                    self.run_step(run_dir, state)
                self.assertEqual((workspace / ".git/config").read_bytes(), original)

    def test_dirty_repositories_use_one_product_root_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend", "backend"])
            names = ["root", "frontend", "backend"]
            self.dirty(workspace, names)
            calls: list[dict] = []
            decision_prompts: list[str] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                self.commit_repositories(workspace, names)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                decision_prompts.append(system_prompt)
                return decision("completed")

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
            self.assertEqual(calls[0]["max_turns"], INITIALIZE_REPOSITORIES_MAX_TURNS)
            profile = get_agent_profile("initialize_repositories")
            self.assertEqual(calls[0]["task"], "initialize_repositories")
            self.assertEqual(
                (calls[0]["model"], calls[0]["effort"]),
                (profile.model, profile.effort),
            )
            self.assertNotIn("max_budget_usd", calls[0])
            self.assertTrue(calls[0]["prompt"].startswith("/commit-changes\n"))
            repository_references = [
                f"@./{'.' if name == 'root' else name}" for name in names
            ]
            self.assertEqual(
                [part for part in calls[0]["prompt"].split() if part.startswith("@./")],
                repository_references,
            )
            self.assertEqual(len(decision_prompts), 1)
            self.assertEqual(
                decision_prompts[0],
                render_decision_system_prompt(
                    INITIALIZE_REPOSITORIES_DECISION_RULES,
                    {"有序仓库": [
                        {"name": name, "path": str((workspace if name == "root" else workspace / name).resolve())}
                        for name in names
                    ]},
                ),
            )
            self.assertEqual(saved["applicable_repositories"], names)
            self.assertNotIn("initial_commits", read_state(run_dir))

    def test_completed_with_dirty_repair_continues_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            names = ["root", "frontend"]
            self.dirty(workspace, names)
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    self.commit_repositories(workspace, names)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )

            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["prompt"], REPOSITORY_REPAIR_PROMPT)
            self.assertEqual(calls[1]["resume_session_id"], "session-1")

    def test_blocked_after_agent_clean_state_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            self.dirty(workspace, ["root"])
            calls = 0

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                nonlocal calls
                calls += 1
                commit_all(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def blocked(messages, config, *, system_prompt):
                return decision("blocked", reason="等待外部输入", required_inputs=["外部输入"])

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=blocked,
                config_loader=lambda: object(),
            )

            self.assertEqual(calls, 1)
            self.assertEqual(saved["status"], "success")
            self.assertEqual(read_state(run_dir)["status"], "success")

    def test_blocked_dirty_state_is_saved_and_resumes_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            self.dirty(workspace, ["root"])
            calls: list[dict] = []
            decisions = ["blocked", "completed"]

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    commit_all(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def decide(messages, config, *, system_prompt):
                verdict = decisions.pop(0)
                if verdict == "blocked":
                    return decision("blocked", reason="等待授权", required_inputs=["授权"])
                return decision("completed")

            with self.assertRaises(InitializeRepositoriesBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            blocked_state = read_state(run_dir)
            self.assertEqual(blocked_state["status"], "blocked")
            self.assertEqual(blocked_state["claude_sessions"]["initialize_repositories"], "session-1")
            self.assertEqual(json.loads((run_dir / "steps/08.json").read_text(encoding="utf-8"))["status"], "blocked")

            saved = self.run_step(
                run_dir,
                blocked_state,
                agent_runner=fake_agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls[1]["prompt"], BLOCKED_RESUME_PROMPT)
            self.assertEqual(calls[1]["resume_session_id"], "session-1")

    def test_failed_state_with_dirty_workspace_resumes_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            self.dirty(workspace, ["root"])
            state.update(
                {
                    "status": "failed",
                    "claude_sessions": {"initialize_repositories": "session-1"},
                    "decision_conversations": {
                        "initialize_repositories": {
                            "path": "conversations/initialize_repositories.json"
                        }
                    },
                }
            )
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/initialize_repositories.json",
                {"messages": [{"role": "system", "content": "测试 system"}]},
            )
            write_state(run_dir, state)
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                commit_all(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(calls[0]["resume_session_id"], "session-1")

    def test_dirty_blocked_recovery_requires_original_session_and_conversation(self) -> None:
        for missing in ("session", "conversation"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), [])
                self.dirty(workspace, ["root"])
                state.update(
                    {
                        "status": "blocked",
                        "blocked": {
                            "reason": "等待授权",
                            "required_inputs": ["授权"],
                            "applicable_repositories": ["root"],
                        },
                    }
                )
                if missing != "session":
                    state["claude_sessions"] = {
                        "initialize_repositories": "session-1"
                    }
                if missing != "conversation":
                    state["decision_conversations"] = {
                        "initialize_repositories": {
                            "path": "conversations/initialize_repositories.json"
                        }
                    }
                    (run_dir / "conversations").mkdir()
                    write_json(
                        run_dir / "conversations/initialize_repositories.json",
                        {"messages": [{"role": "system", "content": "测试 system"}]},
                    )
                write_state(run_dir, state)

                async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("恢复锚点缺失时不得启动新 Agent session")

                with self.assertRaisesRegex(RuntimeError, "缺少原"):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=unexpected,
                        decision_runner=unexpected,
                    )

    def test_dirty_blocked_recovery_requires_blocked_decision_tail(self) -> None:
        for history in ("system-only", "completed", "invalid-json"):
            with self.subTest(history=history), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), [])
                self.dirty(workspace, ["root"])
                state.update(
                    {
                        "status": "blocked",
                        "claude_sessions": {
                            "initialize_repositories": "session-1"
                        },
                        "decision_conversations": {
                            "initialize_repositories": {
                                "path": "conversations/initialize_repositories.json"
                            }
                        },
                        "blocked": {
                            "reason": "等待授权",
                            "required_inputs": ["授权"],
                            "applicable_repositories": ["root"],
                        },
                    }
                )
                conversations = run_dir / "conversations"
                conversations.mkdir()
                history_path = conversations / "initialize_repositories.json"
                if history == "invalid-json":
                    history_path.write_text("{invalid", encoding="utf-8")
                else:
                    messages = [{"role": "system", "content": "测试 system"}]
                    if history == "completed":
                        messages.append(
                            {
                                "role": "assistant",
                                "content": json.dumps(
                                    decision("completed")[0], ensure_ascii=False
                                ),
                            }
                        )
                    write_json(history_path, {"messages": messages})
                write_state(run_dir, state)

                async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("无效 blocked 历史不得恢复 Agent")

                with self.assertRaisesRegex(RuntimeError, "blocked 决策"):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=unexpected,
                        decision_runner=unexpected,
                    )

    def test_blocked_recovery_reads_clean_workspace_before_resuming(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            self.dirty(workspace, ["root"])
            blocked = {
                "reason": "等待授权",
                "required_inputs": ["授权"],
                "applicable_repositories": ["root"],
            }
            state.update(
                {
                    "status": "blocked",
                    "claude_sessions": {"initialize_repositories": "session-1"},
                    "blocked": blocked,
                }
            )
            write_state(run_dir, state)
            commit_all(workspace)

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("已清理的 blocked 恢复不应调用 Agent")

            saved = self.run_step(run_dir, state, agent_runner=unexpected, decision_runner=unexpected)
            self.assertEqual(saved["status"], "success")
            self.assertEqual(read_state(run_dir)["status"], "success")

    def test_clean_recovery_closes_existing_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            self.dirty(workspace, ["root"])
            relative_path = "conversations/initialize_repositories.json"
            state.update(
                {
                    "status": "failed",
                    "claude_sessions": {"initialize_repositories": "session-1"},
                    "decision_conversations": {
                        "initialize_repositories": {"path": relative_path}
                    },
                }
            )
            write_state(run_dir, state)
            conversation_path = run_dir / relative_path
            conversation_path.parent.mkdir()
            write_json(
                conversation_path,
                {
                    "messages": [
                        {"role": "system", "content": "测试 system"},
                        {"role": "assistant", "content": "执行提交"},
                        {"role": "user", "content": "尚未提交"},
                        {
                            "role": "assistant",
                            "content": json.dumps(
                                decision("continue", answer="继续提交")[0],
                                ensure_ascii=False,
                            ),
                        },
                    ]
                },
            )
            commit_all(workspace)

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("已清理的恢复不应调用 Agent 或负责人")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )

            self.assertEqual(saved["status"], "success")
            messages = json.loads(conversation_path.read_text(encoding="utf-8"))["messages"]
            completion = json.loads(messages[-1]["content"])
            self.assertEqual(completion["verdict"], "completed")
            self.assertEqual(completion["answer"], "")
            self.assertEqual(completion["required_inputs"], [])
            self.assertIn("PCM 确定性恢复核验", completion["reason"])

    def test_step_nine_success_refuses_later_dirty_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("干净仓库不应调用 Agent")

            self.run_step(run_dir, state, agent_runner=unexpected, decision_runner=unexpected)
            self.dirty(workspace, ["root"])
            with self.assertRaisesRegex(RuntimeError, "成功后权威仓库出现未提交修改"):
                self.run_step(run_dir, read_state(run_dir), agent_runner=unexpected, decision_runner=unexpected)

    def test_top_level_and_branch_fail_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            self.dirty(workspace, ["root"])

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("无效仓库不应调用 Agent")

            original_git_read = initialize_step._git_read

            def wrong_top_level(path: Path, *args: str) -> str:
                if args == ("rev-parse", "--show-toplevel"):
                    return str(path.parent)
                return original_git_read(path, *args)

            with patch.object(initialize_step, "_git_read", side_effect=wrong_top_level):
                with self.assertRaisesRegex(RuntimeError, "顶层目录"):
                    self.run_step(run_dir, state, agent_runner=unexpected)

            command("switch", "-c", "feature", cwd=workspace)
            with self.assertRaisesRegex(RuntimeError, "分支不是 main"):
                self.run_step(run_dir, state, agent_runner=unexpected)

    def test_unborn_and_multiple_commit_clean_repositories_are_legal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("干净仓库不应调用 Agent")

            self.assertEqual(
                self.run_step(run_dir, state, agent_runner=unexpected, decision_runner=unexpected)["status"],
                "success",
            )

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            (workspace / "one.txt").write_text("one\n", encoding="utf-8")
            commit_all(workspace, "first")
            (workspace / "two.txt").write_text("two\n", encoding="utf-8")
            commit_all(workspace, "second")
            self.assertEqual(
                self.run_step(run_dir, state, agent_runner=unexpected, decision_runner=unexpected)["status"],
                "success",
            )

    def test_result_write_interruption_recovers_from_clean_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            self.dirty(workspace, ["root"])
            calls = 0

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                nonlocal calls
                calls += 1
                commit_all(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            original_write_state = initialize_step.write_state

            def interrupt_final_state(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("模拟状态写入中断")
                original_write_state(target, value)

            with patch.object(initialize_step, "write_state", side_effect=interrupt_final_state):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=fake_agent,
                        decision_runner=completed,
                        config_loader=lambda: object(),
                    )
            self.assertTrue((run_dir / "steps/08.json").is_file())
            interrupted = read_state(run_dir)

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("清理后的重试不应调用 Agent")

            self.assertEqual(
                self.run_step(run_dir, interrupted, agent_runner=unexpected, decision_runner=unexpected)["status"],
                "success",
            )
            self.assertEqual(calls, 1)

    def test_legacy_success_is_normalized_when_workspace_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            write_json(
                run_dir / "steps/08.json",
                {
                    "step": 8,
                    "status": "success",
                    "initial_commits": {"root": "a" * 40},
                    "repositories": [{"name": "root", "head": "a" * 40}],
                },
            )

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("干净旧成功记录不应调用 Agent")

            state["initial_commits"] = {"root": "a" * 40}
            write_state(run_dir, state)
            saved = self.run_step(run_dir, state, agent_runner=unexpected, decision_runner=unexpected)
            self.assertNotIn("initial_commits", saved)
            self.assertEqual(set(saved["repositories"][0]), {"name", "path", "branch", "worktree_clean"})
            stored = json.loads((run_dir / "steps/08.json").read_text(encoding="utf-8"))
            self.assertNotIn("initial_commits", stored)
            self.assertEqual(stored, saved)
            normalized_state = read_state(run_dir)
            self.assertNotIn("initial_commits", normalized_state)
            self.assertEqual(Path(normalized_state["repositories"][0]["path"]), workspace.resolve())

    def test_step_four_outputs_are_the_ordered_authoritative_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["backend", "frontend"])

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("干净仓库不应调用 Agent")

            saved = self.run_step(run_dir, state, agent_runner=unexpected, decision_runner=unexpected)
            self.assertEqual(saved["applicable_repositories"], ["root", "backend", "frontend"])

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), [])
            write_json(run_dir / "steps/04.json", {"step": 4, "status": "success", "outputs": ["mobile"]})
            with self.assertRaisesRegex(RuntimeError, "第 4 步"):
                self.run_step(run_dir, state)

    def test_production_git_reads_use_only_the_allowlisted_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _run_dir, workspace, _state = self.make_run(Path(directory), ["frontend"])
            with patch.object(initialize_step.subprocess, "run", wraps=subprocess.run) as mocked:
                repositories = initialize_step._repository_facts(workspace, ["root", "frontend"])

            self.assertTrue(all(item["worktree_clean"] for item in repositories))
            commands = [tuple(call.args[0][1:]) for call in mocked.call_args_list]
            self.assertEqual(
                commands,
                [
                    ("rev-parse", "--show-toplevel"),
                    ("branch", "--show-current"),
                    ("status", "--porcelain"),
                ]
                * 2,
            )

    def test_cli_success_fixture_uses_the_new_schema(self) -> None:
        import run_step as cli

        with tempfile.TemporaryDirectory() as directory:
            demo_root = Path(directory)
            run_dir = demo_root / "runs" / "step-eight-new-schema-test"
            (run_dir / "steps").mkdir(parents=True)
            successful_state = {
                "status": "success",
                "phase": "project_initialization",
                "step": 9,
                "current_step": 9,
                "current_node": NEXT_NODE,
                "blocked": None,
                "error": None,
            }
            write_state(run_dir, successful_state)
            fixture = initialize_step.result(
                "success",
                "已完成",
                applicable_repositories=["root"],
                repositories=[
                    {
                        "name": "root",
                        "path": ".",
                        "branch": "main",
                        "worktree_clean": True,
                    }
                ],
            )
            write_json(run_dir / "steps/08.json", fixture)
            args = Namespace(
                step=8,
                product_draft=None,
                workspace_root=None,
                catalog_path=None,
                run_id=run_dir.name,
            )
            for attempt in range(2):
                with self.subTest(attempt=attempt):
                    with (
                        patch.object(cli, "DEMO_ROOT", demo_root),
                        patch.object(cli, "parse_args", return_value=args),
                        patch.object(
                            cli, "run_step_eight", side_effect=OSError("模拟中断")
                        ),
                    ):
                        self.assertEqual(cli.main(), 1)
                preserved = json.loads(
                    (run_dir / "steps/08.json").read_text(encoding="utf-8")
                )
                self.assertEqual(preserved, fixture)
                self.assertEqual(read_state(run_dir), successful_state)
                self.assertNotIn("initial_commits", preserved)


if __name__ == "__main__":
    unittest.main()
