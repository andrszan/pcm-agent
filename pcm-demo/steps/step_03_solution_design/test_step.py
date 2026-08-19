from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.state import read_state, write_state
from run_step import main as run_step_main
from steps.step_03_solution_design.step import (
    OUTPUTS,
    SolutionDesignBlocked,
    decision_prompt,
    run,
)


def agent_result(*, session: str = "session-3", text: str = "需要确认") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={"skills": ["solution-design"], "slash_commands": ["solution-design"]},
        text=text,
        result_subtype="success",
        is_error=False,
        session_id=session,
        stop_reason="end_turn",
        num_turns=1,
        total_cost_usd=0.1,
        exception=None,
    )


class SolutionDesignTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        (run_dir / "logs").mkdir()
        workspace = root / "workspace"
        requirements = workspace / "docs/requirements"
        requirements.mkdir(parents=True)
        (requirements / "项目需求说明.md").write_text("# 项目需求\n", encoding="utf-8")
        (requirements / "产品功能说明.md").write_text("# 产品功能\n", encoding="utf-8")
        template_assets = root / "template-assets"
        template_assets.mkdir()
        (template_assets / "repositories.yaml").write_text(
            "repositories:\n  - id: frontend\n  - id: backend\n", encoding="utf-8"
        )
        (template_assets / "templates.yaml").write_text(
            "templates:\n  - id: frontend-template\n  - id: backend-template\n",
            encoding="utf-8",
        )
        state = {
            "run_id": "test",
            "status": "success",
            "current_step": 2,
            "workspace": {"final_path": str(workspace)},
        }
        write_state(run_dir, state)
        return run_dir, workspace, template_assets, state

    def write_outputs(self, workspace: Path) -> None:
        technical, sources = (workspace / relative for relative in OUTPUTS)
        technical.parent.mkdir(parents=True, exist_ok=True)
        technical.write_text("# 技术方案\n", encoding="utf-8")
        sources.write_text(
            json.dumps(
                {
                    "frontend": {
                        "target_path": "frontend",
                        "repository_id": "frontend",
                        "template_id": "frontend-template",
                        "template_path": "templates/frontend-template",
                        "adoption": "direct",
                    },
                    "backend": {
                        "target_path": "backend",
                        "repository_id": "backend",
                        "template_id": "backend-template",
                        "template_path": "templates/backend-template",
                        "adoption": "direct",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_template_assets_are_required_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, template_assets, state = self.make_run(Path(directory))
            (template_assets / "templates.yaml").unlink()
            with self.assertRaisesRegex(RuntimeError, "templates.yaml"):
                asyncio.run(run(run_dir, state, template_assets))

    def test_existing_success_does_not_call_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, template_assets, state = self.make_run(Path(directory))
            self.write_outputs(workspace)
            state.update(
                {
                    "status": "success",
                    "current_step": 3,
                    "solution_design": {
                        "last_agent_result": {"subtype": "success", "is_error": False}
                    },
                }
            )
            write_state(run_dir, state)

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("既有成功不应再次调用 Agent")

            outcome = asyncio.run(
                run(run_dir, state, template_assets, agent_runner=unexpected_agent)
            )
            self.assertEqual(outcome["status"], "success")
            self.assertIn("确认既有成功", outcome["summary"])

    def test_missing_outputs_runs_decision_then_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, template_assets, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs):
                calls.append({"prompt": prompt, **kwargs})
                current = agent_result()
                kwargs["on_update"](current)
                if len(calls) == 2:
                    self.write_outputs(workspace)
                return current

            async def fake_decision(messages, config):
                decision = {
                    "action": "approve",
                    "answer": "批准",
                    "reason": "输入足够",
                    "required_inputs": [],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with patch(
                "steps.step_03_solution_design.step.LLMConfig.load", return_value=object()
            ):
                outcome = asyncio.run(
                    run(
                        run_dir,
                        state,
                        template_assets,
                        agent_runner=fake_agent,
                        decision_runner=fake_decision,
                    )
                )

            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(calls[1]["resume_session_id"], "session-3")
            self.assertIn("明确同意", calls[1]["prompt"])
            self.assertIn(str(template_assets), calls[0]["prompt"])
            saved = read_state(run_dir)
            self.assertEqual(
                saved["solution_design"]["template_assets"], str(template_assets.resolve())
            )
            self.assertEqual(
                saved["decision_conversations"]["solution_design"],
                {"path": "conversations/solution_design.json", "turn": 1},
            )

    def test_structured_blocked_stops_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, template_assets, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs):
                current = agent_result()
                kwargs["on_update"](current)
                return current

            async def fake_decision(messages, config):
                decision = {
                    "action": "blocked",
                    "answer": "需要模板读取权限",
                    "reason": "环境无法取得",
                    "required_inputs": ["TEMPLATE_REPOSITORY_ACCESS"],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with (
                patch(
                    "steps.step_03_solution_design.step.LLMConfig.load",
                    return_value=object(),
                ),
                self.assertRaises(SolutionDesignBlocked) as raised,
            ):
                asyncio.run(
                    run(
                        run_dir,
                        state,
                        template_assets,
                        agent_runner=fake_agent,
                        decision_runner=fake_decision,
                    )
                )
            self.assertEqual(
                raised.exception.required_inputs, ["TEMPLATE_REPOSITORY_ACCESS"]
            )

    def test_skill_must_be_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, template_assets, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs):
                return ClaudeRunResult(
                    init={"skills": [], "slash_commands": []},
                    text="",
                    result_subtype="success",
                    is_error=False,
                    session_id="session-3",
                    stop_reason="end_turn",
                    num_turns=1,
                    total_cost_usd=0.1,
                    exception=None,
                )

            with self.assertRaisesRegex(RuntimeError, "未加载 solution-design Skill"):
                asyncio.run(
                    run(run_dir, state, template_assets, agent_runner=fake_agent)
                )

    def test_invalid_source_json_is_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, template_assets, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs):
                current = agent_result()
                kwargs["on_update"](current)
                technical, sources = (workspace / relative for relative in OUTPUTS)
                technical.parent.mkdir(parents=True, exist_ok=True)
                technical.write_text("# 技术方案\n", encoding="utf-8")
                sources.write_text("{}\n", encoding="utf-8")
                return current

            async def blocked_decision(messages, config):
                decision = {
                    "action": "blocked",
                    "answer": "停止",
                    "reason": "测试结束",
                    "required_inputs": ["VALID_OUTPUT"],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with (
                patch(
                    "steps.step_03_solution_design.step.LLMConfig.load",
                    return_value=object(),
                ),
                self.assertRaises(SolutionDesignBlocked),
            ):
                asyncio.run(
                    run(
                        run_dir,
                        state,
                        template_assets,
                        agent_runner=fake_agent,
                        decision_runner=blocked_decision,
                    )
                )

    def test_budget_result_continues_with_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, template_assets, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs):
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 1:
                    current = ClaudeRunResult(
                        init={
                            "skills": ["solution-design"],
                            "slash_commands": ["solution-design"],
                        },
                        text="预算达到上限前尚未完成",
                        result_subtype="error_max_budget_usd",
                        is_error=True,
                        session_id="session-3",
                        stop_reason="tool_use",
                        num_turns=7,
                        total_cost_usd=2.0,
                        exception="Exception: Reached maximum budget",
                    )
                else:
                    current = agent_result()
                    self.write_outputs(workspace)
                kwargs["on_update"](current)
                return current

            async def fake_decision(messages, config):
                decision = {
                    "action": "continue",
                    "answer": "继续",
                    "reason": "已有 session 可恢复",
                    "required_inputs": [],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with patch(
                "steps.step_03_solution_design.step.LLMConfig.load", return_value=object()
            ):
                outcome = asyncio.run(
                    run(
                        run_dir,
                        state,
                        template_assets,
                        agent_runner=fake_agent,
                        decision_runner=fake_decision,
                    )
                )

            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["resume_session_id"], "session-3")
            history = json.loads(
                (run_dir / "conversations/solution_design.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [message["role"] for message in history["messages"]],
                ["system", "assistant", "user", "assistant", "user", "assistant"],
            )
            self.assertIn("发送给 Claude Agent SDK 的指令", history["messages"][3]["content"])
            self.assertIn("已完成 solution-design", history["messages"][5]["content"])
            self.assertEqual(
                read_state(run_dir)["decision_conversations"]["solution_design"]["turn"],
                1,
            )

    def test_cli_accepts_step_result_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, template_assets, state = self.make_run(Path(directory))
            expected = {
                "step": 3,
                "name": "总体技术方案",
                "status": "success",
                "summary": "完成",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
            }
            args = Namespace(
                step=3,
                product_draft=None,
                workspace_root=None,
                template_assets=template_assets,
                run_id="test",
            )
            with (
                patch("run_step.parse_args", return_value=args),
                patch("run_step.run_dir_for", return_value=run_dir),
                patch("run_step.read_state", return_value=state),
                patch("run_step.run_solution_design", return_value=expected),
            ):
                exit_code = run_step_main()
            self.assertEqual(exit_code, 0)

    def test_approve_is_explicit_developer_authorization(self) -> None:
        prompt = decision_prompt(
            {"action": "approve", "answer": "批准", "reason": "足够", "required_inputs": []}
        )
        self.assertIn("等效开发者授权", prompt)
        self.assertIn("明确同意", prompt)


if __name__ == "__main__":
    unittest.main()
