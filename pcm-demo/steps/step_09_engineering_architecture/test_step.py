from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.agent_decision_loop import BLOCKED_RESUME_PROMPT
from common.claude_agent import ClaudeRunResult
from common.files import write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_05_project_readiness.step import (
    readiness_baseline,
    result as readiness_result,
)
from steps.step_09_engineering_architecture.step import (
    ARCHITECTURE_PATH,
    CONVERSATION_KEY,
    CURRENT_NODE,
    NEXT_NODE,
    EngineeringArchitectureBlocked,
    architecture_repair,
    run,
)
import steps.step_09_engineering_architecture.step as architecture_step


def command(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    )


def commit_paths(repository: Path, *paths: str) -> None:
    command("add", "--", *paths, cwd=repository)
    if command("status", "--porcelain=v1", cwd=repository).stdout:
        command(
            "-c",
            "user.name=PCM Test",
            "-c",
            "user.email=pcm@example.invalid",
            "commit",
            "-m",
            "test commit",
            cwd=repository,
        )


def agent_result(
    cwd: Path, session: str = "session-1", text: str = "已处理"
) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": ["engineering-architecture", "commit-changes"],
            "slash_commands": ["engineering-architecture", "commit-changes"],
        },
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
    verdict: str, *, reason: str = "已核验", answer: str = ""
) -> tuple[dict, int, str]:
    value = {
        "verdict": verdict,
        "answer": answer,
        "reason": reason,
        "required_inputs": ["外部授权"] if verdict == "blocked" else [],
    }
    return value, 1, json.dumps(value, ensure_ascii=False)


class EngineeringArchitectureTests(unittest.TestCase):
    def make_run(
        self, root: Path, children: list[str] | None = None, *, existing: bool = False
    ) -> tuple[Path, Path, dict]:
        children = children or []
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        (workspace / "docs/requirements").mkdir(parents=True)
        (workspace / "docs/design").mkdir(parents=True)
        product_outputs = [
            "docs/requirements/项目需求说明.md",
            "docs/requirements/产品功能说明.md",
        ]
        checklist = "docs/requirements/项目准备清单.md"
        design = "docs/design/技术方案.md"
        for path in [*product_outputs, checklist, design]:
            (workspace / path).write_text("# 有效内容\n", encoding="utf-8")
        if existing:
            self.write_document(workspace)
        initialize_root_repository(workspace)
        for name in children:
            child = workspace / name
            child.mkdir()
            initialize_root_repository(child)
            (child / "README.md").write_text("# child\n", encoding="utf-8")
            commit_paths(child, "README.md")
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as handle:
                handle.write(f"{name}/\n")
        root_paths = [*product_outputs, checklist, design]
        if existing:
            root_paths.append(ARCHITECTURE_PATH.as_posix())
        commit_paths(workspace, *root_paths)
        write_json(run_dir / "steps/02.json", {"step": 2, "status": "success", "outputs": product_outputs})
        write_json(
            run_dir / "steps/05.json",
            readiness_result(
                "success",
                "准备基线已完成。",
                outputs=[checklist],
                readiness_baseline=readiness_baseline(workspace, product_outputs),
            ),
        )
        write_json(run_dir / "steps/07.json", {"step": 7, "status": "success", "applicable": True, "outputs": [design]})
        names = ["root", *children]
        write_json(
            run_dir / "steps/08.json",
            {
                "step": 8,
                "status": "success",
                "applicable": True,
                "outputs": [],
                "applicable_repositories": names,
                "repositories": [{"unexpected": True}],
            },
        )
        state = {
            "status": "success",
            "phase": "project_initialization",
            "step": 9,
            "current_step": 9,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "applicable_repositories": names,
            "repositories": [],
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    @staticmethod
    def write_document(workspace: Path) -> None:
        (workspace / ARCHITECTURE_PATH).write_text(
            "# 工程架构设计\n\n有效内容。\n", encoding="utf-8"
        )

    @staticmethod
    def commit_document(workspace: Path) -> None:
        commit_paths(workspace, ARCHITECTURE_PATH.as_posix())

    @staticmethod
    def run_step(run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    async def completed(self, *_args: object, **_kwargs: object) -> tuple[dict, int, str]:
        return decision("completed")

    def test_step_eight_handoff_uses_names_not_replayed_repository_facts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            _workspace, _outputs, names, _checklist, _design = architecture_step.validate_inputs(run_dir, state)
            self.assertEqual(names, ["root", "frontend"])
            state["applicable_repositories"] = ["root"]
            with self.assertRaisesRegex(RuntimeError, "交接状态"):
                architecture_step.validate_inputs(run_dir, state)

    def test_dirty_document_commits_once_and_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                if prompt.startswith("/engineering-architecture"):
                    self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes":
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            saved = self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
            self.assertEqual(saved["status"], "success")
            self.assertEqual(sum(prompt.splitlines()[0] == "/commit-changes" for prompt in prompts), 1)

    def test_clean_tracked_document_does_not_request_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), existing=True)
            prompts: list[str] = []

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            saved = self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
            self.assertEqual(saved["status"], "success")
            self.assertEqual(sum(prompt.splitlines()[0] == "/commit-changes" for prompt in prompts), 0)
            self.assertEqual(command("status", "--porcelain=v1", cwd=workspace).stdout, "")

    def test_document_repair_then_dirty_commit_reuses_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[tuple[str, str | None]] = []

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append((prompt, kwargs["resume_session_id"]))  # type: ignore[index]
                if "工程架构设计.md` 缺失或为空" in prompt:
                    self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes":
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
            self.assertTrue(calls[0][0].startswith("/engineering-architecture"))
            repair_prompt = next(
                prompt
                for prompt, _ in calls
                if "工程架构设计.md` 缺失或为空" in prompt
            )
            for required in (ARCHITECTURE_PATH.as_posix(), "仅创建或补全", "不修改其它文件", "Git 写操作"):
                self.assertIn(required, repair_prompt)
            self.assertNotIn("Current/Target", repair_prompt)
            sessions = [
                value
                for prompt, value in calls
                if "工程架构设计.md` 缺失或为空" in prompt
                or prompt.splitlines()[0] == "/commit-changes"
            ]
            self.assertEqual(sessions, ["session-1", "session-1"])

    def test_boundary_symlink_and_clean_untracked_document_cannot_succeed(self) -> None:
        for mutation in ("root", "child", "symlink"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir, workspace, state = self.make_run(root, ["frontend"])
                if mutation == "root":
                    (workspace / "README.md").write_text("dirty\n", encoding="utf-8")
                elif mutation == "child":
                    (workspace / "frontend/dirty.txt").write_text("dirty\n", encoding="utf-8")
                else:
                    target = root / "outside.md"
                    target.write_text("outside\n", encoding="utf-8")
                    (workspace / ARCHITECTURE_PATH).symlink_to(target)
                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state)
                if mutation == "symlink":
                    with self.assertRaises(RuntimeError):
                        architecture_repair(workspace)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as handle:
                handle.write(f"{ARCHITECTURE_PATH.as_posix()}\n")
            self.write_document(workspace)
            prompts: list[str] = []

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
            self.assertFalse(any(prompt.splitlines()[0] == "/commit-changes" for prompt in prompts))
            self.assertFalse((run_dir / "steps/09.json").exists())

    def test_fresh_rejects_execution_artifact_presence_without_reading_history(self) -> None:
        for artifact in ("session", "reference", "section", "history"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as directory:
                run_dir, _workspace, state = self.make_run(Path(directory))
                if artifact == "session":
                    state["claude_sessions"] = {CONVERSATION_KEY: "forged"}
                elif artifact == "reference":
                    state["decision_conversations"] = {CONVERSATION_KEY: {"path": "wrong"}}
                elif artifact == "section":
                    state[CONVERSATION_KEY] = "not a section"
                else:
                    (run_dir / "conversations").mkdir()
                    (run_dir / "conversations" / f"{CONVERSATION_KEY}.json").write_text("not json", encoding="utf-8")

                async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("不得执行 Agent")

                with self.assertRaisesRegex(RuntimeError, "既有执行产物"):
                    self.run_step(run_dir, state, agent_runner=unexpected)

    def test_result_state_interruption_recovers_without_agent_or_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                if prompt.startswith("/engineering-architecture"):
                    self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes":
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            original = architecture_step.write_state
            def interrupt(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("interrupted")
                original(target, value)

            with patch.object(
                architecture_step, "write_state", side_effect=interrupt
            ):
                with self.assertRaises(OSError):
                    self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())

            async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                raise AssertionError("不得恢复执行")

            saved = self.run_step(run_dir, read_state(run_dir), agent_runner=unexpected, decision_runner=unexpected)
            self.assertEqual(saved["status"], "success")
            self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_blocked_clean_tracked_document_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                if prompt.startswith("/engineering-architecture"):
                    self.write_document(workspace)
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            async def blocked(*_args: object, **_kwargs: object) -> tuple[dict, int, str]:
                return decision("blocked", reason="缺少外部授权")

            with self.assertRaises(EngineeringArchitectureBlocked):
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=blocked, config_loader=lambda: object())
            saved = json.loads((run_dir / "steps/09.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "blocked")
            self.assertEqual(read_state(run_dir)["current_node"], CURRENT_NODE)
    def test_initial_prompt_exposes_only_engineering_domain_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(
                Path(directory), ["frontend", "backend"]
            )
            prompts: list[str] = []

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                if prompt.startswith("/engineering-architecture"):
                    self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes":
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=self.completed,
                config_loader=lambda: object(),
            )
            prompt = prompts[0]
            self.assertTrue(prompt.startswith("/engineering-architecture\n"))
            for required in (
                "/engineering-architecture",
                ARCHITECTURE_PATH.as_posix(),
                "docs/requirements/项目需求说明.md",
                "docs/requirements/产品功能说明.md",
                "docs/requirements/项目准备清单.md",
                "docs/design/技术方案.md",
                "@./frontend",
                "@./backend",
                "只允许修改该固定产物",
                "Git 写操作",
            ):
                self.assertIn(required, prompt)
            for forbidden in ("第 9 步", "PCM", "节点", "session", "/commit-changes"):
                self.assertNotIn(forbidden, prompt)

    def test_decision_system_prompt_uses_dynamic_context_and_completion_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(
                Path(directory), ["frontend", "backend"], existing=True
            )
            system_prompts: list[str] = []

            async def agent(_prompt: str, **kwargs: object) -> ClaudeRunResult:
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            async def capture_decision(
                _messages: list[dict[str, str]],
                _config: object,
                *,
                system_prompt: str,
            ) -> tuple[dict, int, str]:
                system_prompts.append(system_prompt)
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=capture_decision,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertEqual(len(system_prompts), 1)
            system_prompt = system_prompts[0]
            self.assertNotEqual(
                system_prompt,
                architecture_step.DECISION_LOOP_SPEC.decision_system_prompt,
            )
            for section in (
                "role",
                "project_context",
                "responsibility",
                "completion",
                "output",
            ):
                self.assertIn(f"<{section}>", system_prompt)
                self.assertIn(f"</{section}>", system_prompt)
            for required in (
                '"产品定义"',
                '"项目准备清单"',
                '"总体技术方案"',
                '"权威工程"',
                '"frontend"',
                '"backend"',
                f'"固定输出": "{ARCHITECTURE_PATH.as_posix()}"',
                "固定工程架构设计文档已生成",
                "逐交付单元工程归属合同",
                "稳定边界与内部粒度区分",
                "Current 偏差迁移",
                "工程事实核验",
                "下游所需高影响架构决定",
            ):
                self.assertIn(required, system_prompt)
            responsibility = system_prompt.split("<responsibility>", 1)[1].split(
                "</responsibility>", 1
            )[0]
            completion = system_prompt.split("<completion>", 1)[1].split(
                "</completion>", 1
            )[0]
            self.assertIn("逐交付单元工程归属合同", completion)
            self.assertNotIn("- completed：", responsibility)

    def test_agent_out_of_scope_changes_fail_before_decision(self) -> None:
        for mutation in ("root", "child"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
                decision_called = False

                async def agent(_prompt: str, **kwargs: object) -> ClaudeRunResult:
                    self.write_document(workspace)
                    target = workspace if mutation == "root" else workspace / "frontend"
                    (target / "unexpected.txt").write_text("dirty\n", encoding="utf-8")
                    value = agent_result(kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index,operator]
                    return value

                async def unexpected_decision(*_args: object, **_kwargs: object) -> object:
                    nonlocal decision_called
                    decision_called = True
                    raise AssertionError("越界修改不得请求负责人决定")

                with self.assertRaisesRegex(RuntimeError, "AI-compatible 裁决本地处理失败"):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=unexpected_decision,
                        config_loader=lambda: object(),
                    )
                self.assertFalse(decision_called)

    def test_commit_follow_up_can_continue_same_session_and_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[tuple[str, str | None]] = []
            repair_and_commit = "修正固定文档并提交。"

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append((prompt, kwargs["resume_session_id"]))  # type: ignore[index]
                text = "已处理"
                if prompt.startswith("/engineering-architecture"):
                    self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes":
                    text = "固定文档仍需修正"
                elif prompt == repair_and_commit:
                    self.write_document(workspace)
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"], text=text)  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            async def decide(
                messages: list[dict[str, str]], *_args: object, **_kwargs: object
            ) -> tuple[dict, int, str]:
                if messages[-1]["content"] == "固定文档仍需修正":
                    return decision("continue", answer=repair_and_commit)
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertTrue(calls[0][0].startswith("/engineering-architecture"))
            self.assertEqual(calls[1][0].splitlines()[0], "/commit-changes")
            self.assertEqual(calls[2][0], repair_and_commit)
            self.assertEqual(
                [session for _, session in calls[1:]], ["session-1", "session-1"]
            )

    def test_blocked_rerun_uses_common_resume_session_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[tuple[str, str | None]] = []
            decisions = [decision("blocked", reason="缺少授权"), decision("completed")]

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append((prompt, kwargs["resume_session_id"]))  # type: ignore[index]
                if prompt.startswith("/engineering-architecture"):
                    self.write_document(workspace)
                elif prompt == BLOCKED_RESUME_PROMPT:
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            async def decide(*_args: object, **_kwargs: object) -> tuple[dict, int, str]:
                return decisions.pop(0)

            with self.assertRaises(EngineeringArchitectureBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            saved = self.run_step(
                run_dir,
                read_state(run_dir),
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls[1], (BLOCKED_RESUME_PROMPT, "session-1"))

    def test_existing_success_is_execution_free_and_rejects_drift(self) -> None:
        for mutation in ("document", "child"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])

                async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    if prompt.startswith("/engineering-architecture"):
                        self.write_document(workspace)
                    elif prompt.splitlines()[0] == "/commit-changes":
                        self.commit_document(workspace)
                    value = agent_result(kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index,operator]
                    return value

                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    decision_runner=self.completed,
                    config_loader=lambda: object(),
                )

                async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("既有成功不得执行 Agent 或负责人决定")

                self.assertEqual(
                    self.run_step(
                        run_dir,
                        read_state(run_dir),
                        agent_runner=unexpected,
                        decision_runner=unexpected,
                    )["status"],
                    "success",
                )
                if mutation == "document":
                    (workspace / ARCHITECTURE_PATH).write_text(
                        "漂移\n", encoding="utf-8"
                    )
                else:
                    (workspace / "frontend/drift.txt").write_text(
                        "drift\n", encoding="utf-8"
                    )
                with self.assertRaises(RuntimeError):
                    self.run_step(
                        run_dir,
                        read_state(run_dir),
                        agent_runner=unexpected,
                        decision_runner=unexpected,
                    )

    def test_production_git_reads_use_allowlisted_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            with patch.object(
                architecture_step.subprocess, "run", wraps=subprocess.run
            ) as mocked:
                architecture_step.validate_inputs(run_dir, state)
                architecture_step._verify_worktree_boundary(workspace, ["root", "frontend"])
                architecture_step._document_tracked(workspace)
            commands = [tuple(call.args[0][1:]) for call in mocked.call_args_list]
            allowed = {
                ("rev-parse", "--show-toplevel"),
                ("branch", "--show-current"),
                ("status", "--porcelain=v1", "--untracked-files=all"),
                (
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    "--",
                    ARCHITECTURE_PATH.as_posix(),
                ),
                ("ls-files", "--error-unmatch", "--", ARCHITECTURE_PATH.as_posix()),
            }
            self.assertTrue(commands)
            self.assertTrue(all(item in allowed for item in commands))
            self.assertFalse(
                {"add", "commit", "switch", "checkout", "reset", "log", "diff"}
                & {item[0] for item in commands}
            )
    def test_blocked_rerun_rejects_preexisting_dirty_before_agent(self) -> None:
        for mutation in ("root", "child"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])

                async def first_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    if prompt.startswith("/engineering-architecture"):
                        self.write_document(workspace)
                    value = agent_result(kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index,operator]
                    return value

                async def blocked(*_args: object, **_kwargs: object) -> tuple[dict, int, str]:
                    return decision("blocked", reason="缺少外部授权")

                with self.assertRaises(EngineeringArchitectureBlocked):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=first_agent,
                        decision_runner=blocked,
                        config_loader=lambda: object(),
                    )

                target = workspace if mutation == "root" else workspace / "frontend"
                (target / "unexpected.txt").write_text("dirty\n", encoding="utf-8")
                agent_called = False

                async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                    nonlocal agent_called
                    agent_called = True
                    raise AssertionError("污染现场不得恢复 Agent")

                with self.assertRaises(RuntimeError):
                    self.run_step(
                        run_dir,
                        read_state(run_dir),
                        agent_runner=unexpected,
                        decision_runner=unexpected,
                    )
                self.assertFalse(agent_called)

    def test_cli_and_domain_share_strict_step_nine_success_shape(self) -> None:
        import run_step as cli

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "steps").mkdir()
            valid = architecture_step.result(
                "success", "已完成", outputs=[ARCHITECTURE_PATH.as_posix()]
            )
            write_json(run_dir / "steps/09.json", valid)
            self.assertTrue(cli.has_step_success(run_dir, 9))
            architecture_step.verify_existing_success(run_dir)

            for mutation in ("extra", "blank-summary"):
                invalid = dict(valid)
                if mutation == "extra":
                    invalid["unexpected"] = True
                else:
                    invalid["summary"] = "   "
                write_json(run_dir / "steps/09.json", invalid)
                self.assertFalse(cli.has_step_success(run_dir, 9))
                with self.assertRaises(RuntimeError):
                    architecture_step.verify_existing_success(run_dir)

    def test_failed_without_execution_artifacts_rejects_dirty_before_agent(self) -> None:
        for mutation in ("root", "child"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
                state["status"] = "failed"
                target = workspace if mutation == "root" else workspace / "frontend"
                (target / "dirty.txt").write_text("dirty\n", encoding="utf-8")
                agent_called = False

                async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                    nonlocal agent_called
                    agent_called = True
                    raise AssertionError("dirty 恢复不得启动 Agent")

                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state, agent_runner=unexpected)
                self.assertFalse(agent_called)


if __name__ == "__main__":
    unittest.main()
