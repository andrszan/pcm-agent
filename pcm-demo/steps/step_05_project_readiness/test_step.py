from __future__ import annotations

import asyncio
import copy
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
from common.decision import AgentDecision
from common.files import write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_03_foundation_selection.step import FoundationSelectionResult, TemplateSelection
from steps.step_05_project_readiness.step import (
    CHECKLIST,
    CURRENT_NODE,
    NEXT_NODE,
    PROJECT_READINESS_DECISION_RULES,
    ProjectReadinessBlocked,
    checklist_contents,
    checklist_present,
    initial_prompt,
    readiness_baseline,
    run,
)


def agent_result(*, cwd: Path, session: str = "session-1", text: str = "清单已处理") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": ["project-readiness"],
            "slash_commands": ["project-readiness"],
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
) -> AgentDecision:
    return AgentDecision(
        verdict=verdict,
        answer=answer,
        reason=reason,
        required_inputs=required_inputs or [],
    )


class ProjectReadinessTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        (workspace / "docs/requirements").mkdir(parents=True)
        (workspace / "frontend").mkdir(parents=True)
        (workspace / "frontend/app.py").write_text("pass\n", encoding="utf-8")
        initialize_root_repository(workspace / "frontend")
        requirements = "docs/requirements/项目需求说明.md"
        features = "docs/requirements/产品功能说明.md"
        for output in (requirements, features):
            (workspace / output).write_text("# 定义\n", encoding="utf-8")
        selection = {
            "frontend": TemplateSelection(
                id="frontend-template",
                git_url="file:///templates.git",
                default_branch="main",
                path="templates/frontend",
                reason="test",
            ).model_dump(mode="json"),
            "backend": None,
        }
        write_json(
            run_dir / "steps/02.json",
            {"step": 2, "status": "success", "outputs": [requirements, features]},
        )
        write_json(
            run_dir / "steps/03.json",
            {"step": 3, "status": "success", "template_selection": selection},
        )
        write_json(
            run_dir / "steps/04.json",
            {
                "step": 4,
                "status": "success",
                "applicable": True,
                "outputs": ["frontend"],
                "assembly": {
                    "frontend": {
                        "target": "frontend",
                        "id": "frontend-template",
                        "git_url": "file:///templates.git",
                        "default_branch": "main",
                        "path": "templates/frontend",
                        "origin": "file:///templates.git",
                        "branch": "main",
                        "commit_sha": "a" * 40,
                    },
                    "backend": None,
                },
            },
        )
        root_repository = initialize_root_repository(workspace)
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": "project_initialization",
            "step": 5,
            "current_step": 5,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "root_repository": root_repository,
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        resource_list = root / "可信开发资源清单.md"
        resource_list.write_text("资源清单正文不应内联\n", encoding="utf-8")
        return run_dir, workspace, state

    def run_step(self, run_dir: Path, state: dict, **kwargs: object) -> dict:
        resource_list = run_dir.parent / "可信开发资源清单.md"
        return asyncio.run(
            run(
                run_dir,
                state,
                resource_loader=lambda: (resource_list, "test"),
                **kwargs,
            )
        )

    def selection(self) -> FoundationSelectionResult:
        return FoundationSelectionResult(
            frontend=TemplateSelection(
                id="frontend-template",
                git_url="file:///templates.git",
                default_branch="main",
                path="templates/frontend",
                reason="test",
            ),
            backend=None,
        )

    def product_outputs(self) -> list[str]:
        return [
            "docs/requirements/项目需求说明.md",
            "docs/requirements/产品功能说明.md",
        ]

    def success_result(self, workspace: Path) -> dict[str, object]:
        return {
            "step": 5,
            "name": "核验项目准备状态",
            "status": "success",
            "summary": "project-readiness 已建立并验证当前项目周期的完整准备基线。",
            "applicable": True,
            "outputs": [CHECKLIST.as_posix()],
            "blocked": None,
            "error": None,
            "readiness_baseline": readiness_baseline(
                workspace, self.product_outputs()
            ),
        }

    def test_initial_prompt_uses_authoritative_inputs_and_minimal_selection_projection(self) -> None:
        prompt = initial_prompt(
            ["docs/requirements/项目需求说明.md", "docs/requirements/产品功能说明.md"],
            ["frontend"],
            self.selection(),
            Path("/resource-list"),
        )

        self.assertEqual(prompt.splitlines()[0], "/project-readiness")
        self.assertIn("产品定义是当前最终产品范围的权威输入", prompt)
        self.assertIn("实际工程", prompt)
        self.assertIn("可信开发资源清单：@/resource-list", prompt)
        self.assertIn("任意格式的动态候选池", prompt)
        self.assertIn("当前项目周期唯一的完整准备基线", prompt)
        self.assertIn("实际 `.env`", prompt)
        self.assertIn("`.env.example`", prompt)
        self.assertIn("最终写入项目配置的运行凭据", prompt)
        self.assertIn("任何最终范围必要条件", prompt)
        self.assertIn("完整依赖安装、构建、测试、应用启动", prompt)
        self.assertNotIn("当前只核验进入基础工程项目化前条件", prompt)
        self.assertIn('"applicable": true', prompt)
        self.assertIn('"id": "frontend-template"', prompt)
        self.assertIn('"default_branch": "main"', prompt)
        self.assertIn('"path": "templates/frontend"', prompt)
        self.assertIn('"reason": "test"', prompt)
        self.assertNotIn("file:///templates.git", prompt)
        self.assertNotIn("git_url", prompt)
        self.assertNotIn("origin", prompt)
        for forbidden in ("第 5 步", "第5步", "PCM", "节点", "阶段", "调用 Skill"):
            self.assertNotIn(forbidden, prompt)
            self.assertNotIn(forbidden, PROJECT_READINESS_DECISION_RULES)

    def test_completed_decision_advances_after_checklist_and_preserves_agent_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            decision_inputs: list[list[dict[str, str]]] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
                current = agent_result(cwd=workspace, text="完整 Agent 原文")
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def fake_decision(
                messages: list[dict[str, str]],
                config: object,
                *,
                system_prompt: str,
            ) -> tuple[dict[str, object], int, str]:
                for tag in ("role", "project_context", "responsibility", "completion", "output"):
                    self.assertIn(f"<{tag}>", system_prompt)
                    self.assertIn(f"</{tag}>", system_prompt)
                for required in (
                    "最高项目负责人、工程负责人、专业开发者和 Agent 专家",
                    "assistant 是你此前发给 Agent 的指令或结构化回复",
                    "user 是 Agent 返回给你的完整执行结果",
                    "当前项目周期唯一、完整的准备基线",
                    "不存在必要的 missing、pending 或未验证条件",
                    "最终项目运行凭据",
                    "清单文字或 Agent 自述不能单独证明 ready",
                    "# 定义",
                    "适用工程",
                    "基础工程选择",
                    '"readable": true',
                ):
                    self.assertIn(required, system_prompt)
                self.assertNotEqual(system_prompt, PROJECT_READINESS_DECISION_RULES)
                self.assertIn(str((run_dir.parent / "可信开发资源清单.md").resolve()), system_prompt)
                for forbidden in ("资源清单正文不应内联", "file:///templates.git", "git_url", "origin"):
                    self.assertNotIn(forbidden, system_prompt)
                decision_inputs.append(copy.deepcopy(messages))
                current = decision("completed", reason="清单与当前事实均已核验")
                return current.model_dump(), 1, current.model_dump_json()

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=fake_decision,
                config_loader=lambda: object(),
            )

            self.assertEqual(outcome["outputs"], [CHECKLIST.as_posix()])
            self.assertEqual(decision_inputs[0][-1], {"role": "user", "content": "完整 Agent 原文"})
            saved = read_state(run_dir)
            self.assertEqual((saved["current_step"], saved["current_node"]), (6, NEXT_NODE))
            saved_result = json.loads((run_dir / "steps/05.json").read_text())
            self.assertEqual(saved_result["status"], "success")
            self.assertEqual(
                saved_result["readiness_baseline"],
                readiness_baseline(workspace, self.product_outputs()),
            )
            self.assertNotIn("pending_agent_prompt", saved["project_readiness"])
            history = json.loads(
                (run_dir / "conversations/project_readiness.json").read_text(encoding="utf-8")
            )["messages"]
            self.assertEqual(history[2], {"role": "user", "content": "完整 Agent 原文"})
            self.assertEqual(json.loads(history[3]["content"])["verdict"], "completed")
            self.assertNotIn("已完成 project-readiness", history[3]["content"])

    def test_completed_repair_then_completed_resumes_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict[str, object]] = []
            decision_inputs: list[list[dict[str, str]]] = []
            decisions = iter(
                [
                    decision("completed", reason="首次认为已完成"),
                    decision("completed", reason="清单补全后已完成"),
                ]
            )

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
                current = agent_result(cwd=workspace, text=f"Agent 原文 {len(calls)}")
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def fake_decision(messages, config, *, system_prompt):
                decision_inputs.append(copy.deepcopy(messages))
                current = next(decisions)
                return current.model_dump(), 1, current.model_dump_json()

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=fake_decision,
                config_loader=lambda: object(),
            )

            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertTrue(str(calls[0]["prompt"]).startswith("/project-readiness"))
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertIn("不要只补文档后宣称完成", str(calls[1]["prompt"]))
            self.assertIn("最终运行凭据最小权限验证", str(calls[1]["prompt"]))
            self.assertEqual(decision_inputs[0][-1], {"role": "user", "content": "Agent 原文 1"})
            self.assertNotIn("pending_agent_prompt", read_state(run_dir)["project_readiness"])

    def test_blocked_decision_maps_to_existing_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=workspace, text="缺少真实外部账号")
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def fake_decision(messages, config, *, system_prompt):
                current = decision(
                    "blocked",
                    reason="无法取得客户账号",
                    required_inputs=["客户提供真实账号"],
                )
                return current.model_dump(), 1, current.model_dump_json()

            with self.assertRaises(ProjectReadinessBlocked) as raised:
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=fake_decision,
                    config_loader=lambda: object(),
                )

            self.assertEqual(str(raised.exception), "无法取得客户账号")
            self.assertEqual(raised.exception.required_inputs, ["客户提供真实账号"])
            self.assertEqual(raised.exception.outputs, [])

    def test_blocked_decision_rechecks_git_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def staging_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                subprocess.run(
                    ["git", "add", "docs/requirements/项目需求说明.md"],
                    cwd=workspace,
                    check=True,
                    capture_output=True,
                )
                current = agent_result(cwd=workspace, text="缺少真实外部账号")
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked(messages, config, *, system_prompt):
                current = decision(
                    "blocked",
                    reason="无法取得客户账号",
                    required_inputs=["客户提供真实账号"],
                )
                return current.model_dump(), 1, current.model_dump_json()

            with self.assertRaisesRegex(RuntimeError, "不得暂存文件"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=staging_agent,
                    decision_runner=blocked,
                    config_loader=lambda: object(),
                )

    def test_failed_result_file_does_not_block_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            write_json(run_dir / "steps/05.json", {"step": 5, "status": "failed"})

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
                current = agent_result(cwd=workspace, text="已补全准备清单")
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                current = decision("completed", reason="准备清单已完成")
                return current.model_dump(), 1, current.model_dump_json()

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")

    def test_existing_success_result_and_domain_facts_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
            write_json(run_dir / "steps/05.json", self.success_result(workspace))
            state.update(
                {
                    "status": "success",
                    "step": 6,
                    "current_step": 6,
                    "current_node": NEXT_NODE,
                }
            )
            write_state(run_dir, state)

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("已有成功不应再次调用 Agent")

            outcome = self.run_step(run_dir, state, agent_runner=unexpected_agent)

        self.assertEqual(outcome["status"], "success")
        self.assertIn("确认既有成功", outcome["summary"])

    def test_existing_success_rejects_changed_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / CHECKLIST).write_text("# 已验证准备基线\n", encoding="utf-8")
            write_json(run_dir / "steps/05.json", self.success_result(workspace))
            state.update(
                {
                    "status": "success",
                    "step": 6,
                    "current_step": 6,
                    "current_node": NEXT_NODE,
                }
            )
            write_state(run_dir, state)
            (workspace / CHECKLIST).write_text("# 被替换的清单\n", encoding="utf-8")

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("准备基线漂移不应调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "准备基线不可复用"):
                self.run_step(run_dir, state, agent_runner=unexpected_agent)

    def test_existing_success_rejects_changed_product_definition(self) -> None:
        for output in self.product_outputs():
            with self.subTest(output=output), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                (workspace / CHECKLIST).write_text("# 已验证准备基线\n", encoding="utf-8")
                write_json(run_dir / "steps/05.json", self.success_result(workspace))
                state.update(
                    {
                        "status": "success",
                        "step": 6,
                        "current_step": 6,
                        "current_node": NEXT_NODE,
                    }
                )
                write_state(run_dir, state)
                (workspace / output).write_text("# 变化后的产品范围\n", encoding="utf-8")

                async def unexpected_agent(
                    *args: object, **kwargs: object
                ) -> ClaudeRunResult:
                    raise AssertionError("产品范围漂移不应调用 Agent")

                with self.assertRaisesRegex(RuntimeError, "准备基线不可复用"):
                    self.run_step(run_dir, state, agent_runner=unexpected_agent)

    def test_existing_success_without_baseline_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / CHECKLIST).write_text("# 旧准备清单\n", encoding="utf-8")
            write_json(
                run_dir / "steps/05.json",
                {"step": 5, "status": "success", "outputs": [CHECKLIST.as_posix()]},
            )
            state.update(
                {
                    "status": "success",
                    "step": 6,
                    "current_step": 6,
                    "current_node": NEXT_NODE,
                }
            )
            write_state(run_dir, state)

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("旧成功结果不应调用 Agent 或自动升级")

            with self.assertRaisesRegex(RuntimeError, "准备基线不可复用"):
                self.run_step(run_dir, state, agent_runner=unexpected_agent)

    def test_completed_verifier_rejects_handoff_conflict_and_nonregular_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / CHECKLIST).mkdir()
                current = agent_result(cwd=workspace, text="清单已完成")
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def fake_decision(messages, config, *, system_prompt):
                current = decision("completed", reason="已完成")
                return current.model_dump(), 1, current.model_dump_json()

            with self.assertRaisesRegex(RuntimeError, "完成核验失败"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=fake_decision,
                    config_loader=lambda: object(),
                )
            with self.assertRaisesRegex(RuntimeError, "不是普通文件"):
                checklist_contents(workspace)

    def test_checklist_rejects_symlinked_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            outside = root / "outside"
            (workspace / "docs").mkdir(parents=True)
            outside.mkdir()
            (outside / CHECKLIST.name).write_text("# 外部清单\n", encoding="utf-8")
            (workspace / "docs/requirements").symlink_to(outside, target_is_directory=True)
            self.assertFalse(checklist_present(workspace))

    def test_cli_requires_run_id_with_step_five_schema(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(DEMO_ROOT / "run_step.py"), "--step", "5"],
            cwd=DEMO_ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("第 5 步执行失败", completed.stderr)
        self.assertNotIn("TypeError", completed.stderr)


if __name__ == "__main__":
    unittest.main()
