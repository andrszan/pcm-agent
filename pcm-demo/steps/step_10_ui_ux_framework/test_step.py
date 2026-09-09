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
from steps.step_10_ui_ux_framework.step import (
    ARCHITECTURE_OUTPUT_PATH,
    CONVERSATION_KEY,
    CURRENT_NODE,
    FRAMEWORK_PATH,
    NEXT_NODE,
    UIUXFrameworkBlocked,
    framework_repair,
    run,
)
import steps.step_10_ui_ux_framework.step as ui_ux_step


def command(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def commit_paths(repository: Path, *paths: str) -> None:
    command("add", "--", *paths, cwd=repository)
    if command("status", "--porcelain=v1", cwd=repository).stdout:
        command("-c", "user.name=PCM Test", "-c", "user.email=pcm@example.invalid", "commit", "-m", "test commit", cwd=repository)


def agent_result(cwd: Path) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={"cwd": str(cwd), "skills": ["ui-ux-framework", "commit-changes"], "slash_commands": ["ui-ux-framework", "commit-changes"]},
        text="已处理", result_subtype="success", is_error=False, session_id="session-1",
        stop_reason="end_turn", num_turns=1, total_cost_usd=0.1, exception=None,
    )


def decision(verdict: str, *, reason: str = "已核验") -> tuple[dict, int, str]:
    value = {"verdict": verdict, "answer": "", "reason": reason, "required_inputs": ["外部授权"] if verdict == "blocked" else []}
    return value, 1, json.dumps(value, ensure_ascii=False)


class UIUXFrameworkTests(unittest.TestCase):
    def make_run(self, root: Path, children: list[str] | None = None, *, existing: bool = False) -> tuple[Path, Path, dict]:
        children = children or []
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        (workspace / "docs/requirements").mkdir(parents=True)
        (workspace / "docs/design").mkdir(parents=True)
        outputs = ["docs/requirements/项目需求说明.md", "docs/requirements/产品功能说明.md"]
        checklist = "docs/requirements/项目准备清单.md"
        design = "docs/design/技术方案.md"
        for path in [*outputs, checklist, design, ARCHITECTURE_OUTPUT_PATH.as_posix()]:
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
        root_paths = [*outputs, checklist, design, ARCHITECTURE_OUTPUT_PATH.as_posix()]
        if existing:
            root_paths.append(FRAMEWORK_PATH.as_posix())
        commit_paths(workspace, *root_paths)
        write_json(run_dir / "steps/02.json", {"step": 2, "status": "success", "outputs": outputs})
        write_json(
            run_dir / "steps/05.json",
            readiness_result(
                "success",
                "准备基线已完成。",
                outputs=[checklist],
                readiness_baseline=readiness_baseline(workspace, outputs),
            ),
        )
        write_json(run_dir / "steps/07.json", {"step": 7, "status": "success", "applicable": True, "outputs": [design]})
        write_json(run_dir / "steps/09.json", {"step": 9, "name": "工程架构设计", "status": "success", "summary": "完成", "applicable": True, "outputs": [ARCHITECTURE_OUTPUT_PATH.as_posix()], "blocked": None, "error": None})
        names = ["root", *children]
        write_json(run_dir / "steps/08.json", {"step": 8, "status": "success", "applicable": True, "outputs": [], "applicable_repositories": names, "repositories": [{"unexpected": True}]})
        state = {
            "status": "success",
            "phase": "project_initialization",
            "step": 10,
            "current_step": 10,
            "current_node": CURRENT_NODE,
            "workspace": {
                "root": str(workspace_root),
                "final_path": str(workspace),
            },
            "applicable_repositories": names,
            "repositories": [],
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    @staticmethod
    def write_document(workspace: Path) -> None:
        (workspace / FRAMEWORK_PATH).parent.mkdir(parents=True, exist_ok=True)
        (workspace / FRAMEWORK_PATH).write_text("# UI/UX\n\n有效内容。\n", encoding="utf-8")

    @staticmethod
    def commit_document(workspace: Path) -> None:
        commit_paths(workspace, FRAMEWORK_PATH.as_posix())

    @staticmethod
    def run_step(run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    async def completed(self, *_args: object, **_kwargs: object) -> tuple[dict, int, str]:
        return decision("completed")

    def test_inapplicable_has_no_agent_git_or_llm_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["backend"])

            async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                raise AssertionError("不适用路径不得执行")

            with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                saved = self.run_step(run_dir, state, agent_runner=unexpected, decision_runner=unexpected, config_loader=lambda: (_ for _ in ()).throw(AssertionError("不得加载配置")))
            self.assertFalse(saved["applicable"])
            self.assertEqual(git_run.call_count, 0)
            self.assertFalse((workspace / "docs/ui-ux").exists())

    def test_inapplicable_rejects_readiness_baseline_drift(self) -> None:
        for relative in (
            "docs/requirements/项目准备清单.md",
            "docs/requirements/项目需求说明.md",
            "docs/requirements/产品功能说明.md",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["backend"])
                (workspace / relative).write_text("# 漂移内容\n", encoding="utf-8")

                async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("准备基线漂移不得执行 Agent 或决策")

                with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                    with self.assertRaisesRegex(RuntimeError, "准备基线不可复用"):
                        self.run_step(
                            run_dir,
                            state,
                            agent_runner=unexpected,
                            decision_runner=unexpected,
                            config_loader=lambda: (_ for _ in ()).throw(
                                AssertionError("不得加载配置")
                            ),
                        )
                self.assertEqual(git_run.call_count, 0)

    def test_inapplicable_rejects_execution_artifact_by_presence_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["backend"])
            (run_dir / "conversations").mkdir()
            (run_dir / "conversations" / f"{CONVERSATION_KEY}.json").write_text("not json", encoding="utf-8")
            async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                raise AssertionError("不得执行")
            with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                with self.assertRaisesRegex(RuntimeError, "既有执行产物"):
                    self.run_step(run_dir, state, agent_runner=unexpected, decision_runner=unexpected, config_loader=lambda: (_ for _ in ()).throw(AssertionError("不得加载配置")))
            self.assertEqual(git_run.call_count, 0)

    def test_step_eight_handoff_uses_names_not_replayed_repository_facts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            workspace, names = ui_ux_step._step_eight_handoff(run_dir, state)
            self.assertTrue(workspace.is_dir())
            self.assertEqual(names, ["root", "frontend"])
            state["applicable_repositories"] = ["root"]
            with self.assertRaisesRegex(RuntimeError, "交接状态"):
                ui_ux_step._step_eight_handoff(run_dir, state)

    def test_dirty_document_commits_once_and_clean_tracked_skips_commit(self) -> None:
        for existing, expected_commits in ((False, 1), (True, 0)):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"], existing=existing)
                prompts: list[str] = []
                async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    prompts.append(prompt)
                    if prompt.startswith("/ui-ux-framework") and not existing:
                        self.write_document(workspace)
                    elif prompt.splitlines()[0] == "/commit-changes":
                        self.commit_document(workspace)
                    value = agent_result(kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index,operator]
                    return value
                saved = self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
                self.assertEqual(saved["status"], "success")
                self.assertEqual(sum(item.splitlines()[0] == "/commit-changes" for item in prompts), expected_commits)

    def test_document_repair_then_commit_reuses_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            calls: list[tuple[str, str | None]] = []
            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append((prompt, kwargs["resume_session_id"]))  # type: ignore[index]
                if prompt.startswith("固定产品级 UI/UX 框架文档缺失"):
                    self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes":
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value
            self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
            self.assertEqual([session for prompt, session in calls if prompt.startswith("固定产品级 UI/UX 框架文档缺失") or prompt.splitlines()[0] == "/commit-changes"], ["session-1", "session-1"])

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
                    (workspace / FRAMEWORK_PATH).parent.mkdir(parents=True)
                    (workspace / FRAMEWORK_PATH).symlink_to(target)
                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state)
                if mutation == "symlink":
                    with self.assertRaisesRegex(RuntimeError, "符号链接"):
                        framework_repair(workspace)
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as handle:
                handle.write(f"{FRAMEWORK_PATH.as_posix()}\n")
            self.write_document(workspace)
            prompts: list[str] = []
            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value
            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
            self.assertFalse(any(item.splitlines()[0] == "/commit-changes" for item in prompts))

    def test_fresh_rejects_state_or_invalid_history_by_presence_only(self) -> None:
        for artifact in ("session", "reference", "section", "history"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as directory:
                run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
                if artifact == "session": state["claude_sessions"] = {CONVERSATION_KEY: "forged"}
                elif artifact == "reference": state["decision_conversations"] = {CONVERSATION_KEY: {"path": "wrong"}}
                elif artifact == "section": state[CONVERSATION_KEY] = "wrong"
                else:
                    (run_dir / "conversations").mkdir()
                    (run_dir / "conversations" / f"{CONVERSATION_KEY}.json").write_text("not json", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "既有执行产物"):
                    self.run_step(run_dir, state)

    def test_result_state_interruption_recovers_without_agent_or_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                if prompt.startswith("/ui-ux-framework"): self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes": self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value
            original = ui_ux_step.write_state
            def interrupt(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE: raise OSError("interrupted")
                original(target, value)
            with patch.object(ui_ux_step, "write_state", side_effect=interrupt):
                with self.assertRaises(OSError):
                    self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
            async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                raise AssertionError("不得恢复执行")
            self.assertEqual(self.run_step(run_dir, read_state(run_dir), agent_runner=unexpected, decision_runner=unexpected)["status"], "success")

    def test_blocked_clean_tracked_document_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                if prompt.startswith("/ui-ux-framework"):
                    self.write_document(workspace)
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value
            async def blocked(*_args: object, **_kwargs: object) -> tuple[dict, int, str]:
                return decision("blocked", reason="缺少外部授权")
            with self.assertRaises(UIUXFrameworkBlocked):
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=blocked, config_loader=lambda: object())
            self.assertEqual(json.loads((run_dir / "steps/10.json").read_text(encoding="utf-8"))["status"], "blocked")
            self.assertEqual(read_state(run_dir)["current_node"], CURRENT_NODE)
    def test_applicable_prompt_uses_step_nine_output_and_rejects_wrong_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(
                Path(directory), ["frontend", "backend"]
            )
            prompts: list[str] = []
            decision_prompts: list[str] = []

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                if prompt.startswith("/ui-ux-framework"):
                    self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes":
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            async def decide(
                *_args: object, system_prompt: str, **_kwargs: object
            ) -> tuple[dict, int, str]:
                decision_prompts.append(system_prompt)
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            prompt = prompts[0]
            self.assertTrue(prompt.startswith("/ui-ux-framework\n"))
            for required in (
                "docs/requirements/项目需求说明.md", "docs/requirements/产品功能说明.md",
                "docs/requirements/项目准备清单.md", "docs/design/技术方案.md",
                ARCHITECTURE_OUTPUT_PATH.as_posix(), FRAMEWORK_PATH.as_posix(), "@./frontend",
                "bootstrap 模式", "不得开展单项需求设计", "不得执行 Git 写操作",
            ):
                self.assertIn(required, prompt)
            for forbidden in ("第 10 步", "PCM", "节点", "session", "Skill", "/commit-changes"):
                self.assertNotIn(forbidden, prompt)

            self.assertTrue(decision_prompts)
            for system_prompt in decision_prompts:
                for required in (
                    "固定产品级 UI/UX 框架文档已生成",
                    "前端工程事实核验",
                    "关键体验方向",
                    "真正高影响的具体取舍",
                    "要求 Agent 回写",
                    "不得泛化为待确认",
                ):
                    self.assertIn(required, system_prompt)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            step_nine = json.loads((run_dir / "steps/09.json").read_text(encoding="utf-8"))
            step_nine["outputs"] = ["docs/design/other.md"]
            write_json(run_dir / "steps/09.json", step_nine)

            async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                raise AssertionError("非法第 9 步交接不得执行 Agent")

            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, state, agent_runner=unexpected)

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

    def test_inapplicable_invalid_handoff_and_interruption_stay_execution_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["backend"])
            step_nine = json.loads((run_dir / "steps/09.json").read_text(encoding="utf-8"))
            step_nine["outputs"] = ["docs/design/other.md"]
            write_json(run_dir / "steps/09.json", step_nine)

            async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                raise AssertionError("不适用交接失败不得执行")

            with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                with self.assertRaises(RuntimeError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=unexpected,
                        decision_runner=unexpected,
                        config_loader=lambda: (_ for _ in ()).throw(
                            AssertionError("不得加载配置")
                        ),
                    )
            self.assertEqual(git_run.call_count, 0)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["backend"])
            original = ui_ux_step.write_state

            def interrupt(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("interrupted")
                original(target, value)

            with patch.object(ui_ux_step, "write_state", side_effect=interrupt):
                with self.assertRaises(OSError):
                    self.run_step(run_dir, state)

            async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                raise AssertionError("不适用恢复不得执行")

            with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                recovered = self.run_step(
                    run_dir,
                    read_state(run_dir),
                    agent_runner=unexpected,
                    decision_runner=unexpected,
                    config_loader=lambda: (_ for _ in ()).throw(
                        AssertionError("不得加载配置")
                    ),
                )
                repeated = self.run_step(
                    run_dir,
                    read_state(run_dir),
                    agent_runner=unexpected,
                    decision_runner=unexpected,
                )
            self.assertFalse(recovered["applicable"])
            self.assertFalse(repeated["applicable"])
            self.assertEqual(git_run.call_count, 0)

    def test_blocked_rerun_uses_common_resume_session_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            calls: list[tuple[str, str | None]] = []
            decisions = [decision("blocked", reason="缺少授权"), decision("completed")]

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append((prompt, kwargs["resume_session_id"]))  # type: ignore[index]
                if prompt.startswith("/ui-ux-framework"):
                    self.write_document(workspace)
                elif prompt == BLOCKED_RESUME_PROMPT:
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            async def decide(*_args: object, **_kwargs: object) -> tuple[dict, int, str]:
                return decisions.pop(0)

            with self.assertRaises(UIUXFrameworkBlocked):
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
                    if prompt.startswith("/ui-ux-framework"):
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
                    (workspace / FRAMEWORK_PATH).write_text(
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
            with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as mocked:
                ui_ux_step.validate_inputs(run_dir, state)
                ui_ux_step._verify_worktree_boundary(workspace, ["root", "frontend"])
                ui_ux_step._document_tracked(workspace)
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
                    FRAMEWORK_PATH.as_posix(),
                ),
                ("ls-files", "--error-unmatch", "--", FRAMEWORK_PATH.as_posix()),
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
                    if prompt.startswith("/ui-ux-framework"):
                        self.write_document(workspace)
                    value = agent_result(kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index,operator]
                    return value

                async def blocked(*_args: object, **_kwargs: object) -> tuple[dict, int, str]:
                    return decision("blocked", reason="缺少外部授权")

                with self.assertRaises(UIUXFrameworkBlocked):
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
