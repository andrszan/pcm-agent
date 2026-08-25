from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.files import write_json
from common.state import read_state, write_state
from steps.step_13_select_requirement.step import run as select_requirement
from steps.step_14_trd_design.step import (
    BACKLOG_PATH,
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    STEP,
    TRD_AGENT_TOOLS,
    TRD_DESIGN_DECISION_RULES,
    TRDDesignBlocked,
    _context,
    _status_entries,
    _trd_agent_hooks,
    _verify_refs,
    failure_scope,
    has_complete_success,
    run,
)


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=check
    )


def commit(repository: Path, *paths: str, message: str = "test commit") -> str:
    git("add", "--", *paths, cwd=repository)
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
    return git("rev-parse", "HEAD", cwd=repository).stdout.strip()


def agent_result(
    cwd: Path,
    *,
    text: str = "已形成活动 TRD。",
    session: str = "trd-session-1",
) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": ["trd-design"],
            "slash_commands": ["trd-design"],
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


class TRDDesignTests(unittest.TestCase):
    @staticmethod
    def catalog() -> list[dict]:
        return [
            {
                "id": "BR-001",
                "title": "身份、角色访问与站内消息入口",
                "order": 1,
                "depends_on": [],
            },
            {
                "id": "BR-002",
                "title": "物品治理",
                "order": 2,
                "depends_on": ["BR-001"],
            },
        ]

    @staticmethod
    def source() -> dict:
        return {
            "path": BACKLOG_PATH.as_posix(),
            "sha256": "a" * 64,
            "root_main_sha": "b" * 40,
        }

    def make_run(
        self,
        root: Path,
        *,
        ui_ux_applicable: bool = True,
        children: list[str] | None = None,
        trd_parent_file: bool = False,
    ) -> tuple[Path, Path, dict]:
        children = children or ["frontend", "backend"]
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        (workspace / "docs/requirements").mkdir(parents=True)
        (workspace / "docs/design").mkdir(parents=True)
        (workspace / "docs/backlog").mkdir(parents=True)

        documents = {
            "docs/requirements/项目需求说明.md": "# 项目需求\n\n产品目标。\n",
            "docs/requirements/产品功能说明.md": "# 产品功能\n\n功能范围。\n",
            "docs/requirements/项目准备清单.md": "# 项目准备清单\n\n准备完成。\n",
            "docs/design/技术方案.md": "# 技术方案\n\n总体方案。\n",
            "docs/design/工程架构设计.md": "# 工程架构\n\n实际架构。\n",
            BACKLOG_PATH.as_posix(): (
                "# Backlog\n\n## 需求详情\n\n"
                "#### BR-001 身份、角色访问与站内消息入口\n\n"
                "##### 目标\n\n完成身份与安全访问。\n\n"
                "#### BR-002 物品治理\n\n##### 目标\n\n治理物品。\n"
            ),
        }
        if trd_parent_file:
            documents["docs/trd"] = "路径冲突。\n"
        if ui_ux_applicable:
            documents["docs/ui-ux/framework.md"] = "# UI/UX 框架\n\n体验约束。\n"
        for relative, content in documents.items():
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        git("init", "-b", "main", cwd=workspace)
        for name in children:
            child = workspace / name
            child.mkdir()
            git("init", "-b", "main", cwd=child)
            (child / "README.md").write_text(f"# {name}\n", encoding="utf-8")
            commit(child, "README.md")
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
                exclude.write(f"{name}/\n")
        commit(workspace, *documents)

        product_outputs = [
            "docs/requirements/项目需求说明.md",
            "docs/requirements/产品功能说明.md",
        ]
        common = {
            "status": "success",
            "summary": "已完成。",
            "applicable": True,
            "blocked": None,
            "error": None,
        }
        write_json(
            run_dir / "steps/02.json",
            {"step": 2, "name": "项目需求与产品定义", "outputs": product_outputs, **common},
        )
        write_json(
            run_dir / "steps/05.json",
            {
                "step": 5,
                "name": "核验项目准备状态",
                "outputs": ["docs/requirements/项目准备清单.md"],
                **common,
            },
        )
        write_json(
            run_dir / "steps/07.json",
            {
                "step": 7,
                "name": "总体技术方案",
                "outputs": ["docs/design/技术方案.md"],
                **common,
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
                "outputs": [],
                "applicable_repositories": names,
                "repositories": result_repositories,
                **common,
            },
        )
        write_json(
            run_dir / "steps/09.json",
            {
                "step": 9,
                "name": "工程架构设计",
                "outputs": ["docs/design/工程架构设计.md"],
                **common,
            },
        )
        write_json(
            run_dir / "steps/10.json",
            {
                "step": 10,
                "name": "产品级 UI/UX 框架",
                "status": "success",
                "summary": "已完成。",
                "applicable": ui_ux_applicable,
                "outputs": ["docs/ui-ux/framework.md"] if ui_ux_applicable else [],
                "blocked": None,
                "error": None,
            },
        )
        write_json(
            run_dir / "steps/11.json",
            {"step": 11, "name": "拆分 Backlog", "outputs": [BACKLOG_PATH.as_posix()], **common},
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
            "phase": PHASE,
            "step": 13,
            "current_step": 13,
            "current_node": "phase_1:select_requirement",
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "applicable_repositories": names,
            "repositories": state_repositories,
            "requirement_registry": {
                "schema_version": 1,
                "source": self.source(),
                "requirements": [
                    {**item, "status": "pending", "completion": None}
                    for item in self.catalog()
                ],
            },
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        select_requirement(run_dir, state)
        return run_dir, workspace, read_state(run_dir)

    @staticmethod
    def run_step(run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    @staticmethod
    def write_trd(workspace: Path, state: dict, content: str = "# 技术设计\n\n有效内容。\n") -> Path:
        relative = state["requirement_cycle"]["trd_path"]
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def test_decision_rules_reject_implementation_blocking_open_decisions(self) -> None:
        self.assertIn("实现前必须确认", TRD_DESIGN_DECISION_RULES)
        self.assertIn("不能仅因这些事项已被列出就判定完成", TRD_DESIGN_DECISION_RULES)

    def test_fresh_persists_exact_path_before_agent_and_places_it_in_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []

            async def agent(prompt: str, **_: object) -> ClaudeRunResult:
                persisted = read_state(run_dir)
                self.assertEqual(
                    persisted["requirement_cycle"]["trd_path"],
                    "docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md",
                )
                self.assertIn(persisted["requirement_cycle"]["trd_path"], prompt)
                prompts.append(prompt)
                self.write_trd(workspace, persisted)
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                today_provider=lambda: date(2026, 8, 25),
            )
            self.assertEqual(len(prompts), 1)
            self.assertTrue(prompts[0].startswith("/trd-design\n"))
            self.assertNotIn("第 14 步", prompts[0])
            self.assertNotIn("PCM", prompts[0])
            self.assertEqual(saved["outputs"], [saved["trd_path"]])
            self.assertEqual(saved["trd_session_id"], "trd-session-1")
            self.assertEqual(_status_entries(workspace), [("??", saved["trd_path"])])
            completed = read_state(run_dir)
            self.assertEqual(
                (completed["step"], completed["current_step"], completed["current_node"]),
                (15, 15, NEXT_NODE),
            )
            self.assertTrue(has_complete_success(run_dir, completed))
            self.assertFalse((run_dir / "steps/14.json").exists())
            self.assertTrue((run_dir / "steps/requirements/BR-001/14.json").is_file())

    def test_recovery_reuses_first_date_and_original_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def interrupted(*_: object, **__: object) -> ClaudeRunResult:
                raise RuntimeError("simulated interruption")

            with self.assertRaisesRegex(RuntimeError, "Agent SDK 执行异常"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=interrupted,
                    config_loader=lambda: object(),
                    today_provider=lambda: date(2026, 8, 25),
                )
            interrupted_state = read_state(run_dir)
            first_path = interrupted_state["requirement_cycle"]["trd_path"]
            prompts: list[str] = []

            async def agent(prompt: str, **_: object) -> ClaudeRunResult:
                prompts.append(prompt)
                self.write_trd(workspace, read_state(run_dir))
                return agent_result(workspace, session="trd-session-2")

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            saved = self.run_step(
                run_dir,
                interrupted_state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                today_provider=lambda: date(2026, 8, 26),
            )
            self.assertEqual(saved["trd_path"], first_path)
            self.assertIn("2026-08-25", saved["trd_path"])
            self.assertEqual(prompts, [prompts[0]])

    def test_inapplicable_ui_framework_is_not_read_or_referenced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(
                Path(directory), ui_ux_applicable=False
            )
            prompts: list[str] = []

            async def agent(prompt: str, **_: object) -> ClaudeRunResult:
                prompts.append(prompt)
                self.write_trd(workspace, read_state(run_dir))
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                today_provider=lambda: date(2026, 8, 25),
            )
            self.assertIn("没有适用的产品级 UI/UX 框架", prompts[0])
            self.assertNotIn("@./docs/ui-ux/framework.md", prompts[0])

    def test_completed_missing_document_repairs_in_same_session_without_commit_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []

            async def agent(prompt: str, **_: object) -> ClaudeRunResult:
                prompts.append(prompt)
                if len(prompts) == 2:
                    self.write_trd(workspace, read_state(run_dir))
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                today_provider=lambda: date(2026, 8, 25),
            )
            self.assertEqual(len(prompts), 2)
            self.assertIn("缺失或为空", prompts[1])
            self.assertNotIn("/commit-changes", "\n".join(prompts))
            conversation = json.loads(
                (run_dir / "conversations/trd_design_BR-001.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("/commit-changes", json.dumps(conversation, ensure_ascii=False))

    def test_blocked_preserves_scoped_result_and_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision(
                    "blocked",
                    reason="缺少外部授权",
                    required_inputs=["外部授权"],
                )

            with self.assertRaises(TRDDesignBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                    today_provider=lambda: date(2026, 8, 25),
                )
            saved = json.loads(
                (run_dir / "steps/requirements/BR-001/14.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["status"], "blocked")
            self.assertEqual(saved["trd_session_id"], "trd-session-1")
            blocked_state = read_state(run_dir)
            self.assertEqual(blocked_state["current_node"], CURRENT_NODE)
            self.assertEqual(blocked_state["status"], "blocked")

    def test_scope_staged_commit_and_ref_drift_are_rejected(self) -> None:
        cases = ("outside", "staged", "commit")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))

                async def agent(*_: object, **__: object) -> ClaudeRunResult:
                    current = read_state(run_dir)
                    target = self.write_trd(workspace, current)
                    if case == "outside":
                        (workspace / "outside.txt").write_text("outside\n", encoding="utf-8")
                    elif case == "staged":
                        git("add", "--", str(target.relative_to(workspace)), cwd=workspace)
                    else:
                        commit(workspace, str(target.relative_to(workspace)))
                    return agent_result(workspace)

                async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                    return decision("completed")

                with self.assertRaises(RuntimeError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=decide,
                        config_loader=lambda: object(),
                        today_provider=lambda: date(2026, 8, 25),
                    )

    def test_trd_parent_file_conflict_is_rejected_before_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(
                Path(directory), trd_parent_file=True
            )
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "父路径"):
                self.run_step(
                    run_dir,
                    state,
                    today_provider=lambda: date(2026, 8, 25),
                )
            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            self.assertNotIn("trd_path", read_state(run_dir)["requirement_cycle"])
            self.assertFalse((run_dir / "steps/requirements/BR-001/14.json").exists())

    def test_preflight_ref_drift_has_no_state_or_agent_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "baseline.txt").write_text("changed\n", encoding="utf-8")
            commit(workspace, "baseline.txt")
            before = (run_dir / "state.json").read_bytes()
            called = False

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                nonlocal called
                called = True
                return agent_result(workspace)

            with self.assertRaisesRegex(RuntimeError, "基线"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    today_provider=lambda: date(2026, 8, 25),
                )
            self.assertFalse(called)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            self.assertNotIn("trd_path", read_state(run_dir)["requirement_cycle"])

    def test_success_result_recovers_state_and_advanced_rerun_does_not_read_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                self.write_trd(workspace, read_state(run_dir))
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                today_provider=lambda: date(2026, 8, 25),
            )
            interrupted = read_state(run_dir)
            interrupted.update(
                {
                    "status": "running",
                    "step": STEP,
                    "current_step": STEP,
                    "current_node": CURRENT_NODE,
                }
            )
            write_state(run_dir, interrupted)

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("不应再次调用 Agent")

            recovered = self.run_step(
                run_dir,
                interrupted,
                agent_runner=forbidden,
                config_loader=lambda: object(),
            )
            self.assertEqual(recovered, saved)
            advanced = read_state(run_dir)
            (workspace / "future-code.py").write_text("print('future')\n", encoding="utf-8")
            with patch(
                "steps.step_14_trd_design.step._git_run",
                side_effect=AssertionError("推进后不应读取 Git"),
            ):
                self.assertEqual(self.run_step(run_dir, advanced), saved)

    def test_bisect_state_is_rejected_before_trd_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            git("bisect", "start", cwd=workspace)
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "未完成"):
                self.run_step(
                    run_dir,
                    state,
                    today_provider=lambda: date(2026, 8, 25),
                )
            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            self.assertNotIn("trd_path", read_state(run_dir)["requirement_cycle"])

    def test_default_agent_runner_receives_restricted_tools_and_write_hook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            captured: dict[str, object] = {}

            async def restricted_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                captured.update(kwargs)
                self.write_trd(workspace, read_state(run_dir))
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            with patch(
                "steps.step_14_trd_design.step.run_claude",
                new=restricted_agent,
            ):
                self.run_step(
                    run_dir,
                    state,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                    today_provider=lambda: date(2026, 8, 25),
                )
            self.assertEqual(captured["tools"], TRD_AGENT_TOOLS)
            hooks = captured["hooks"]
            self.assertIsInstance(hooks, dict)
            self.assertIn("PreToolUse", hooks)

    def test_real_agent_tool_policy_has_no_bash_and_only_allows_exact_trd_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            state["requirement_cycle"]["trd_path"] = (
                "docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md"
            )
            context = _context(run_dir, state)
            hooks = _trd_agent_hooks(
                context, state["requirement_cycle"]["trd_path"]
            )
            callback = hooks["PreToolUse"][0].hooks[0]
            allowed = asyncio.run(
                callback(
                    {
                        "tool_name": "Write",
                        "tool_input": {
                            "file_path": str(
                                workspace / state["requirement_cycle"]["trd_path"]
                            )
                        },
                    },
                    None,
                    {"signal": None},
                )
            )
            denied = asyncio.run(
                callback(
                    {
                        "tool_name": "Edit",
                        "tool_input": {"file_path": str(workspace / "README.md")},
                    },
                    None,
                    {"signal": None},
                )
            )
            self.assertEqual(
                allowed["hookSpecificOutput"]["permissionDecision"], "allow"
            )
            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            self.assertNotIn("Bash", TRD_AGENT_TOOLS)
            self.assertNotIn("Agent", TRD_AGENT_TOOLS)
            self.assertNotIn("NotebookEdit", TRD_AGENT_TOOLS)

    def test_failure_scope_and_git_environment_are_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            self.assertIsNone(failure_scope(run_dir, state))
            state["requirement_cycle"]["trd_path"] = (
                "docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md"
            )
            write_state(run_dir, state)
            scope = failure_scope(run_dir, state)
            self.assertEqual(scope["requirement_id"], "BR-001")
            self.assertEqual(
                scope["trd_path"],
                "docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md",
            )

            captured: list[dict[str, str]] = []
            original = subprocess.run

            def recording_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
                env = kwargs.get("env")
                if isinstance(env, dict):
                    captured.append(env)
                return original(*args, **kwargs)

            with patch.dict(os.environ, {"GIT_DIR": "/tmp/redirect", "GIT_INDEX_FILE": "/tmp/index"}):
                with patch(
                    "steps.step_14_trd_design.step.subprocess.run",
                    side_effect=recording_run,
                ):
                    _verify_refs(_context(run_dir, state))
            self.assertTrue(captured)
            self.assertTrue(all(not any(key.startswith("GIT_") for key in env) for env in captured))


if __name__ == "__main__":
    unittest.main()
