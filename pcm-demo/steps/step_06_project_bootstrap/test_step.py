from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.files import write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_03_foundation_selection.step import TemplateSelection
from steps.step_06_project_bootstrap.step import (
    COVERAGE_ARTIFACT_REPAIR_PROMPT,
    CURRENT_NODE,
    DECISION_LOOP_SPEC,
    LEGACY_COMPLETION_MESSAGES,
    NEXT_NODE,
    PROJECT_BOOTSTRAP_MAX_BUDGET_USD,
    PROJECT_BOOTSTRAP_MAX_TURNS,
    README_REPAIR_PROMPT,
    ProjectBootstrapBlocked,
    run,
)


def agent_result(
    *,
    cwd: Path,
    session: str = "session-1",
    text: str = "项目化完整回复",
    skills: list[str] | None = None,
) -> ClaudeRunResult:
    loaded = ["project-bootstrap"] if skills is None else skills
    return ClaudeRunResult(
        init={"cwd": str(cwd), "skills": loaded, "slash_commands": loaded},
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
    reason: str = "完成条件已经满足",
    required_inputs: list[str] | None = None,
) -> tuple[dict, int, str]:
    data = {
        "verdict": verdict,
        "answer": answer,
        "reason": reason,
        "required_inputs": required_inputs or [],
    }
    return data, 1, json.dumps(data, ensure_ascii=False)


class ProjectBootstrapTests(unittest.TestCase):
    def make_run(
        self, root: Path, *, applicable: bool = True
    ) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        (workspace / "docs/requirements").mkdir(parents=True)
        requirements = "docs/requirements/项目需求说明.md"
        features = "docs/requirements/产品功能说明.md"
        checklist = "docs/requirements/项目准备清单.md"
        for output in (requirements, features, checklist):
            (workspace / output).write_text(f"# {Path(output).stem}\n", encoding="utf-8")

        frontend = None
        outputs: list[str] = []
        assembly_frontend = None
        if applicable:
            (workspace / "frontend").mkdir()
            (workspace / "frontend/package.json").write_text("{}\n", encoding="utf-8")
            initialize_root_repository(workspace / "frontend")
            frontend = TemplateSelection(
                id="frontend-template",
                git_url="file:///templates.git",
                default_branch="main",
                path="templates/frontend",
                reason="test",
            ).model_dump(mode="json")
            outputs = ["frontend"]
            assembly_frontend = {
                "target": "frontend",
                "id": "frontend-template",
                "git_url": "file:///templates.git",
                "default_branch": "main",
                "path": "templates/frontend",
                "origin": "file:///templates.git",
                "branch": "main",
                "commit_sha": "a" * 40,
            }

        write_json(
            run_dir / "steps/02.json",
            {"step": 2, "status": "success", "outputs": [requirements, features]},
        )
        write_json(
            run_dir / "steps/03.json",
            {
                "step": 3,
                "status": "success",
                "template_selection": {"frontend": frontend, "backend": None},
            },
        )
        write_json(
            run_dir / "steps/04.json",
            {
                "step": 4,
                "status": "success",
                "applicable": applicable,
                "outputs": outputs,
                "assembly": {"frontend": assembly_frontend, "backend": None},
            },
        )
        write_json(
            run_dir / "steps/05.json",
            {"step": 5, "status": "success", "outputs": [checklist]},
        )
        root_repository = initialize_root_repository(workspace)
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": "project_initialization",
            "step": 6,
            "current_step": 6,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "root_repository": root_repository,
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    def run_step(self, run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    def test_completed_repair_resumes_same_session_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []
            system_prompts: list[str] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                current = agent_result(
                    cwd=kwargs["cwd"], text=f"项目化回复 {len(calls)}"  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                self.assertEqual(messages[-1]["content"], f"项目化回复 {len(system_prompts) + 1}")
                system_prompts.append(system_prompt)
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["outputs"], ["frontend"])
            self.assertEqual(len(calls), 2)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertEqual(calls[1]["prompt"], README_REPAIR_PROMPT)
            prompt = calls[0]["prompt"]
            self.assertTrue(prompt.startswith("/project-bootstrap\n"))
            self.assertIn("docs/requirements/项目需求说明.md", prompt)
            self.assertIn("@./frontend", prompt)
            self.assertIn("产品根 README", prompt)
            self.assertIn("真实浏览器", prompt)
            self.assertIn("不得初始化、暂存、提交", prompt)
            for forbidden in ("git_url", "origin", "第 6 步", "PCM", "节点", "阶段", "调用Skill"):
                self.assertNotIn(forbidden, prompt)
            self.assertEqual(calls[0]["max_turns"], PROJECT_BOOTSTRAP_MAX_TURNS)
            self.assertEqual(calls[0]["max_budget_usd"], PROJECT_BOOTSTRAP_MAX_BUDGET_USD)
            self.assertEqual(len(system_prompts), 2)
            for system_prompt in system_prompts:
                for tag in ("role", "project_context", "responsibility", "completion", "output"):
                    self.assertIn(f"<{tag}>", system_prompt)
                    self.assertIn(f"</{tag}>", system_prompt)
                for required in (
                    "最高项目负责人、工程负责人、专业开发者和 Agent 专家",
                    "assistant 是你此前发给 Agent 的指令或结构化回复",
                    "user 是 Agent 返回给你的完整执行结果",
                    "产品根 README 和各适用工程的项目身份",
                    "# 项目需求说明",
                    "# 产品功能说明",
                    "# 项目准备清单",
                    '"frontend"',
                    '"commit_sha"',
                ):
                    self.assertIn(required, system_prompt)
                self.assertNotEqual(system_prompt, DECISION_LOOP_SPEC.decision_system_prompt)
                for forbidden in ("file:///templates.git", "git_url", "origin"):
                    self.assertNotIn(forbidden, system_prompt)

            saved = read_state(run_dir)
            self.assertEqual((saved["step"], saved["current_node"]), (7, NEXT_NODE))
            history = json.loads(
                (run_dir / "conversations/project_bootstrap.json").read_text(encoding="utf-8")
            )["messages"]
            self.assertEqual(
                [item["role"] for item in history],
                ["system", "assistant", "user", "assistant", "assistant", "user", "assistant"],
            )
            self.assertEqual(json.loads(history[-1]["content"])["verdict"], "completed")
            self.assertNotIn(LEGACY_COMPLETION_MESSAGES[0], [item["content"] for item in history])

            saved.pop("project_bootstrap", None)
            saved.pop("claude_sessions", None)
            saved.pop("decision_conversations", None)
            write_state(run_dir, saved)

            async def unexpected(*args, **kwargs):
                raise AssertionError("既有成功不应调用 Agent 或决策模型")

            reused = self.run_step(
                run_dir,
                saved,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(reused["status"], "success")
            self.assertIn("确认既有成功", reused["summary"])

    def test_unignored_coverage_artifact_uses_same_session_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
            coverage = workspace / ".coverage"
            coverage.write_bytes(b"coverage")
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    coverage.unlink()
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

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
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertEqual(calls[1]["prompt"], COVERAGE_ARTIFACT_REPAIR_PROMPT)

    def test_blocked_decision_preserves_domain_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked(messages, config, *, system_prompt):
                return decision(
                    "blocked",
                    reason="缺少不可替代授权",
                    required_inputs=["外部授权"],
                )

            with self.assertRaises(ProjectBootstrapBlocked) as raised:
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=blocked,
                    config_loader=lambda: object(),
                )
            self.assertEqual(raised.exception.required_inputs, ["外部授权"])
            self.assertEqual(raised.exception.outputs, ["frontend"])
            self.assertTrue(workspace.is_dir())

    def test_blocked_decision_rechecks_git_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def staging_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                subprocess.run(
                    ["git", "add", "README.md"],
                    cwd=workspace,
                    check=True,
                    capture_output=True,
                )
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked(messages, config, *, system_prompt):
                return decision(
                    "blocked",
                    reason="缺少不可替代授权",
                    required_inputs=["外部授权"],
                )

            with self.assertRaisesRegex(RuntimeError, "不得暂存文件"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=staging_agent,
                    decision_runner=blocked,
                    config_loader=lambda: object(),
                )

    def test_blocked_decision_rechecks_coverage_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / ".coverage").write_bytes(b"coverage")

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked(messages, config, *, system_prompt):
                return decision(
                    "blocked",
                    reason="缺少不可替代授权",
                    required_inputs=["外部授权"],
                )

            with self.assertRaisesRegex(RuntimeError, "覆盖率数据库"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=blocked,
                    config_loader=lambda: object(),
                )

    def test_root_and_child_repository_changes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def staging_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                subprocess.run(
                    ["git", "add", "README.md"], cwd=workspace, check=True, capture_output=True
                )
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            with self.assertRaisesRegex(RuntimeError, "完成核验失败"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=staging_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )

        for mutation in ("staged", "committed", "non-main"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                frontend = workspace / "frontend"
                if mutation == "staged":
                    subprocess.run(
                        ["git", "add", "package.json"], cwd=frontend, check=True, capture_output=True
                    )
                elif mutation == "committed":
                    subprocess.run(
                        ["git", "add", "package.json"], cwd=frontend, check=True, capture_output=True
                    )
                    subprocess.run(
                        [
                            "git",
                            "-c",
                            "user.name=PCM Test",
                            "-c",
                            "user.email=pcm@example.invalid",
                            "commit",
                            "-m",
                            "test",
                        ],
                        cwd=frontend,
                        check=True,
                        capture_output=True,
                    )
                else:
                    subprocess.run(
                        ["git", "switch", "-c", "feature"],
                        cwd=frontend,
                        check=True,
                        capture_output=True,
                    )

                async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("子仓边界异常不应调用 Agent")

                with self.assertRaisesRegex(RuntimeError, "Git 仓库"):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=unexpected_agent,
                        config_loader=lambda: object(),
                    )

    def test_failed_result_file_does_not_block_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            write_json(run_dir / "steps/06.json", {"step": 6, "status": "failed"})

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

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

    def test_no_applicable_foundation_skips_without_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory), applicable=False)

            async def unexpected(*args, **kwargs):
                raise AssertionError("无适用工程不应调用 Agent 或决策模型")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(outcome["status"], "success")
            self.assertFalse(outcome["applicable"])
            self.assertEqual(outcome["outputs"], [])

    def test_cli_requires_run_id_and_handles_corrupt_state(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(DEMO_ROOT / "run_step.py"), "--step", "6"],
            cwd=DEMO_ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("第 6 步执行失败", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

        run_dir = DEMO_ROOT / "runs" / "corrupt-step-six-test"
        if run_dir.exists():
            self.skipTest("本地测试 run 已存在")
        try:
            (run_dir / "steps").mkdir(parents=True)
            (run_dir / "state.json").write_text("{invalid", encoding="utf-8")
            broken = subprocess.run(
                [
                    sys.executable,
                    str(DEMO_ROOT / "run_step.py"),
                    "--step",
                    "6",
                    "--run-id",
                    run_dir.name,
                ],
                cwd=DEMO_ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(broken.returncode, 1)
            self.assertNotIn("Traceback", broken.stderr)
            saved = json.loads((run_dir / "steps/06.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "failed")
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)


if __name__ == "__main__":
    unittest.main()
