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
from steps.step_11_requirement_breakdown.step import (
    ARCHITECTURE_OUTPUT_PATH,
    BACKLOG_PATH,
    CONVERSATION_KEY,
    CURRENT_NODE,
    NEXT_NODE,
    RequirementBreakdownBlocked,
    UI_UX_FRAMEWORK_PATH,
    backlog_repair,
    run,
)
import steps.step_11_requirement_breakdown.step as breakdown_step


def command(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def commit_paths(repository: Path, *paths: str) -> None:
    command("add", "--", *paths, cwd=repository)
    if command("status", "--porcelain=v1", cwd=repository).stdout:
        command("-c", "user.name=PCM Test", "-c", "user.email=pcm@example.invalid", "commit", "-m", "test commit", cwd=repository)


def agent_result(cwd: Path) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={"cwd": str(cwd), "skills": ["requirement-breakdown", "commit-changes"], "slash_commands": ["requirement-breakdown", "commit-changes"]},
        text="已处理", result_subtype="success", is_error=False, session_id="session-1",
        stop_reason="end_turn", num_turns=1, total_cost_usd=0.1, exception=None,
    )


def decision(verdict: str, *, reason: str = "已核验") -> tuple[dict, int, str]:
    value = {"verdict": verdict, "answer": "", "reason": reason, "required_inputs": ["外部授权"] if verdict == "blocked" else []}
    return value, 1, json.dumps(value, ensure_ascii=False)


class RequirementBreakdownTests(unittest.TestCase):
    def make_run(
        self,
        root: Path,
        children: list[str] | None = None,
        *,
        existing: bool = False,
        ui_ux_applicable: bool = True,
    ) -> tuple[Path, Path, dict]:
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
        if ui_ux_applicable:
            (workspace / UI_UX_FRAMEWORK_PATH).parent.mkdir(parents=True)
            (workspace / UI_UX_FRAMEWORK_PATH).write_text(
                "# UI/UX\n\n## 已确认 Target\n- 运营工作台是既有产品表面，后续需求从此入口演进。\n\n"
                "## 默认 Target\n- 窄屏将上下文导航收纳为抽屉，同时保留当前对象与返回关系。\n"
                "  - 依据：现有任务需要保持对象上下文。\n"
                "  - 重新评估条件：新增跨角色工作台或主要入口。\n",
                encoding="utf-8",
            )
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
        root_paths = [
            *outputs,
            checklist,
            design,
            ARCHITECTURE_OUTPUT_PATH.as_posix(),
        ]
        if ui_ux_applicable:
            root_paths.append(UI_UX_FRAMEWORK_PATH.as_posix())
        if existing:
            root_paths.append(BACKLOG_PATH.as_posix())
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
        write_json(
            run_dir / "steps/10.json",
            {
                "step": 10,
                "name": "产品级 UI/UX 框架",
                "status": "success",
                "summary": "完成",
                "applicable": ui_ux_applicable,
                "outputs": [UI_UX_FRAMEWORK_PATH.as_posix()]
                if ui_ux_applicable
                else [],
                "blocked": None,
                "error": None,
            },
        )
        names = ["root", *children]
        write_json(run_dir / "steps/08.json", {"step": 8, "status": "success", "applicable": True, "outputs": [], "applicable_repositories": names, "repositories": [{"unexpected": True}]})
        state = {
            "status": "success",
            "phase": "project_initialization",
            "step": 11,
            "current_step": 11,
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
        (workspace / BACKLOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        (workspace / BACKLOG_PATH).write_text("# Backlog\n\n有效内容。\n", encoding="utf-8")

    @staticmethod
    def commit_document(workspace: Path) -> None:
        commit_paths(workspace, BACKLOG_PATH.as_posix())

    @staticmethod
    def run_step(run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    async def completed(self, *_args: object, **_kwargs: object) -> tuple[dict, int, str]:
        return decision("completed")

    def test_step_eight_handoff_uses_names_not_replayed_repository_facts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            workspace, names = breakdown_step._step_eight_handoff(run_dir, state)
            self.assertTrue(workspace.is_dir())
            self.assertEqual(names, ["root", "frontend"])
            state["applicable_repositories"] = ["root"]
            with self.assertRaisesRegex(RuntimeError, "交接状态"):
                breakdown_step._step_eight_handoff(run_dir, state)

    def test_dirty_document_commits_once_and_clean_tracked_skips_commit(self) -> None:
        for existing, expected_commits in ((False, 1), (True, 0)):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"], existing=existing)
                prompts: list[str] = []
                async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    prompts.append(prompt)
                    if prompt.startswith("/requirement-breakdown") and not existing:
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
                if prompt.startswith("固定 Backlog 文档缺失"):
                    self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes":
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value
            self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
            self.assertEqual([session for prompt, session in calls if prompt.startswith("固定 Backlog 文档缺失") or prompt.splitlines()[0] == "/commit-changes"], ["session-1", "session-1"])

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
                    (workspace / BACKLOG_PATH).parent.mkdir(parents=True)
                    (workspace / BACKLOG_PATH).symlink_to(target)
                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state)
                if mutation == "symlink":
                    with self.assertRaisesRegex(RuntimeError, "符号链接"):
                        backlog_repair(workspace)
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as handle:
                handle.write(f"{BACKLOG_PATH.as_posix()}\n")
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
                if prompt.startswith("/requirement-breakdown"): self.write_document(workspace)
                elif prompt.splitlines()[0] == "/commit-changes": self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value
            original = breakdown_step.write_state
            def interrupt(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE: raise OSError("interrupted")
                original(target, value)
            with patch.object(breakdown_step, "write_state", side_effect=interrupt):
                with self.assertRaises(OSError):
                    self.run_step(run_dir, state, agent_runner=agent, decision_runner=self.completed, config_loader=lambda: object())
            async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                raise AssertionError("不得恢复执行")
            self.assertEqual(self.run_step(run_dir, read_state(run_dir), agent_runner=unexpected, decision_runner=unexpected)["status"], "success")

    def test_blocked_clean_tracked_document_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                if prompt.startswith("/requirement-breakdown"):
                    self.write_document(workspace)
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value
            async def blocked(*_args: object, **_kwargs: object) -> tuple[dict, int, str]:
                return decision("blocked", reason="缺少外部授权")
            with self.assertRaises(RequirementBreakdownBlocked):
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=blocked, config_loader=lambda: object())
            self.assertEqual(json.loads((run_dir / "steps/11.json").read_text(encoding="utf-8"))["status"], "blocked")
            self.assertEqual(read_state(run_dir)["current_node"], CURRENT_NODE)
    def test_success_advances_requirement_registry_state_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                if prompt.startswith("/requirement-breakdown"):
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
            completed = read_state(run_dir)
            self.assertEqual(
                (
                    completed["phase"],
                    completed["step"],
                    completed["current_step"],
                    completed["current_node"],
                ),
                ("phase_1_requirement_development", 12, 12, NEXT_NODE),
            )
            self.assertIsNone(completed["active_requirement"])
            self.assertIsNone(completed["requirement_cycle"])

    def test_step_ten_applicability_controls_prompt_and_invalid_handoffs_fail(self) -> None:
        for applicable in (True, False):
            with self.subTest(applicable=applicable), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(
                    Path(directory), ["frontend"], ui_ux_applicable=applicable
                )
                prompts: list[str] = []
                decision_prompts: list[str] = []

                async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    prompts.append(prompt)
                    if prompt.startswith("/requirement-breakdown"):
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
                self.assertTrue(prompt.startswith("/requirement-breakdown\n"))
                for required in (
                    ARCHITECTURE_OUTPUT_PATH.as_posix(),
                    BACKLOG_PATH.as_posix(),
                    "已确认 Target",
                    "演进既有产品表面",
                    "独立可观察的用户结果",
                    "其它需求开始前确实必须完成",
                    "默认 Target",
                    "依据和重议条件",
                ):
                    self.assertIn(required, prompt)
                if applicable:
                    self.assertIn(UI_UX_FRAMEWORK_PATH.as_posix(), prompt)
                else:
                    self.assertIn("当前产品没有适用的产品级体验框架文档", prompt)
                for forbidden in ("第 11 步", "PCM", "节点", "session", "Skill", "/commit-changes"):
                    self.assertNotIn(forbidden, prompt)

                self.assertTrue(decision_prompts)
                for system_prompt in decision_prompts:
                    for required in (
                        "已确认 Target",
                        "演进既有产品表面",
                        "独立可观察的用户结果",
                        "其它需求开始前确实必须完成",
                        "迁移 BR",
                        "严格依赖",
                        "体验约束",
                        "默认 Target",
                        "依据和重议条件",
                        "偏离默认 Target",
                        "跨需求体验骨架",
                        "框架文档",
                        "页面",
                        "组件",
                        "CSS",
                        "目录",
                        "工程依赖",
                        "外部条件",
                        "depends_on",
                        "正式 BR ID",
                    ):
                        self.assertIn(required, system_prompt)
                    self.assertNotIn("Skill", system_prompt)
                    if applicable:
                        self.assertIn("运营工作台是既有产品表面", system_prompt)
                        self.assertIn("窄屏将上下文导航收纳为抽屉", system_prompt)
                        self.assertIn("现有任务需要保持对象上下文", system_prompt)
                        self.assertIn("新增跨角色工作台或主要入口", system_prompt)
                    else:
                        self.assertIn("当前产品没有适用的产品级体验框架文档", system_prompt)
                        self.assertNotIn("运营工作台是既有产品表面", system_prompt)
                        self.assertNotIn("窄屏将上下文导航收纳为抽屉", system_prompt)

        for invalid_step in ("02", "05", "07", "09", "10"):
            with self.subTest(invalid_step=invalid_step), tempfile.TemporaryDirectory() as directory:
                run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
                path = run_dir / "steps" / f"{invalid_step}.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                if invalid_step == "02":
                    data["outputs"] = ["docs/requirements/other.md"]
                elif invalid_step == "10":
                    data["outputs"] = []
                else:
                    data["outputs"] = []
                write_json(path, data)

                async def unexpected(*_args: object, **_kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("上游交接失败不得执行 Agent")

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

    def test_blocked_rerun_uses_common_resume_session_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            calls: list[tuple[str, str | None]] = []
            decisions = [decision("blocked", reason="缺少授权"), decision("completed")]

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append((prompt, kwargs["resume_session_id"]))  # type: ignore[index]
                if prompt.startswith("/requirement-breakdown"):
                    self.write_document(workspace)
                elif prompt == BLOCKED_RESUME_PROMPT:
                    self.commit_document(workspace)
                value = agent_result(kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index,operator]
                return value

            async def decide(*_args: object, **_kwargs: object) -> tuple[dict, int, str]:
                return decisions.pop(0)

            with self.assertRaises(RequirementBreakdownBlocked):
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
                    if prompt.startswith("/requirement-breakdown"):
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
                    (workspace / BACKLOG_PATH).write_text(
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
                breakdown_step.subprocess, "run", wraps=subprocess.run
            ) as mocked:
                breakdown_step.validate_inputs(run_dir, state)
                breakdown_step._verify_worktree_boundary(workspace, ["root", "frontend"])
                breakdown_step._document_tracked(workspace)
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
                    BACKLOG_PATH.as_posix(),
                ),
                ("ls-files", "--error-unmatch", "--", BACKLOG_PATH.as_posix()),
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
                    if prompt.startswith("/requirement-breakdown"):
                        self.write_document(workspace)
                    value = agent_result(kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index,operator]
                    return value

                async def blocked(*_args: object, **_kwargs: object) -> tuple[dict, int, str]:
                    return decision("blocked", reason="缺少外部授权")

                with self.assertRaises(RequirementBreakdownBlocked):
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
