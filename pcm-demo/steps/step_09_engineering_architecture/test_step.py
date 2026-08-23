from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.agent_decision_loop import BLOCKED_RESUME_PROMPT
from common.claude_agent import ClaudeRunResult
from common.files import write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_09_engineering_architecture.step import (
    ARCHITECTURE_PATH,
    ARCHITECTURE_REPAIR_PROMPT,
    COMMIT_REPAIR_PROMPT,
    CONVERSATION_KEY,
    CURRENT_NODE,
    ENGINEERING_ARCHITECTURE_MAX_BUDGET_USD,
    ENGINEERING_ARCHITECTURE_MAX_TURNS,
    NEXT_NODE,
    EngineeringArchitectureBlocked,
    _commit_requested,
    initial_prompt,
    result,
    run,
)
import steps.step_09_engineering_architecture.step as architecture_step


def command(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=check
    )


def commit_paths(repository: Path, *paths: str, message: str = "test commit") -> None:
    command("add", "--", *paths, cwd=repository)
    status = command("status", "--porcelain=v1", cwd=repository).stdout
    if status:
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


def agent_result(
    *, cwd: Path, text: str = "已处理", session: str = "session-1"
) -> ClaudeRunResult:
    skills = ["engineering-architecture", "commit-changes"]
    return ClaudeRunResult(
        init={"cwd": str(cwd), "skills": skills, "slash_commands": skills},
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


class EngineeringArchitectureTests(unittest.TestCase):
    def make_run(
        self,
        root: Path,
        outputs: list[str] | None = None,
        *,
        existing_architecture: bool = False,
    ) -> tuple[Path, Path, dict]:
        children = outputs or []
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
            (workspace / path).write_text(f"# {Path(path).stem}\n\n有效内容。\n", encoding="utf-8")
        if existing_architecture:
            (workspace / ARCHITECTURE_PATH).write_text(
                "# 工程架构设计\n\n既有有效内容。\n", encoding="utf-8"
            )

        initialize_root_repository(workspace)
        for name in children:
            child = workspace / name
            child.mkdir()
            initialize_root_repository(child)
            (child / "README.md").write_text(f"# {name}\n", encoding="utf-8")
            commit_paths(child, "README.md")
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
                exclude.write(f"{name}/\n")
        root_paths = [*product_outputs, checklist, design]
        if existing_architecture:
            root_paths.append(ARCHITECTURE_PATH.as_posix())
        commit_paths(workspace, *root_paths)

        write_json(
            run_dir / "steps/02.json",
            {"step": 2, "status": "success", "outputs": product_outputs},
        )
        write_json(
            run_dir / "steps/05.json",
            {"step": 5, "status": "success", "outputs": [checklist]},
        )
        write_json(
            run_dir / "steps/07.json",
            {
                "step": 7,
                "status": "success",
                "applicable": True,
                "outputs": [design],
            },
        )
        names = ["root", *children]
        result_repositories = [
            {
                "name": name,
                "path": "." if name == "root" else name,
                "branch": "main",
                "worktree_clean": True,
            }
            for name in names
        ]
        write_json(
            run_dir / "steps/08.json",
            {
                "step": 8,
                "name": "首次提交适用仓库",
                "status": "success",
                "summary": "已完成",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "applicable_repositories": names,
                "repositories": result_repositories,
            },
        )
        state_repositories = [
            {
                "name": name,
                "path": str((workspace if name == "root" else workspace / name).resolve()),
                "branch": "main",
                "worktree_clean": True,
            }
            for name in names
        ]
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": "project_initialization",
            "step": 9,
            "current_step": 9,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "applicable_repositories": names,
            "repositories": state_repositories,
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    def run_step(self, run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    @staticmethod
    def write_architecture(workspace: Path) -> None:
        (workspace / ARCHITECTURE_PATH).write_text(
            "# 工程架构设计\n\n模块边界、依赖方向和质量门禁。\n", encoding="utf-8"
        )

    @staticmethod
    def commit_architecture(workspace: Path) -> None:
        commit_paths(workspace, ARCHITECTURE_PATH.as_posix(), message="docs: 工程架构设计")

    def test_required_root_only_and_three_repositories_succeed(self) -> None:
        for children in ([], ["frontend", "backend"]):
            with self.subTest(children=children), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), children)
                calls: list[dict] = []

                async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    calls.append({"prompt": prompt, **kwargs})
                    if prompt.startswith("/engineering-architecture"):
                        self.write_architecture(workspace)
                    elif prompt == COMMIT_REPAIR_PROMPT:
                        self.commit_architecture(workspace)
                    value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index, operator]
                    return value

                async def completed(messages, config, *, system_prompt):
                    return decision("completed")

                saved = self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )
                self.assertEqual(saved["outputs"], [ARCHITECTURE_PATH.as_posix()])
                self.assertTrue(saved["applicable"])
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[1]["prompt"], COMMIT_REPAIR_PROMPT)
                self.assertEqual(calls[1]["resume_session_id"], "session-1")
                self.assertEqual(calls[0]["max_turns"], ENGINEERING_ARCHITECTURE_MAX_TURNS)
                self.assertEqual(
                    calls[0]["max_budget_usd"], ENGINEERING_ARCHITECTURE_MAX_BUDGET_USD
                )
                completed_state = read_state(run_dir)
                self.assertEqual(
                    (completed_state["step"], completed_state["current_node"]),
                    (10, NEXT_NODE),
                )
                self.assertEqual(
                    [entry["name"] for entry in completed_state["repositories"]],
                    ["root", *children],
                )
                self.assertTrue(
                    all(Path(entry["path"]).is_absolute() for entry in completed_state["repositories"])
                )
                self.assertNotIn("head", json.dumps(completed_state["repositories"]))

    def test_initial_prompt_contains_only_domain_inputs_engineering_output_and_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend", "backend"])
            prompts: list[str] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                if len(prompts) == 1:
                    self.write_architecture(workspace)
                else:
                    self.commit_architecture(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                for required in (
                    "# 项目需求说明",
                    "# 产品功能说明",
                    "# 项目准备清单",
                    "# 技术方案",
                    '"root"',
                    ARCHITECTURE_PATH.as_posix(),
                ):
                    self.assertIn(required, system_prompt)
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            prompt = prompts[0]
            self.assertTrue(prompt.startswith("/engineering-architecture\n"))
            for required in (
                "docs/requirements/项目需求说明.md",
                "docs/requirements/产品功能说明.md",
                "docs/requirements/项目准备清单.md",
                "docs/design/技术方案.md",
                "@./frontend",
                "@./backend",
                ARCHITECTURE_PATH.as_posix(),
                "`CLAUDE.md`",
                "`AGENTS.md`",
                "其它项目规则",
            ):
                self.assertIn(required, prompt)
            for forbidden in ("第 9 步", "PCM", "节点", "session", "/commit-changes"):
                self.assertNotIn(forbidden, prompt)

    def test_domain_repair_then_commit_repair_uses_one_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if prompt == ARCHITECTURE_REPAIR_PROMPT:
                    self.write_architecture(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_architecture(workspace)
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
            self.assertEqual(
                [call["prompt"] for call in calls],
                [calls[0]["prompt"], ARCHITECTURE_REPAIR_PROMPT, COMMIT_REPAIR_PROMPT],
            )
            self.assertTrue(calls[0]["prompt"].startswith("/engineering-architecture"))
            self.assertFalse(ARCHITECTURE_REPAIR_PROMPT.startswith("/"))
            self.assertIn(ARCHITECTURE_PATH.as_posix(), ARCHITECTURE_REPAIR_PROMPT)
            self.assertIn("不得修改任何其他文件", ARCHITECTURE_REPAIR_PROMPT)
            self.assertIn("不得执行 Git 写操作", ARCHITECTURE_REPAIR_PROMPT)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(
                [call["resume_session_id"] for call in calls[1:]],
                ["session-1", "session-1"],
            )

    def test_existing_tracked_unchanged_document_still_requests_commit_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(
                Path(directory), existing_architecture=True
            )
            prompts: list[str] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertEqual(len(prompts), 2)
            self.assertEqual(prompts[1], COMMIT_REPAIR_PROMPT)

    def test_fresh_entry_rejects_any_existing_execution_artifact(self) -> None:
        for artifact in ("session", "reference", "section"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as directory:
                run_dir, _workspace, state = self.make_run(Path(directory))
                if artifact == "session":
                    state["claude_sessions"] = {CONVERSATION_KEY: "session-1"}
                elif artifact == "reference":
                    state["decision_conversations"] = {
                        CONVERSATION_KEY: {
                            "path": f"conversations/{CONVERSATION_KEY}.json"
                        }
                    }
                else:
                    state[CONVERSATION_KEY] = {}
                write_state(run_dir, state)

                async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("新鲜入口存在执行产物时不得调用 Agent")

                with self.assertRaisesRegex(RuntimeError, "新鲜.*既有执行产物"):
                    self.run_step(run_dir, state, agent_runner=unexpected)

    def test_fresh_entry_rejects_forged_unreferenced_completed_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(
                Path(directory), existing_architecture=True
            )
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / f"conversations/{CONVERSATION_KEY}.json",
                {
                    "messages": [
                        {"role": "system", "content": "伪造 system"},
                        {"role": "assistant", "content": COMMIT_REPAIR_PROMPT},
                        {"role": "user", "content": "伪造提交回复"},
                        {"role": "assistant", "content": decision("completed")[2]},
                    ]
                },
            )
            agent_called = False

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                nonlocal agent_called
                agent_called = True
                raise AssertionError("伪造历史不得被采纳")

            with self.assertRaisesRegex(RuntimeError, "新鲜.*既有执行产物"):
                self.run_step(run_dir, state, agent_runner=unexpected)
            self.assertFalse(agent_called)

    def test_fresh_entry_rejects_symlink_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _workspace, state = self.make_run(root)
            conversations = run_dir / "conversations"
            conversations.mkdir()
            target = root / "forged-conversation.json"
            write_json(target, {"messages": [{"role": "system", "content": "伪造"}]})
            (conversations / f"{CONVERSATION_KEY}.json").symlink_to(target)

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("符号链接历史不得启动 Agent")

            with self.assertRaisesRegex(RuntimeError, "非符号链接普通文件"):
                self.run_step(run_dir, state, agent_runner=unexpected)

    def test_fresh_entry_rejects_symlink_conversations_directory_without_external_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _workspace, state = self.make_run(root)
            external = root / "external-conversations"
            external.mkdir()
            (run_dir / "conversations").symlink_to(external, target_is_directory=True)
            agent_called = False
            decision_called = False

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                nonlocal agent_called
                agent_called = True
                raise AssertionError("不安全 conversation 目录不得调用 Agent")

            async def unexpected_decision(messages, config, *, system_prompt):
                nonlocal decision_called
                decision_called = True
                raise AssertionError("不安全 conversation 目录不得请求决定")

            with self.assertRaisesRegex(RuntimeError, "conversations.*非符号链接目录"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=unexpected_agent,
                    decision_runner=unexpected_decision,
                )
            self.assertFalse(agent_called)
            self.assertFalse(decision_called)
            self.assertEqual(list(external.iterdir()), [])

    def test_recovery_rejects_symlink_conversations_directory_with_external_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _workspace, state = self.make_run(root)
            external = root / "external-conversations"
            external.mkdir()
            external_history = external / f"{CONVERSATION_KEY}.json"
            write_json(
                external_history,
                {"messages": [{"role": "system", "content": "外部历史"}]},
            )
            (run_dir / "conversations").symlink_to(external, target_is_directory=True)
            state.update(
                {
                    "status": "failed",
                    "claude_sessions": {CONVERSATION_KEY: "session-1"},
                    "decision_conversations": {
                        CONVERSATION_KEY: {
                            "path": f"conversations/{CONVERSATION_KEY}.json"
                        }
                    },
                }
            )
            agent_called = False
            decision_called = False

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                nonlocal agent_called
                agent_called = True
                raise AssertionError("不安全恢复目录不得调用 Agent")

            async def unexpected_decision(messages, config, *, system_prompt):
                nonlocal decision_called
                decision_called = True
                raise AssertionError("不安全恢复目录不得请求决定")

            with self.assertRaisesRegex(RuntimeError, "conversations.*非符号链接目录"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=unexpected_agent,
                    decision_runner=unexpected_decision,
                )
            self.assertFalse(agent_called)
            self.assertFalse(decision_called)
            self.assertEqual(
                [path.name for path in external.iterdir()],
                [external_history.name],
            )

    def test_commit_requested_requires_exact_prompt_followed_by_agent_reply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _workspace, state = self.make_run(root)
            conversations = run_dir / "conversations"
            conversations.mkdir()
            path = conversations / f"{CONVERSATION_KEY}.json"
            state["claude_sessions"] = {CONVERSATION_KEY: "session-1"}
            state["decision_conversations"] = {
                CONVERSATION_KEY: {"path": f"conversations/{CONVERSATION_KEY}.json"}
            }
            cases = [
                ([{"role": "user", "content": COMMIT_REPAIR_PROMPT}], False),
                ([{"role": "assistant", "content": COMMIT_REPAIR_PROMPT + "\n"}], False),
                ([{"role": "assistant", "content": "前缀" + COMMIT_REPAIR_PROMPT}], False),
                ([{"role": "assistant", "content": COMMIT_REPAIR_PROMPT}], False),
                (
                    [
                        {"role": "assistant", "content": COMMIT_REPAIR_PROMPT},
                        {"role": "user", "content": "   "},
                    ],
                    False,
                ),
                (
                    [
                        {"role": "assistant", "content": COMMIT_REPAIR_PROMPT},
                        {"role": "user", "content": "提交回复报告文档仍需修正"},
                        {"role": "assistant", "content": "请只修正并提交固定文档。"},
                        {"role": "user", "content": "已修正并提交固定文档"},
                    ],
                    True,
                ),
                (
                    [
                        {"role": "assistant", "content": COMMIT_REPAIR_PROMPT},
                        {"role": "user", "content": "已完成提交核验"},
                    ],
                    True,
                ),
            ]
            for tail, expected in cases:
                with self.subTest(tail=tail):
                    write_json(
                        path,
                        {"messages": [{"role": "system", "content": "x"}, *tail]},
                    )
                    self.assertEqual(_commit_requested(run_dir, state), expected)
            state["claude_sessions"].pop(CONVERSATION_KEY)
            write_json(
                path,
                {
                    "messages": [
                        {"role": "system", "content": "x"},
                        {"role": "assistant", "content": COMMIT_REPAIR_PROMPT},
                        {"role": "user", "content": "已完成提交核验"},
                    ]
                },
            )
            self.assertFalse(_commit_requested(run_dir, state))
            state["claude_sessions"][CONVERSATION_KEY] = "session-1"
            state["decision_conversations"][CONVERSATION_KEY]["path"] = "conversations/other.json"
            with self.assertRaisesRegex(RuntimeError, "引用"):
                _commit_requested(run_dir, state)

    def test_untracked_document_repeats_commit_repair_until_tracked_and_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                if len(prompts) == 1:
                    self.write_architecture(workspace)
                elif prompts.count(COMMIT_REPAIR_PROMPT) == 2:
                    self.commit_architecture(workspace)
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
            self.assertEqual(prompts.count(COMMIT_REPAIR_PROMPT), 2)

    def test_commit_reply_can_continue_with_fixed_document_repair_and_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []
            repair_and_commit = (
                "只修正 `docs/design/工程架构设计.md` 中的边界语义并提交该固定文档；"
                "不得修改或提交任何其他文件。"
            )

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                if len(prompts) == 1:
                    (workspace / ARCHITECTURE_PATH).write_text(
                        "# 工程架构设计\n\n存在待修正的边界语义。\n", encoding="utf-8"
                    )
                    text = "已生成文档"
                elif prompt == COMMIT_REPAIR_PROMPT:
                    text = "提交检查发现固定文档的边界语义仍需修正"
                else:
                    self.assertEqual(prompt, repair_and_commit)
                    (workspace / ARCHITECTURE_PATH).write_text(
                        "# 工程架构设计\n\n已修正模块边界语义。\n", encoding="utf-8"
                    )
                    self.commit_architecture(workspace)
                    text = "已只修正并提交固定文档"
                value = agent_result(cwd=kwargs["cwd"], text=text)  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def decide(messages, config, *, system_prompt):
                if messages[-1]["content"] == "提交检查发现固定文档的边界语义仍需修正":
                    return decision(
                        "continue",
                        answer=repair_and_commit,
                        reason="固定文档需要有限修正后提交",
                    )
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertEqual(
                prompts,
                [prompts[0], COMMIT_REPAIR_PROMPT, repair_and_commit],
            )
            self.assertTrue(_commit_requested(run_dir, read_state(run_dir)))
            committed_paths = command(
                "-c",
                "core.quotePath=false",
                "show",
                "--pretty=format:",
                "--name-only",
                "HEAD",
                cwd=workspace,
            ).stdout.splitlines()
            self.assertEqual(committed_paths, [ARCHITECTURE_PATH.as_posix()])
            self.assertEqual(
                command("status", "--porcelain=v1", cwd=workspace).stdout,
                "",
            )

    def test_initial_out_of_scope_and_child_dirty_are_rejected_before_agent(self) -> None:
        cases = ("root", "child")
        for mutation in cases:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
                target = workspace if mutation == "root" else workspace / "frontend"
                (target / "unexpected.txt").write_text("dirty\n", encoding="utf-8")

                async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("边界失败前不得调用 Agent")

                message = "范围外" if mutation == "root" else "子仓库"
                with self.assertRaisesRegex(RuntimeError, message):
                    self.run_step(run_dir, state, agent_runner=unexpected)

    def test_agent_out_of_scope_change_fails_before_owner_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            decision_called = False

            async def bad_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                self.write_architecture(workspace)
                (workspace / "README.md").write_text("越界\n", encoding="utf-8")
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def unexpected_decision(messages, config, *, system_prompt):
                nonlocal decision_called
                decision_called = True
                raise AssertionError("范围核验失败后不得请求负责人决定")

            with self.assertRaisesRegex(RuntimeError, "AI-compatible 决策失败"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=bad_agent,
                    decision_runner=unexpected_decision,
                    config_loader=lambda: object(),
                )
            self.assertFalse(decision_called)

    def test_agent_out_of_scope_change_cannot_continue_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            agent_calls = 0
            decision_calls = 0

            async def bad_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                nonlocal agent_calls
                agent_calls += 1
                self.write_architecture(workspace)
                (workspace / "README.md").write_text("越界\n", encoding="utf-8")
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def would_continue(messages, config, *, system_prompt):
                nonlocal decision_calls
                decision_calls += 1
                return decision(
                    "continue", answer="继续补全架构。", reason="仍有内容待补充"
                )

            with self.assertRaisesRegex(RuntimeError, "AI-compatible 决策失败"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=bad_agent,
                    decision_runner=would_continue,
                    config_loader=lambda: object(),
                )
            self.assertEqual(agent_calls, 1)
            self.assertEqual(decision_calls, 0)

    def test_blocked_saves_current_output_and_resumes_original_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []
            verdicts = ["blocked", "completed", "completed"]

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 1:
                    self.write_architecture(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_architecture(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def decide(messages, config, *, system_prompt):
                verdict = verdicts.pop(0)
                if verdict == "blocked":
                    return decision(
                        "blocked", reason="缺少授权", required_inputs=["外部授权"]
                    )
                return decision("completed")

            with self.assertRaises(EngineeringArchitectureBlocked) as raised:
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            self.assertEqual(raised.exception.outputs, [ARCHITECTURE_PATH.as_posix()])
            blocked_state = read_state(run_dir)
            self.assertEqual(blocked_state["status"], "blocked")
            blocked_result = json.loads(
                (run_dir / "steps/09.json").read_text(encoding="utf-8")
            )
            self.assertEqual(blocked_result["outputs"], [ARCHITECTURE_PATH.as_posix()])

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
            self.assertEqual(calls[2]["prompt"], COMMIT_REPAIR_PROMPT)

    def test_blocked_after_commit_repair_is_normalized_to_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[str] = []
            verdicts = ["completed", "blocked"]

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append(prompt)
                if prompt.startswith("/engineering-architecture"):
                    self.write_architecture(workspace)
                else:
                    self.commit_architecture(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def decide(messages, config, *, system_prompt):
                verdict = verdicts.pop(0)
                if verdict == "blocked":
                    return decision(
                        "blocked", reason="误报阻塞", required_inputs=["外部输入"]
                    )
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls[-1], COMMIT_REPAIR_PROMPT)
            self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_failed_recovery_without_session_allows_only_pre_agent_history(self) -> None:
        for history in ("system", "initial"):
            with self.subTest(history=history), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                prompt = initial_prompt(
                    [
                        "docs/requirements/项目需求说明.md",
                        "docs/requirements/产品功能说明.md",
                    ],
                    ["root"],
                )
                messages = [{"role": "system", "content": "persisted system"}]
                if history == "initial":
                    messages.append({"role": "assistant", "content": prompt})
                state.update(
                    {
                        "status": "failed",
                        "decision_conversations": {
                            CONVERSATION_KEY: {
                                "path": f"conversations/{CONVERSATION_KEY}.json"
                            }
                        },
                    }
                )
                (run_dir / "conversations").mkdir()
                write_json(
                    run_dir / f"conversations/{CONVERSATION_KEY}.json",
                    {"messages": messages},
                )
                calls: list[dict] = []

                async def fake_agent(prompt_value: str, **kwargs: object) -> ClaudeRunResult:
                    calls.append({"prompt": prompt_value, **kwargs})
                    if prompt_value.startswith("/engineering-architecture"):
                        self.write_architecture(workspace)
                    elif prompt_value == COMMIT_REPAIR_PROMPT:
                        self.commit_architecture(workspace)
                    value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index, operator]
                    return value

                async def completed(messages, config, *, system_prompt):
                    return decision("completed")

                saved = self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )
                self.assertEqual(saved["status"], "success")
                self.assertIsNone(calls[0]["resume_session_id"])

    def test_recovery_rejects_unreferenced_or_agent_history_without_session(self) -> None:
        for case in ("unreferenced", "agent-reply", "decision", "commit-prompt"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_dir, _workspace, state = self.make_run(Path(directory))
                state["status"] = "running"
                messages = [{"role": "system", "content": "persisted system"}]
                if case == "agent-reply":
                    messages.append({"role": "user", "content": "Agent 回复"})
                elif case == "decision":
                    messages.append(
                        {"role": "assistant", "content": decision("completed")[2]}
                    )
                elif case == "commit-prompt":
                    messages.append(
                        {"role": "assistant", "content": COMMIT_REPAIR_PROMPT}
                    )
                if case != "unreferenced":
                    state["decision_conversations"] = {
                        CONVERSATION_KEY: {
                            "path": f"conversations/{CONVERSATION_KEY}.json"
                        }
                    }
                (run_dir / "conversations").mkdir()
                write_json(
                    run_dir / f"conversations/{CONVERSATION_KEY}.json",
                    {"messages": messages},
                )

                async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("无效恢复锚点不得调用 Agent")

                expected = "未引用" if case == "unreferenced" else "缺少原 Claude session"
                with self.assertRaisesRegex(RuntimeError, expected):
                    self.run_step(run_dir, state, agent_runner=unexpected)

    def test_blocked_or_failed_execution_requires_complete_resume_anchor(self) -> None:
        for status in ("running", "failed", "blocked"):
            for missing in ("session", "reference", "file"):
                with self.subTest(status=status, missing=missing), tempfile.TemporaryDirectory() as directory:
                    run_dir, _workspace, state = self.make_run(Path(directory))
                    state["status"] = status
                    state[CONVERSATION_KEY] = {"last_agent_result": {"subtype": "success"}}
                    if missing != "session":
                        state["claude_sessions"] = {CONVERSATION_KEY: "session-1"}
                    if missing != "reference":
                        state["decision_conversations"] = {
                            CONVERSATION_KEY: {
                                "path": f"conversations/{CONVERSATION_KEY}.json"
                            }
                        }
                    if missing != "file":
                        (run_dir / "conversations").mkdir()
                        messages = [{"role": "system", "content": "system"}]
                        if status == "blocked":
                            messages.append(
                                {
                                    "role": "assistant",
                                    "content": decision(
                                        "blocked",
                                        reason="缺少授权",
                                        required_inputs=["授权"],
                                    )[2],
                                }
                            )
                        write_json(
                            run_dir / f"conversations/{CONVERSATION_KEY}.json",
                            {"messages": messages},
                        )
                    write_state(run_dir, state)
                    expected = "未引用" if missing == "reference" else "缺少原"
                    with self.assertRaisesRegex(RuntimeError, expected):
                        self.run_step(run_dir, state)

    def test_blocked_resume_requires_blocked_decision_tail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory))
            state.update(
                {
                    "status": "blocked",
                    "claude_sessions": {CONVERSATION_KEY: "session-1"},
                    "decision_conversations": {
                        CONVERSATION_KEY: {
                            "path": f"conversations/{CONVERSATION_KEY}.json"
                        }
                    },
                }
            )
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / f"conversations/{CONVERSATION_KEY}.json",
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": decision("completed")[2]},
                    ]
                },
            )
            with self.assertRaisesRegex(RuntimeError, "不是 blocked"):
                self.run_step(run_dir, state)

    def test_failed_pending_reply_recovers_without_new_initial_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            self.write_architecture(workspace)
            state.update(
                {
                    "status": "failed",
                    "claude_sessions": {CONVERSATION_KEY: "session-1"},
                    "decision_conversations": {
                        CONVERSATION_KEY: {
                            "path": f"conversations/{CONVERSATION_KEY}.json"
                        }
                    },
                    CONVERSATION_KEY: {
                        "pending_agent_text": "中断前完整领域回复",
                        "last_agent_result": {
                            "subtype": "success",
                            "is_error": False,
                            "has_errors": False,
                            "api_error_status": None,
                            "exception_type": None,
                            "terminal_reason": None,
                        },
                    },
                }
            )
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / f"conversations/{CONVERSATION_KEY}.json",
                {
                    "messages": [
                        {"role": "system", "content": "persisted system"},
                        {"role": "assistant", "content": "初始领域提示"},
                    ]
                },
            )
            calls: list[str] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append(prompt)
                self.assertEqual(prompt, COMMIT_REPAIR_PROMPT)
                self.commit_architecture(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls, [COMMIT_REPAIR_PROMPT])

    def test_commit_repair_tail_interruption_is_resumed_by_common_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(
                Path(directory), existing_architecture=True
            )
            state.update(
                {
                    "status": "failed",
                    "claude_sessions": {CONVERSATION_KEY: "session-1"},
                    "decision_conversations": {
                        CONVERSATION_KEY: {
                            "path": f"conversations/{CONVERSATION_KEY}.json"
                        }
                    },
                    CONVERSATION_KEY: {
                        "last_agent_result": {
                            "subtype": "success",
                            "is_error": False,
                            "has_errors": False,
                            "api_error_status": None,
                            "exception_type": None,
                            "terminal_reason": None,
                        }
                    },
                }
            )
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / f"conversations/{CONVERSATION_KEY}.json",
                {
                    "messages": [
                        {"role": "system", "content": "persisted system"},
                        {"role": "assistant", "content": "领域提示"},
                        {"role": "user", "content": "领域回复"},
                        {"role": "assistant", "content": decision("completed")[2]},
                        {"role": "assistant", "content": COMMIT_REPAIR_PROMPT},
                    ]
                },
            )
            self.assertFalse(_commit_requested(run_dir, state))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                self.commit_architecture(workspace)
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
            self.assertEqual(calls[0]["prompt"], COMMIT_REPAIR_PROMPT)
            self.assertEqual(calls[0]["resume_session_id"], "session-1")

    def test_result_then_state_interruption_recovers_without_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                if prompt.startswith("/engineering-architecture"):
                    self.write_architecture(workspace)
                else:
                    self.commit_architecture(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            original_write_state = architecture_step.write_state

            def interrupt_final_state(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("模拟状态写入中断")
                original_write_state(target, value)

            with patch.object(
                architecture_step, "write_state", side_effect=interrupt_final_state
            ):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=fake_agent,
                        decision_runner=completed,
                        config_loader=lambda: object(),
                    )
            self.assertEqual(
                json.loads((run_dir / "steps/09.json").read_text(encoding="utf-8"))["status"],
                "success",
            )

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("结果已成功时不得再次调用 Agent")

            recovered = self.run_step(
                run_dir,
                read_state(run_dir),
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(recovered["status"], "success")
            self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_success_is_idempotent_and_rejects_later_document_or_repository_drift(self) -> None:
        for mutation in ("document", "outside"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))

                async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    if prompt.startswith("/engineering-architecture"):
                        self.write_architecture(workspace)
                    else:
                        self.commit_architecture(workspace)
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
                successful_state = read_state(run_dir)

                async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("既有成功不得调用 Agent")

                reused = self.run_step(
                    run_dir,
                    successful_state,
                    agent_runner=unexpected,
                    decision_runner=unexpected,
                )
                self.assertIn("确认既有成功", reused["summary"])
                if mutation == "document":
                    (workspace / ARCHITECTURE_PATH).write_text("漂移\n", encoding="utf-8")
                else:
                    (workspace / "README.md").write_text("漂移\n", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    self.run_step(
                        run_dir,
                        successful_state,
                        agent_runner=unexpected,
                        decision_runner=unexpected,
                    )

    def test_production_git_reads_use_only_allowlisted_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            with patch.object(architecture_step.subprocess, "run", wraps=subprocess.run) as mocked:
                architecture_step.validate_inputs(run_dir, state)
                architecture_step._verify_worktree_boundary(
                    workspace, ["root", "frontend"]
                )
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
                (
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    ARCHITECTURE_PATH.as_posix(),
                ),
            }
            self.assertTrue(commands)
            self.assertTrue(all(command_args in allowed for command_args in commands))
            for forbidden in ("add", "commit", "switch", "checkout", "reset", "log", "diff"):
                self.assertNotIn(forbidden, {args[0] for args in commands})

    def test_cli_nonprotected_step_overwrites_prior_success_on_failure(self) -> None:
        import run_step as cli

        run_dir = DEMO_ROOT / "runs" / "step-seven-success-overwrite-test"
        if run_dir.exists():
            self.skipTest("本地 demo runs 已存在 step-seven-success-overwrite-test")
        try:
            (run_dir / "steps").mkdir(parents=True)
            write_state(
                run_dir,
                {"status": "success", "step": 7, "current_step": 7},
            )
            write_json(
                run_dir / "steps/07.json",
                {
                    "step": 7,
                    "name": "总体技术方案",
                    "status": "success",
                    "summary": "已完成",
                    "applicable": True,
                    "outputs": ["docs/design/技术方案.md"],
                    "blocked": None,
                    "error": None,
                },
            )
            args = Namespace(
                step=7,
                product_draft=None,
                workspace_root=None,
                catalog_path=None,
                run_id=run_dir.name,
            )
            with (
                patch.object(cli, "parse_args", return_value=args),
                patch.object(cli, "run_step_seven", side_effect=OSError("模拟失败")),
            ):
                self.assertEqual(cli.main(), 1)
            overwritten = json.loads(
                (run_dir / "steps/07.json").read_text(encoding="utf-8")
            )
            self.assertEqual(overwritten["status"], "failed")
            self.assertFalse(cli.has_step_success(run_dir, 7))
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)

    def test_cli_incomplete_step_nine_success_is_not_protected(self) -> None:
        import run_step as cli

        run_dir = DEMO_ROOT / "runs" / "step-nine-incomplete-success-test"
        if run_dir.exists():
            self.skipTest("本地 demo runs 已存在 step-nine-incomplete-success-test")
        try:
            (run_dir / "steps").mkdir(parents=True)
            write_state(
                run_dir,
                {
                    "status": "success",
                    "step": 10,
                    "current_step": 10,
                    "current_node": NEXT_NODE,
                },
            )
            write_json(run_dir / "steps/09.json", {"status": "success"})
            args = Namespace(
                step=9,
                product_draft=None,
                workspace_root=None,
                catalog_path=None,
                run_id=run_dir.name,
            )
            with (
                patch.object(cli, "parse_args", return_value=args),
                patch.object(cli, "run_step_nine", side_effect=OSError("模拟失败")),
            ):
                self.assertEqual(cli.main(), 1)
            failed_result = json.loads(
                (run_dir / "steps/09.json").read_text(encoding="utf-8")
            )
            failed_state = read_state(run_dir)
            self.assertEqual(failed_result["status"], "failed")
            self.assertEqual(failed_state["status"], "failed")
            self.assertEqual(failed_state["step"], 9)
            self.assertEqual(failed_state["current_node"], CURRENT_NODE)
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)

    def test_cli_step_nine_and_generic_success_protection(self) -> None:
        import run_step as cli

        run_dir = DEMO_ROOT / "runs" / "step-nine-cli-test"
        if run_dir.exists():
            self.skipTest("本地 demo runs 已存在 step-nine-cli-test")
        try:
            (run_dir / "steps").mkdir(parents=True)
            write_state(
                run_dir,
                {
                    "status": "running",
                    "step": 9,
                    "current_step": 9,
                    "current_node": CURRENT_NODE,
                },
            )
            args = Namespace(
                step=9,
                product_draft=None,
                workspace_root=None,
                catalog_path=None,
                run_id=run_dir.name,
            )
            success = result(
                "success", "已完成", outputs=[ARCHITECTURE_PATH.as_posix()]
            )
            blocked_error = EngineeringArchitectureBlocked(
                "缺少授权", ["外部授权"], [ARCHITECTURE_PATH.as_posix()]
            )
            with (
                patch.object(cli, "parse_args", return_value=args),
                patch.object(cli, "run_step_nine", side_effect=blocked_error),
            ):
                self.assertEqual(cli.main(), 1)
            blocked_result = json.loads(
                (run_dir / "steps/09.json").read_text(encoding="utf-8")
            )
            self.assertEqual(blocked_result["status"], "blocked")
            self.assertEqual(blocked_result["outputs"], [ARCHITECTURE_PATH.as_posix()])
            self.assertEqual(read_state(run_dir)["current_node"], CURRENT_NODE)

            with (
                patch.object(cli, "parse_args", return_value=args),
                patch.object(cli, "run_step_nine", return_value=(run_dir, success)) as runner,
            ):
                self.assertEqual(cli.main(), 0)
            runner.assert_called_once()
            self.assertEqual(
                json.loads((run_dir / "steps/09.json").read_text(encoding="utf-8")),
                success,
            )

            protected_state = {
                "status": "success",
                "phase": "project_initialization",
                "step": 10,
                "current_step": 10,
                "current_node": NEXT_NODE,
                "blocked": None,
                "error": None,
            }
            write_state(run_dir, protected_state)
            with (
                patch.object(cli, "parse_args", return_value=args),
                patch.object(cli, "run_step_nine", side_effect=OSError("模拟中断")),
            ):
                self.assertEqual(cli.main(), 1)
            self.assertEqual(
                json.loads((run_dir / "steps/09.json").read_text(encoding="utf-8")),
                success,
            )
            self.assertEqual(read_state(run_dir), protected_state)
            for step in (5, 7):
                write_json(run_dir / f"steps/{step:02d}.json", {"status": "success"})
                self.assertFalse(cli.has_step_success(run_dir, step))
                write_json(
                    run_dir / f"steps/{step:02d}.json",
                    {
                        "step": step,
                        "name": f"测试步骤 {step}",
                        "status": "success",
                        "summary": "已完成",
                        "applicable": True,
                        "outputs": [],
                        "blocked": None,
                        "error": None,
                    },
                )
                self.assertFalse(cli.has_step_success(run_dir, step))

            write_json(run_dir / "steps/08.json", {"status": "success"})
            self.assertFalse(cli.has_step_success(run_dir, 8))
            step_eight_success = {
                "step": 8,
                "name": "首次提交适用仓库",
                "status": "success",
                "summary": "已完成首次提交",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "applicable_repositories": ["root", "frontend", "backend"],
                "repositories": [
                    {
                        "name": "root",
                        "path": ".",
                        "branch": "main",
                        "worktree_clean": True,
                    },
                    {
                        "name": "frontend",
                        "path": "frontend",
                        "branch": "main",
                        "worktree_clean": True,
                    },
                    {
                        "name": "backend",
                        "path": "backend",
                        "branch": "main",
                        "worktree_clean": True,
                    },
                ],
            }
            write_json(run_dir / "steps/08.json", step_eight_success)
            self.assertTrue(cli.has_step_success(run_dir, 8))

            write_json(run_dir / "steps/09.json", {"status": "success"})
            self.assertFalse(cli.has_step_success(run_dir, 9))
            write_json(run_dir / "steps/09.json", success)
            self.assertTrue(cli.has_step_success(run_dir, 9))
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)


if __name__ == "__main__":
    unittest.main()
