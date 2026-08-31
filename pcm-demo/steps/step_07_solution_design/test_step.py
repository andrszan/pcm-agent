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
from common.files import write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_03_foundation_selection.step import TemplateSelection
from steps.step_05_project_readiness.step import (
    readiness_baseline,
    result as readiness_result,
)
from steps.step_07_solution_design.step import (
    CURRENT_NODE,
    DECISION_LOOP_SPEC,
    DESIGN_PATH,
    DESIGN_REPAIR_PROMPT,
    LEGACY_COMPLETION_MESSAGES,
    NEXT_NODE,
    SOLUTION_DESIGN_MAX_TURNS,
    SolutionDesignBlocked,
    run,
)


def agent_result(
    *,
    cwd: Path,
    session: str = "session-1",
    text: str = "总体方案完整回复",
    skills: list[str] | None = None,
) -> ClaudeRunResult:
    loaded = ["solution-design"] if skills is None else skills
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


class SolutionDesignTests(unittest.TestCase):
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
            readiness_result(
                "success",
                "准备基线已完成。",
                outputs=[checklist],
                readiness_baseline=readiness_baseline(
                    workspace, [requirements, features]
                ),
            ),
        )
        write_json(
            run_dir / "steps/06.json",
            {
                "step": 6,
                "status": "success",
                "applicable": applicable,
                "outputs": outputs,
                "tailwind_theme": "frontend" in outputs,
            },
        )
        root_repository = initialize_root_repository(workspace)
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": "project_initialization",
            "step": 7,
            "current_step": 7,
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

    @staticmethod
    def write_design(workspace: Path) -> None:
        path = workspace / DESIGN_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 总体技术方案\n\n存在风险和待确认事项。\n", encoding="utf-8")

    def test_completed_repair_resumes_same_session_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []
            system_prompts: list[str] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    self.write_design(workspace)
                current = agent_result(
                    cwd=kwargs["cwd"], text=f"总体方案回复 {len(calls)}"  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                self.assertEqual(messages[-1]["content"], f"总体方案回复 {len(system_prompts) + 1}")
                system_prompts.append(system_prompt)
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["outputs"], [DESIGN_PATH.as_posix()])
            self.assertEqual(len(calls), 2)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertEqual(calls[1]["prompt"], DESIGN_REPAIR_PROMPT)
            prompt = calls[0]["prompt"]
            self.assertTrue(prompt.startswith("/solution-design\n"))
            self.assertIn("docs/requirements/项目需求说明.md", prompt)
            self.assertIn("docs/design/技术方案.md", prompt)
            self.assertIn("系统上下文与边界", prompt)
            self.assertIn("不得实现或修改业务代码", prompt)
            for forbidden in (
                "git_url",
                "origin",
                "第 7 步",
                "PCM",
                "节点",
                "阶段",
                "调用Skill",
                "扫描所有README/manifest/代码",
                "README、manifest、锁文件、配置、代码、测试",
            ):
                self.assertNotIn(forbidden, prompt)
            self.assertEqual(calls[0]["max_turns"], SOLUTION_DESIGN_MAX_TURNS)
            self.assertNotIn("max_budget_usd", calls[0])
            self.assertEqual(len(system_prompts), 2)
            for system_prompt in system_prompts:
                for tag in ("role", "project_context", "responsibility", "completion", "output"):
                    self.assertIn(f"<{tag}>", system_prompt)
                    self.assertIn(f"</{tag}>", system_prompt)
                for required in (
                    "最高项目负责人、工程负责人、专业开发者和 Agent 专家",
                    "assistant 是你此前发给 Agent 的指令或结构化回复",
                    "user 是 Agent 返回给你的完整执行结果",
                    "固定技术方案文档已写入",
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
            self.assertEqual((saved["step"], saved["current_node"]), (8, NEXT_NODE))
            history = json.loads(
                (run_dir / "conversations/solution_design.json").read_text(encoding="utf-8")
            )["messages"]
            self.assertEqual(
                [item["role"] for item in history],
                ["system", "assistant", "user", "assistant", "assistant", "user", "assistant"],
            )
            self.assertEqual(json.loads(history[-1]["content"])["verdict"], "completed")
            self.assertNotIn(LEGACY_COMPLETION_MESSAGES[0], [item["content"] for item in history])

            saved.pop("solution_design", None)
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

    def test_agent_reply_is_preserved_as_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            agent_text = "完整 Agent 原文，包含方案完成情况与后续事项。"

            async def interrupted_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=kwargs["cwd"], text=agent_text)  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                raise OSError("模拟进程中断")

            with self.assertRaisesRegex(RuntimeError, "Agent SDK 执行异常"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=interrupted_agent,
                    config_loader=lambda: object(),
                )
            saved = read_state(run_dir)
            self.assertEqual(saved["solution_design"]["pending_agent_text"], agent_text)
            self.write_design(workspace)
            observed: list[str] = []

            async def completed(messages, config, *, system_prompt):
                observed.append(messages[-1]["content"])
                return decision("completed")

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("已保存回复应先进入决策")

            outcome = self.run_step(
                run_dir,
                saved,
                agent_runner=unexpected_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(observed, [agent_text])
            history = json.loads(
                (run_dir / "conversations/solution_design.json").read_text(encoding="utf-8")
            )["messages"]
            self.assertIn({"role": "user", "content": agent_text}, history)

    def test_blocked_decision_preserves_fixed_document_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            self.write_design(workspace)

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

            with self.assertRaises(SolutionDesignBlocked) as raised:
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=blocked,
                    config_loader=lambda: object(),
                )
            self.assertEqual(raised.exception.required_inputs, ["外部授权"])
            self.assertEqual(raised.exception.outputs, [DESIGN_PATH.as_posix()])

    def test_blocked_decision_rechecks_git_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            self.write_design(workspace)

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

    def test_staged_changes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                self.write_design(workspace)
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
                    agent_runner=fake_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )

    def test_child_repository_changes_are_rejected(self) -> None:
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

    def test_step_six_tailwind_theme_marker_must_match_frontend(self) -> None:
        for marker in (None, False, 1):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                run_dir, _, state = self.make_run(Path(directory))
                step_six_path = run_dir / "steps/06.json"
                payload = json.loads(step_six_path.read_text(encoding="utf-8"))
                if marker is None:
                    payload.pop("tailwind_theme", None)
                else:
                    payload["tailwind_theme"] = marker
                write_json(step_six_path, payload)

                async def unexpected(*args, **kwargs):
                    raise AssertionError("无效第 6 步 marker 不应调用 Agent")

                with self.assertRaisesRegex(RuntimeError, "不可复用"):
                    self.run_step(run_dir, state, agent_runner=unexpected)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory), applicable=False)
            step_six_path = run_dir / "steps/06.json"
            payload = json.loads(step_six_path.read_text(encoding="utf-8"))
            payload["tailwind_theme"] = True
            write_json(step_six_path, payload)

            async def unexpected(*args, **kwargs):
                raise AssertionError("无 frontend 却标记主题成功不应调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "不可复用"):
                self.run_step(run_dir, state, agent_runner=unexpected)

    def test_failed_result_file_does_not_block_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            write_json(run_dir / "steps/07.json", {"step": 7, "status": "failed"})

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                self.write_design(workspace)
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

    def test_no_applicable_engine_still_generates_fixed_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), applicable=False)
            calls = 0

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                nonlocal calls
                calls += 1
                self.write_design(workspace)
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(calls, 1)
            self.assertEqual(outcome["outputs"], [DESIGN_PATH.as_posix()])


if __name__ == "__main__":
    unittest.main()
