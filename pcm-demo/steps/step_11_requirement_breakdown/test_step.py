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
from steps.step_11_requirement_breakdown.step import (
    ARCHITECTURE_OUTPUT_PATH,
    BACKLOG_PATH,
    BACKLOG_REPAIR_PROMPT,
    COMMIT_REPAIR_PROMPT,
    CONVERSATION_KEY,
    CURRENT_NODE,
    NEXT_NODE,
    REQUIREMENT_BREAKDOWN_MAX_BUDGET_USD,
    REQUIREMENT_BREAKDOWN_MAX_TURNS,
    RequirementBreakdownBlocked,
    UI_UX_FRAMEWORK_PATH,
    _commit_requested,
    backlog_repair,
    run,
)
import steps.step_11_requirement_breakdown.step as breakdown_step


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


def agent_result(*, cwd: Path, text: str = "已处理", session: str = "session-1") -> ClaudeRunResult:
    skills = ["requirement-breakdown", "commit-changes"]
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


class RequirementBreakdownTests(unittest.TestCase):
    def test_handoff_targets_requirement_registry_initialization(self) -> None:
        self.assertEqual(NEXT_NODE, "phase_1:initialize_requirement_registry")

    def make_run(
        self,
        root: Path,
        children: list[str] | None = None,
        *,
        ui_ux_applicable: bool = True,
        existing_backlog: bool = False,
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
        for document in [
            *product_outputs,
            checklist,
            design,
            ARCHITECTURE_OUTPUT_PATH.as_posix(),
        ]:
            (workspace / document).write_text(
                f"# {Path(document).stem}\n\n有效内容。\n", encoding="utf-8"
            )
        root_paths = [
            *product_outputs,
            checklist,
            design,
            ARCHITECTURE_OUTPUT_PATH.as_posix(),
        ]
        if ui_ux_applicable:
            (workspace / UI_UX_FRAMEWORK_PATH).parent.mkdir(parents=True)
            (workspace / UI_UX_FRAMEWORK_PATH).write_text(
                "# 产品级 UI/UX 框架\n\n体验基线。\n", encoding="utf-8"
            )
            root_paths.append(UI_UX_FRAMEWORK_PATH.as_posix())
        if existing_backlog:
            (workspace / BACKLOG_PATH).parent.mkdir(parents=True)
            (workspace / BACKLOG_PATH).write_text(
                "# Backlog\n\n既有有效内容。\n", encoding="utf-8"
            )
            root_paths.append(BACKLOG_PATH.as_posix())

        initialize_root_repository(workspace)
        for name in children:
            child = workspace / name
            child.mkdir()
            initialize_root_repository(child)
            (child / "README.md").write_text(f"# {name}\n", encoding="utf-8")
            commit_paths(child, "README.md")
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
                exclude.write(f"{name}/\n")
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
            {"step": 7, "status": "success", "applicable": True, "outputs": [design]},
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
        write_json(
            run_dir / "steps/10.json",
            {
                "step": 10,
                "name": "产品级 UI/UX 框架",
                "status": "success",
                "summary": "已完成",
                "applicable": ui_ux_applicable,
                "outputs": [UI_UX_FRAMEWORK_PATH.as_posix()] if ui_ux_applicable else [],
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
            "step": 11,
            "current_step": 11,
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
    def write_backlog(workspace: Path) -> None:
        (workspace / BACKLOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        (workspace / BACKLOG_PATH).write_text(
            "# Backlog\n\n- 需求：可核验的范围与验收要点。\n", encoding="utf-8"
        )

    @staticmethod
    def commit_backlog(workspace: Path) -> None:
        commit_paths(workspace, BACKLOG_PATH.as_posix(), message="docs: 拆分 Backlog")

    def test_step_ten_applicable_and_inapplicable_handoffs_drive_prompt(self) -> None:
        for applicable in (True, False):
            with self.subTest(applicable=applicable), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(
                    Path(directory), ["frontend", "backend"], ui_ux_applicable=applicable
                )
                prompts: list[str] = []

                async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    prompts.append(prompt)
                    if prompt.startswith("/requirement-breakdown"):
                        self.write_backlog(workspace)
                    elif prompt == COMMIT_REPAIR_PROMPT:
                        self.commit_backlog(workspace)
                    value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                    kwargs["on_update"](value)  # type: ignore[index, operator]
                    return value

                async def completed(messages, config, *, system_prompt):
                    self.assertIn("# 项目需求说明", system_prompt)
                    self.assertIn("# 项目准备清单", system_prompt)
                    self.assertIn("# 工程架构设计", system_prompt)
                    self.assertIn(BACKLOG_PATH.as_posix(), system_prompt)
                    if applicable:
                        self.assertIn("# 产品级 UI/UX 框架", system_prompt)
                    else:
                        self.assertNotIn("# 产品级 UI/UX 框架", system_prompt)
                    return decision("completed")

                document_paths: list[Path] = []
                original_document_contents = breakdown_step._document_contents

                def observe_document(workspace: Path, relative: Path, label: str) -> str:
                    document_paths.append(relative)
                    return original_document_contents(workspace, relative, label)

                with patch.object(
                    breakdown_step, "_document_contents", side_effect=observe_document
                ):
                    saved = self.run_step(
                        run_dir,
                        state,
                        agent_runner=fake_agent,
                        decision_runner=completed,
                        config_loader=lambda: object(),
                    )
                self.assertEqual(saved["outputs"], [BACKLOG_PATH.as_posix()])
                if not applicable:
                    self.assertNotIn(UI_UX_FRAMEWORK_PATH, document_paths)
                self.assertTrue(prompts[0].startswith("/requirement-breakdown\n"))
                for expected in (
                    "充分授权",
                    "正式 Backlog",
                    "待开发",
                    "开发中",
                    "已完成",
                    "阻塞",
                    "只允许创建或更新固定 Backlog 文档",
                    "不得执行 Git 写操作",
                    "@./frontend",
                ):
                    self.assertIn(expected, prompts[0])
                for forbidden in ("第 11 步", "PCM", "节点", "session", "Skill", "/commit-changes"):
                    self.assertNotIn(forbidden, prompts[0])
                self.assertEqual(prompts[-1], COMMIT_REPAIR_PROMPT)
                completed_state = read_state(run_dir)
                self.assertEqual(
                    (completed_state["phase"], completed_state["step"], completed_state["current_node"]),
                    ("phase_1_requirement_development", 12, NEXT_NODE),
                )
                self.assertIsNone(completed_state["active_requirement"])
                self.assertIsNone(completed_state["requirement_cycle"])
                self.assertNotIn("completed_requirements", completed_state)
                self.assertNotIn("phase_two", completed_state)
                self.assertEqual(REQUIREMENT_BREAKDOWN_MAX_TURNS, 48)
                self.assertEqual(REQUIREMENT_BREAKDOWN_MAX_BUDGET_USD, 16.0)

    def test_strict_handoffs_reject_before_agent_execution(self) -> None:
        cases = (
            "step-two",
            "step-two-wrong-paths",
            "step-five",
            "step-seven",
            "step-nine",
            "step-ten",
            "step-eight-state",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
                if case == "step-two":
                    write_json(run_dir / "steps/02.json", {"step": 2, "status": "success", "outputs": ["x"]})
                elif case == "step-two-wrong-paths":
                    wrong_outputs = ["docs/requirements/旧需求.md", "docs/requirements/旧功能.md"]
                    for output in wrong_outputs:
                        (workspace / output).write_text("# 旧资料\n", encoding="utf-8")
                    write_json(
                        run_dir / "steps/02.json",
                        {"step": 2, "status": "success", "outputs": wrong_outputs},
                    )
                elif case == "step-five":
                    write_json(run_dir / "steps/05.json", {"step": 5, "status": "success", "outputs": []})
                elif case == "step-seven":
                    write_json(run_dir / "steps/07.json", {"step": 7, "status": "success", "outputs": []})
                elif case == "step-nine":
                    data = json.loads((run_dir / "steps/09.json").read_text(encoding="utf-8"))
                    data["outputs"] = ["docs/design/other.md"]
                    write_json(run_dir / "steps/09.json", data)
                elif case == "step-ten":
                    data = json.loads((run_dir / "steps/10.json").read_text(encoding="utf-8"))
                    data["outputs"] = []
                    write_json(run_dir / "steps/10.json", data)
                else:
                    state["repositories"] = []
                    write_state(run_dir, state)

                async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("交接无效时不得调用 Agent")

                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state, agent_runner=unexpected)

    def test_document_repair_and_exact_same_session_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if prompt == BACKLOG_REPAIR_PROMPT:
                    self.write_backlog(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_backlog(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=lambda *args, **kwargs: asyncio.sleep(0, result=decision("completed")),
                config_loader=lambda: object(),
            )
            self.assertTrue(calls[0]["prompt"].startswith("/requirement-breakdown"))
            self.assertEqual([call["prompt"] for call in calls[1:]], [BACKLOG_REPAIR_PROMPT, COMMIT_REPAIR_PROMPT])
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual([call["resume_session_id"] for call in calls[1:]], ["session-1", "session-1"])

    def test_commit_anchor_requires_exact_prompt_immediate_reply_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            conversations = run_dir / "conversations"
            conversations.mkdir()
            path = conversations / f"{CONVERSATION_KEY}.json"
            state["claude_sessions"] = {CONVERSATION_KEY: "session-1"}
            state["decision_conversations"] = {CONVERSATION_KEY: {"path": f"conversations/{CONVERSATION_KEY}.json"}}
            for tail, expected in (
                ([{"role": "assistant", "content": COMMIT_REPAIR_PROMPT}], False),
                ([{"role": "assistant", "content": COMMIT_REPAIR_PROMPT + "\n"}, {"role": "user", "content": "已提交"}], False),
                ([{"role": "assistant", "content": COMMIT_REPAIR_PROMPT}, {"role": "user", "content": " "}], False),
                ([{"role": "assistant", "content": COMMIT_REPAIR_PROMPT}, {"role": "user", "content": "已提交"}], True),
            ):
                with self.subTest(tail=tail):
                    write_json(path, {"messages": [{"role": "system", "content": "x"}, *tail]})
                    self.assertEqual(_commit_requested(run_dir, state), expected)

    def test_worktree_boundary_and_symlinks_are_rejected(self) -> None:
        for mutation in ("root", "child"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
                target = workspace if mutation == "root" else workspace / "frontend"
                (target / "unexpected.txt").write_text("dirty\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "范围外|子仓库"):
                    self.run_step(run_dir, state)

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
            external = root / "external-history.json"
            write_json(external, {"messages": [{"role": "system", "content": "x"}]})
            (conversations / f"{CONVERSATION_KEY}.json").symlink_to(external)
            with self.assertRaisesRegex(RuntimeError, "非符号链接普通文件"):
                self.run_step(run_dir, state)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _run_dir, workspace, _state = self.make_run(root, ["frontend"])
            external = root / "external-backlog.md"
            external.write_text("内容\n", encoding="utf-8")
            (workspace / BACKLOG_PATH).parent.mkdir(parents=True)
            (workspace / BACKLOG_PATH).symlink_to(external)
            with self.assertRaisesRegex(RuntimeError, "不能包含符号链接"):
                backlog_repair(workspace)

    def test_fresh_anchor_blocked_resume_and_success_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory), ["frontend"])
            state["claude_sessions"] = {CONVERSATION_KEY: "forged"}
            write_state(run_dir, state)
            with self.assertRaisesRegex(RuntimeError, "新鲜.*既有执行产物"):
                self.run_step(run_dir, state)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            verdicts = ["blocked", "completed", "completed"]
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if prompt.startswith("/requirement-breakdown"):
                    self.write_backlog(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_backlog(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def decide(messages, config, *, system_prompt):
                verdict = verdicts.pop(0)
                if verdict == "blocked":
                    return decision("blocked", reason="缺少授权", required_inputs=["外部授权"])
                return decision("completed")

            with self.assertRaises(RequirementBreakdownBlocked):
                self.run_step(run_dir, state, agent_runner=fake_agent, decision_runner=decide, config_loader=lambda: object())
            self.run_step(run_dir, read_state(run_dir), agent_runner=fake_agent, decision_runner=decide, config_loader=lambda: object())
            self.assertEqual(calls[1]["prompt"], BLOCKED_RESUME_PROMPT)
            self.assertEqual(calls[1]["resume_session_id"], "session-1")

    def test_result_state_interruption_idempotence_and_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                if prompt.startswith("/requirement-breakdown"):
                    self.write_backlog(workspace)
                elif prompt == COMMIT_REPAIR_PROMPT:
                    self.commit_backlog(workspace)
                value = agent_result(cwd=kwargs["cwd"])  # type: ignore[index]
                kwargs["on_update"](value)  # type: ignore[index, operator]
                return value

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            original_write_state = breakdown_step.write_state

            def interrupt_final_state(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("模拟状态写入中断")
                original_write_state(target, value)

            with patch.object(breakdown_step, "write_state", side_effect=interrupt_final_state):
                with self.assertRaises(OSError):
                    self.run_step(run_dir, state, agent_runner=fake_agent, decision_runner=completed, config_loader=lambda: object())
            self.assertEqual(json.loads((run_dir / "steps/11.json").read_text(encoding="utf-8"))["status"], "success")

            async def unexpected(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("既有成功不得再次调用 Agent 或决定服务")

            recovered = self.run_step(run_dir, read_state(run_dir), agent_runner=unexpected, decision_runner=unexpected)
            repeated = self.run_step(run_dir, read_state(run_dir), agent_runner=unexpected, decision_runner=unexpected)
            self.assertEqual(recovered["status"], "success")
            self.assertIn("确认既有成功", repeated["summary"])
            (workspace / BACKLOG_PATH).write_text("漂移\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "漂移"):
                self.run_step(run_dir, read_state(run_dir), agent_runner=unexpected)

    def test_production_git_reads_are_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            with patch.object(breakdown_step.subprocess, "run", wraps=subprocess.run) as mocked:
                breakdown_step.validate_inputs(run_dir, state)
                breakdown_step._verify_worktree_boundary(workspace, ["root", "frontend"])
                breakdown_step._document_tracked(workspace)
            commands = [tuple(call.args[0][1:]) for call in mocked.call_args_list]
            allowed = {
                ("rev-parse", "--show-toplevel"),
                ("branch", "--show-current"),
                ("status", "--porcelain=v1", "--untracked-files=all"),
                ("status", "--porcelain=v1", "--untracked-files=all", "--", BACKLOG_PATH.as_posix()),
                ("ls-files", "--error-unmatch", "--", BACKLOG_PATH.as_posix()),
            }
            self.assertTrue(commands)
            self.assertTrue(all(item in allowed for item in commands))
            self.assertFalse({"add", "commit", "switch", "checkout", "reset", "log", "diff"} & {item[0] for item in commands})


if __name__ == "__main__":
    unittest.main()
