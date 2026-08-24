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
from steps.step_10_ui_ux_framework.step import (
    ARCHITECTURE_OUTPUT_PATH,
    COMMIT_REPAIR_PROMPT,
    CONVERSATION_KEY,
    CURRENT_NODE,
    FRAMEWORK_PATH,
    FRAMEWORK_REPAIR_PROMPT,
    NEXT_NODE,
    UI_UX_FRAMEWORK_MAX_BUDGET_USD,
    UI_UX_FRAMEWORK_MAX_TURNS,
    UIUXFrameworkBlocked,
    _commit_requested,
    framework_repair,
    run,
)
import steps.step_10_ui_ux_framework.step as ui_ux_step


def command(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=check
    )


def commit_paths(repository: Path, *paths: str, message: str = "test commit") -> None:
    command("add", "--", *paths, cwd=repository)
    if command("status", "--porcelain=v1", cwd=repository).stdout:
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
    skills = ["ui-ux-framework", "commit-changes"]
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


class UIUXFrameworkTests(unittest.TestCase):
    def make_run(
        self,
        root: Path,
        children: list[str] | None = None,
        *,
        existing_framework: bool = False,
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
        for path in [*product_outputs, checklist, design, ARCHITECTURE_OUTPUT_PATH.as_posix()]:
            (workspace / path).write_text(f"# {Path(path).stem}\n\n有效内容。\n", encoding="utf-8")
        if existing_framework:
            (workspace / FRAMEWORK_PATH).parent.mkdir(parents=True)
            (workspace / FRAMEWORK_PATH).write_text(
                "# 产品级 UI/UX 框架\n\n既有有效内容。\n", encoding="utf-8"
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
        root_paths = [*product_outputs, checklist, design, ARCHITECTURE_OUTPUT_PATH.as_posix()]
        if existing_framework:
            root_paths.append(FRAMEWORK_PATH.as_posix())
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
        write_json(
            run_dir / "steps/09.json",
            {
                "step": 9,
                "name": "工程架构设计",
                "status": "success",
                "summary": "已完成",
                "applicable": True,
                "outputs": [ARCHITECTURE_OUTPUT_PATH.as_posix()],
                "blocked": None,
                "error": None,
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
            "step": 10,
            "current_step": 10,
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
    def write_framework(workspace: Path) -> None:
        (workspace / FRAMEWORK_PATH).parent.mkdir(parents=True, exist_ok=True)
        (workspace / FRAMEWORK_PATH).write_text(
            "# 产品级 UI/UX 框架\n\n体验原则、信息框架与可访问性基线。\n",
            encoding="utf-8",
        )

    @staticmethod
    def commit_framework(workspace: Path) -> None:
        commit_paths(workspace, FRAMEWORK_PATH.as_posix(), message="docs: 产品级 UI/UX 框架")

    def test_inapplicable_short_circuits_without_execution_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["backend"])

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("不适用路径不得调用 Agent")

            async def unexpected_decision(*args: object, **kwargs: object) -> object:
                raise AssertionError("不适用路径不得请求负责人决定")

            def unexpected_config() -> object:
                raise AssertionError("不适用路径不得加载 LLM 配置")

            with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                saved = self.run_step(
                    run_dir,
                    state,
                    agent_runner=unexpected_agent,
                    decision_runner=unexpected_decision,
                    config_loader=unexpected_config,
                )
            self.assertFalse(saved["applicable"])
            self.assertEqual(saved["outputs"], [])
            self.assertEqual(git_run.call_count, 0)
            completed = read_state(run_dir)
            self.assertEqual((completed["step"], completed["current_node"]), (11, NEXT_NODE))
            self.assertNotIn(CONVERSATION_KEY, completed)
            self.assertNotIn("claude_sessions", completed)
            self.assertNotIn("decision_conversations", completed)
            self.assertFalse((run_dir / "conversations").exists())
            self.assertFalse((workspace / "docs/ui-ux").exists())

    def test_inapplicable_rejects_invalid_step_nine_without_execution_side_effects(self) -> None:
        for case in ("missing", "incomplete", "wrong-outputs"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["backend"])
                step_nine = run_dir / "steps/09.json"
                if case == "missing":
                    step_nine.unlink()
                elif case == "incomplete":
                    write_json(step_nine, {"step": 9, "status": "success"})
                else:
                    invalid = json.loads(step_nine.read_text(encoding="utf-8"))
                    invalid["outputs"] = ["docs/design/other.md"]
                    write_json(step_nine, invalid)
                state_before = (run_dir / "state.json").read_bytes()

                async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("无效第 9 步结果不得调用 Agent")

                async def unexpected_decision(*args: object, **kwargs: object) -> object:
                    raise AssertionError("无效第 9 步结果不得请求决定")

                def unexpected_config() -> object:
                    raise AssertionError("无效第 9 步结果不得加载 LLM 配置")

                with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                    with self.assertRaises(RuntimeError):
                        self.run_step(
                            run_dir,
                            state,
                            agent_runner=unexpected_agent,
                            decision_runner=unexpected_decision,
                            config_loader=unexpected_config,
                        )
                self.assertEqual(git_run.call_count, 0)
                self.assertEqual((run_dir / "state.json").read_bytes(), state_before)
                self.assertFalse((run_dir / "steps/10.json").exists())
                self.assertFalse((workspace / "docs/ui-ux").exists())
                self.assertFalse((run_dir / "conversations").exists())

    def test_inapplicable_rejects_preexisting_execution_artifacts_read_only(self) -> None:
        for artifact in ("session", "reference", "private", "history", "history-symlink"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir, workspace, state = self.make_run(root, ["backend"])
                if artifact == "session":
                    state["claude_sessions"] = {CONVERSATION_KEY: "session-1"}
                elif artifact == "reference":
                    state["decision_conversations"] = {
                        CONVERSATION_KEY: {"path": f"conversations/{CONVERSATION_KEY}.json"}
                    }
                elif artifact == "private":
                    state[CONVERSATION_KEY] = {}
                else:
                    conversations = run_dir / "conversations"
                    conversations.mkdir()
                    history = conversations / f"{CONVERSATION_KEY}.json"
                    if artifact == "history":
                        write_json(history, {"messages": [{"role": "system", "content": "x"}]})
                    else:
                        external = root / "external-history.json"
                        write_json(external, {"messages": [{"role": "system", "content": "x"}]})
                        history.symlink_to(external)
                write_state(run_dir, state)
                state_before = (run_dir / "state.json").read_bytes()

                async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("伪造不适用执行产物不得调用 Agent")

                async def unexpected_decision(*args: object, **kwargs: object) -> object:
                    raise AssertionError("伪造不适用执行产物不得请求决定")

                def unexpected_config() -> object:
                    raise AssertionError("伪造不适用执行产物不得加载 LLM 配置")

                with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                    with self.assertRaisesRegex(RuntimeError, "既有执行产物|决策历史"):
                        self.run_step(
                            run_dir,
                            state,
                            agent_runner=unexpected_agent,
                            decision_runner=unexpected_decision,
                            config_loader=unexpected_config,
                        )
                self.assertEqual(git_run.call_count, 0)
                self.assertEqual((run_dir / "state.json").read_bytes(), state_before)
                self.assertFalse((run_dir / "steps/10.json").exists())
                self.assertFalse((workspace / "docs/ui-ux").exists())
                if artifact in {"session", "reference", "private"}:
                    self.assertFalse((run_dir / "conversations").exists())

    def test_inapplicable_execution_artifacts_are_rejected_after_failed_blocked_or_success(self) -> None:
        for status, artifact in (
            ("failed", "session"),
            ("blocked", "private"),
            ("success", "conversation"),
        ):
            with self.subTest(status=status, artifact=artifact), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["backend"])
                if status == "success":
                    write_json(
                        run_dir / "steps/10.json",
                        ui_ux_step.result(
                            "success", "已确认不适用。", applicable=False
                        ),
                    )
                    state.update(
                        {
                            "status": "success",
                            "step": 11,
                            "current_step": 11,
                            "current_node": NEXT_NODE,
                        }
                    )
                else:
                    state["status"] = status
                if artifact == "session":
                    state["claude_sessions"] = {CONVERSATION_KEY: "session-1"}
                elif artifact == "private":
                    state[CONVERSATION_KEY] = {}
                else:
                    conversations = run_dir / "conversations"
                    conversations.mkdir()
                    write_json(
                        conversations / f"{CONVERSATION_KEY}.json",
                        {"messages": [{"role": "system", "content": "x"}]},
                    )
                write_state(run_dir, state)
                state_before = (run_dir / "state.json").read_bytes()

                async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("不适用执行产物不得调用 Agent")

                async def unexpected_decision(*args: object, **kwargs: object) -> object:
                    raise AssertionError("不适用执行产物不得请求决定")

                def unexpected_config() -> object:
                    raise AssertionError("不适用执行产物不得加载 LLM 配置")

                with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                    with self.assertRaisesRegex(RuntimeError, "不适用.*既有执行产物"):
                        self.run_step(
                            run_dir,
                            state,
                            agent_runner=unexpected_agent,
                            decision_runner=unexpected_decision,
                            config_loader=unexpected_config,
                        )
                self.assertEqual(git_run.call_count, 0)
                self.assertEqual((run_dir / "state.json").read_bytes(), state_before)
                self.assertFalse((workspace / "docs/ui-ux").exists())

    def test_inapplicable_result_state_interruption_and_idempotence_stay_execution_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["backend"])
            original_write_state = ui_ux_step.write_state

            def interrupt_final_state(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("模拟状态写入中断")
                original_write_state(target, value)

            with patch.object(ui_ux_step, "write_state", side_effect=interrupt_final_state):
                with self.assertRaises(OSError):
                    self.run_step(run_dir, state)
            saved = json.loads((run_dir / "steps/10.json").read_text(encoding="utf-8"))
            self.assertEqual((saved["status"], saved["applicable"], saved["outputs"]), ("success", False, []))

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("不适用恢复不得调用 Agent")

            async def unexpected_decision(*args: object, **kwargs: object) -> object:
                raise AssertionError("不适用恢复不得请求决定")

            with patch.object(ui_ux_step.subprocess, "run", wraps=subprocess.run) as git_run:
                recovered = self.run_step(
                    run_dir,
                    read_state(run_dir),
                    agent_runner=unexpected_agent,
                    decision_runner=unexpected_decision,
                    config_loader=lambda: (_ for _ in ()).throw(AssertionError("不得加载配置")),
                )
                repeated = self.run_step(
                    run_dir,
                    read_state(run_dir),
                    agent_runner=unexpected_agent,
                    decision_runner=unexpected_decision,
                )
            self.assertFalse(recovered["applicable"])
            self.assertFalse(repeated["applicable"])
            self.assertEqual(git_run.call_count, 0)
            self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)
            self.assertFalse((workspace / "docs/ui-ux").exists())

    def test_handoff_mismatch_is_rejected_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            state["applicable_repositories"] = ["root", "backend"]
            write_state(run_dir, state)

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("交接不一致时不得调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "第 8 步仓库 clean 交接状态"):
                self.run_step(run_dir, state, agent_runner=unexpected)

    def test_applicable_prompt_uses_step_nine_output_and_authoritative_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend", "backend"])
            architecture_content = "# 工程架构设计\n\n来自第九步的前端边界。\n"
            (workspace / ARCHITECTURE_OUTPUT_PATH).write_text(architecture_content, encoding="utf-8")
            commit_paths(workspace, ARCHITECTURE_OUTPUT_PATH.as_posix())
            prompts: list[str] = []
            agent_calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                agent_calls.append(kwargs)
                if prompt.startswith("/ui-ux-framework"):
                    self.write_framework(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_framework(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                for required in (
                    "# 项目需求说明",
                    "# 产品功能说明",
                    "# 项目准备清单",
                    "# 技术方案",
                    "来自第九步的前端边界",
                    '"frontend"',
                    FRAMEWORK_PATH.as_posix(),
                ):
                    self.assertIn(required, system_prompt)
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            prompt = prompts[0]
            self.assertEqual(saved["outputs"], [FRAMEWORK_PATH.as_posix()])
            self.assertTrue(prompt.startswith("/ui-ux-framework\n"))
            for required in (
                "docs/requirements/项目需求说明.md",
                "docs/requirements/产品功能说明.md",
                "docs/requirements/项目准备清单.md",
                "docs/design/技术方案.md",
                ARCHITECTURE_OUTPUT_PATH.as_posix(),
                "@./frontend",
                FRAMEWORK_PATH.as_posix(),
                "bootstrap",
                "高影响方向",
                "单项需求设计",
                "页面、CSS、组件或主题",
            ):
                self.assertIn(required, prompt)
            for forbidden in ("第 10 步", "PCM", "节点", "session", "Skill", "/commit-changes"):
                self.assertNotIn(forbidden, prompt)
            self.assertEqual(prompts[1], COMMIT_REPAIR_PROMPT)
            self.assertNotEqual(prompts[0], COMMIT_REPAIR_PROMPT)
            self.assertNotEqual(prompts[0], FRAMEWORK_REPAIR_PROMPT)
            self.assertEqual(
                [call for call in prompts if call == COMMIT_REPAIR_PROMPT], [COMMIT_REPAIR_PROMPT]
            )
            self.assertEqual(agent_calls[0]["max_turns"], UI_UX_FRAMEWORK_MAX_TURNS)
            self.assertEqual(
                agent_calls[0]["max_budget_usd"], UI_UX_FRAMEWORK_MAX_BUDGET_USD
            )

    def test_step_nine_output_requires_the_fixed_unique_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            step_nine = json.loads((run_dir / "steps/09.json").read_text(encoding="utf-8"))
            step_nine["outputs"] = ["docs/design/other.md"]
            write_json(run_dir / "steps/09.json", step_nine)
            with self.assertRaisesRegex(RuntimeError, "第 9 步工程架构设计结果不可复用"):
                self.run_step(run_dir, state)

    def test_document_repair_then_commit_uses_the_original_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if prompt == FRAMEWORK_REPAIR_PROMPT:
                    self.write_framework(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_framework(workspace)
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
            self.assertTrue(calls[0]["prompt"].startswith("/ui-ux-framework"))
            self.assertEqual(
                [call["prompt"] for call in calls[1:]],
                [FRAMEWORK_REPAIR_PROMPT, COMMIT_REPAIR_PROMPT],
            )
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(
                [call["resume_session_id"] for call in calls[1:]], ["session-1", "session-1"]
            )

    def test_commit_anchor_requires_exact_prompt_immediate_nonempty_agent_reply_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            conversations = run_dir / "conversations"
            conversations.mkdir()
            path = conversations / f"{CONVERSATION_KEY}.json"
            state["claude_sessions"] = {CONVERSATION_KEY: "session-1"}
            state["decision_conversations"] = {
                CONVERSATION_KEY: {"path": f"conversations/{CONVERSATION_KEY}.json"}
            }
            for tail, expected in (
                ([{"role": "assistant", "content": COMMIT_REPAIR_PROMPT}], False),
                (
                    [
                        {"role": "assistant", "content": COMMIT_REPAIR_PROMPT + "\n"},
                        {"role": "user", "content": "已提交"},
                    ],
                    False,
                ),
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
                        {"role": "user", "content": "已提交固定文档"},
                    ],
                    True,
                ),
            ):
                with self.subTest(tail=tail):
                    write_json(path, {"messages": [{"role": "system", "content": "x"}, *tail]})
                    self.assertEqual(_commit_requested(run_dir, state), expected)
            state.pop("claude_sessions")
            self.assertFalse(_commit_requested(run_dir, state))

    def test_root_or_child_changes_fail_before_owner_decision(self) -> None:
        for mutation in ("initial-root", "initial-child", "agent-root", "agent-child"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
                decision_called = False
                if mutation == "initial-root":
                    (workspace / "README.md").write_text("dirty\n", encoding="utf-8")
                elif mutation == "initial-child":
                    (workspace / "frontend/unexpected.txt").write_text("dirty\n", encoding="utf-8")

                async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    if mutation.startswith("agent"):
                        self.write_framework(workspace)
                        target = workspace if mutation == "agent-root" else workspace / "frontend"
                        (target / "unexpected.txt").write_text("dirty\n", encoding="utf-8")
                    value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index, operator]
                    return value

                async def unexpected_decision(messages, config, *, system_prompt):
                    nonlocal decision_called
                    decision_called = True
                    raise AssertionError("越界修改不得进入负责人裁决")

                message = "子仓库" if "child" in mutation else "范围外"
                with self.assertRaisesRegex(RuntimeError, message if mutation.startswith("initial") else "AI-compatible 决策失败"):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=unexpected_decision,
                        config_loader=lambda: object(),
                    )
                self.assertFalse(decision_called)

    def test_fresh_and_recovery_execution_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            state["claude_sessions"] = {CONVERSATION_KEY: "forged"}
            write_state(run_dir, state)

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("fresh 锚点伪造时不得调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "新鲜.*既有执行产物"):
                self.run_step(run_dir, state, agent_runner=unexpected)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            state.update(
                {
                    "status": "failed",
                    "claude_sessions": {CONVERSATION_KEY: "session-1"},
                    "decision_conversations": {
                        CONVERSATION_KEY: {"path": f"conversations/{CONVERSATION_KEY}.json"}
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
                        {"role": "user", "content": "中断前完整 Agent 回复"},
                    ]
                },
            )
            calls: list[str] = []
            decisions = 0

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append(prompt)
                if prompt == FRAMEWORK_REPAIR_PROMPT:
                    self.write_framework(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_framework(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                nonlocal decisions
                decisions += 1
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertGreaterEqual(decisions, 1)
            self.assertEqual(calls, [FRAMEWORK_REPAIR_PROMPT, COMMIT_REPAIR_PROMPT])
            self.assertTrue(all(call != "/ui-ux-framework" for call in calls))

    def test_blocked_resumes_original_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            calls: list[dict] = []
            verdicts = ["blocked", "completed", "completed"]

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if prompt.startswith("/ui-ux-framework"):
                    self.write_framework(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_framework(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def decide(messages, config, *, system_prompt):
                verdict = verdicts.pop(0)
                if verdict == "blocked":
                    return decision("blocked", reason="缺少授权", required_inputs=["外部授权"])
                return decision("completed")

            with self.assertRaises(UIUXFrameworkBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            saved = self.run_step(
                run_dir,
                read_state(run_dir),
                agent_runner=fake_agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls[1]["prompt"], BLOCKED_RESUME_PROMPT)
            self.assertEqual(calls[1]["resume_session_id"], "session-1")

    def test_conversation_and_document_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _workspace, state = self.make_run(root, ["frontend"])
            external = root / "external-conversations"
            external.mkdir()
            (run_dir / "conversations").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "conversations.*非符号链接目录"):
                self.run_step(run_dir, state)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _workspace, state = self.make_run(root, ["frontend"])
            conversations = run_dir / "conversations"
            conversations.mkdir()
            target = root / "external-history.json"
            write_json(target, {"messages": [{"role": "system", "content": "x"}]})
            (conversations / f"{CONVERSATION_KEY}.json").symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "非符号链接普通文件"):
                self.run_step(run_dir, state)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, workspace, _state = self.make_run(root, ["frontend"])
            target = root / "external-framework.md"
            target.write_text("外部内容\n", encoding="utf-8")
            (workspace / FRAMEWORK_PATH).parent.mkdir(parents=True)
            (workspace / FRAMEWORK_PATH).symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "不能包含符号链接"):
                framework_repair(workspace)
            self.assertTrue(run_dir.is_dir())

    def test_success_interruption_recovers_idempotently_and_rejects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                if prompt.startswith("/ui-ux-framework"):
                    self.write_framework(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_framework(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            original_write_state = ui_ux_step.write_state

            def interrupt_final_state(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("模拟状态写入中断")
                original_write_state(target, value)

            with patch.object(ui_ux_step, "write_state", side_effect=interrupt_final_state):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=fake_agent,
                        decision_runner=completed,
                        config_loader=lambda: object(),
                    )
            self.assertEqual(
                json.loads((run_dir / "steps/10.json").read_text(encoding="utf-8"))["status"],
                "success",
            )

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("已有成功不得再次调用 Agent 或决定服务")

            recovered = self.run_step(
                run_dir,
                read_state(run_dir),
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            repeated = self.run_step(
                run_dir,
                read_state(run_dir),
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertIn("确认既有成功", repeated["summary"])
            self.assertEqual(recovered["status"], "success")
            (workspace / FRAMEWORK_PATH).write_text("漂移\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "漂移"):
                self.run_step(run_dir, read_state(run_dir), agent_runner=unexpected)

    def test_production_git_reads_are_allowlisted(self) -> None:
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
                (
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    FRAMEWORK_PATH.as_posix(),
                ),
            }
            self.assertTrue(commands)
            self.assertTrue(all(item in allowed for item in commands))
            self.assertFalse({"add", "commit", "switch", "checkout", "reset", "log", "diff"} & {item[0] for item in commands})


if __name__ == "__main__":
    unittest.main()
