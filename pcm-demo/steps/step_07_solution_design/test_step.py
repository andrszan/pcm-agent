from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.files import write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_03_foundation_selection.step import TemplateSelection
from steps.step_07_solution_design.step import (
    COMPLETION_MESSAGE,
    CURRENT_NODE,
    DESIGN_PATH,
    NEXT_NODE,
    SOLUTION_DESIGN_MAX_BUDGET_USD,
    SOLUTION_DESIGN_MAX_TURNS,
    SolutionDesignBlocked,
    SolutionDesignDecision,
    request_solution_design_decision,
    run,
    successful_agent,
)


def agent_result(
    *,
    cwd: Path,
    session: str | None = "session-1",
    text: str = "总体方案完整回复",
    subtype: str = "success",
    is_error: bool = False,
    exception: str | None = None,
    skills: list[str] | None = None,
) -> ClaudeRunResult:
    loaded = ["solution-design"] if skills is None else skills
    return ClaudeRunResult(
        init={"cwd": str(cwd), "skills": loaded, "slash_commands": loaded},
        text=text,
        result_subtype=subtype,
        is_error=is_error,
        session_id=session,
        stop_reason="end_turn",
        num_turns=1,
        total_cost_usd=0.1,
        exception=exception,
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
        write_json(
            run_dir / "steps/06.json",
            {
                "step": 6,
                "status": "success",
                "applicable": applicable,
                "outputs": outputs,
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

    def test_completed_decision_succeeds_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                self.write_design(kwargs["cwd"])  # type: ignore[arg-type]
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config):
                self.assertEqual(messages[-1]["content"], "总体方案完整回复")
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["outputs"], [DESIGN_PATH.as_posix()])
            self.assertIn("/solution-design", calls[0]["prompt"])
            self.assertIn("docs/requirements/项目需求说明.md", calls[0]["prompt"])
            self.assertIn("@./frontend", calls[0]["prompt"])
            self.assertIn("系统边界", calls[0]["prompt"])
            self.assertNotIn("git_url", calls[0]["prompt"])
            self.assertNotIn("origin", calls[0]["prompt"])
            self.assertNotIn("第 7 步", calls[0]["prompt"])
            self.assertNotIn("PCM", calls[0]["prompt"])
            self.assertEqual(calls[0]["max_turns"], SOLUTION_DESIGN_MAX_TURNS)
            self.assertEqual(calls[0]["max_budget_usd"], SOLUTION_DESIGN_MAX_BUDGET_USD)

            saved = read_state(run_dir)
            self.assertEqual((saved["step"], saved["current_node"]), (8, NEXT_NODE))
            history = json.loads(
                (run_dir / "conversations/solution_design.json").read_text(encoding="utf-8")
            )["messages"]
            self.assertEqual(
                [item["role"] for item in history],
                ["system", "assistant", "user", "assistant", "assistant"],
            )
            self.assertEqual(json.loads(history[-2]["content"])["verdict"], "completed")
            self.assertEqual(history[-1]["content"], COMPLETION_MESSAGE)

            async def unexpected(*args, **kwargs):
                raise AssertionError("成功复用不应调用 Agent 或决策模型")

            reused = self.run_step(
                run_dir,
                saved,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(reused["status"], "success")
            self.assertIn("确认既有成功", reused["summary"])

    def test_agent_reply_is_redacted_before_persistence_and_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            observed: list[str] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                self.write_design(kwargs["cwd"])  # type: ignore[arg-type]
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text='api_key=super-secret "password": "json-secret" "clientSecret":"camel-secret" postgresql://db-user:db-secret@example.invalid/db https://user:password@example.invalid/repo',
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config):
                observed.append(messages[-1]["content"])
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertNotIn("super-secret", observed[0])
            self.assertNotIn("json-secret", observed[0])
            self.assertNotIn("camel-secret", observed[0])
            self.assertNotIn("db-user:db-secret", observed[0])
            self.assertNotIn("user:password", observed[0])
            history = (run_dir / "conversations/solution_design.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("super-secret", history)
            self.assertNotIn("json-secret", history)
            self.assertNotIn("camel-secret", history)
            self.assertNotIn("db-user:db-secret", history)
            self.assertNotIn("user:password", history)

    def test_staged_changes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                self.write_design(kwargs["cwd"])  # type: ignore[arg-type]
                (workspace / "README.md").write_text("staged\n", encoding="utf-8")
                import subprocess

                subprocess.run(
                    ["git", "add", "README.md"],
                    cwd=workspace,
                    check=True,
                    capture_output=True,
                )
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            with self.assertRaisesRegex(RuntimeError, "不得暂存"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=lambda messages, config: _async_value(decision("completed")),
                    config_loader=lambda: object(),
                )

    def test_success_requires_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                self.write_design(kwargs["cwd"])  # type: ignore[arg-type]
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    session=None,
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            with self.assertRaisesRegex(RuntimeError, "session ID"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=lambda messages, config: _async_value(decision("completed")),
                    config_loader=lambda: object(),
                )

    def test_invalid_session_type_does_not_count_as_success(self) -> None:
        state = {
            "claude_sessions": {"solution_design": 1},
            "solution_design": {
                "last_agent_result": {"subtype": "success", "is_error": False}
            },
        }
        self.assertFalse(successful_agent(state))

    def test_continue_resumes_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                self.write_design(kwargs["cwd"])  # type: ignore[arg-type]
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text=f"总体方案回复 {len(calls)}",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            decisions = iter(
                [
                    decision("continue", answer="继续核对工程事实", reason="仍缺少事实核验"),
                    decision("completed"),
                ]
            )

            async def fake_decision(messages, config):
                return next(decisions)

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=fake_decision,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertEqual(calls[1]["prompt"], "继续核对工程事实")

    def test_completed_decision_requires_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            with self.assertRaisesRegex(RuntimeError, "技术方案文档"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=lambda messages, config: _async_value(decision("completed")),
                    config_loader=lambda: object(),
                )

    def test_saved_agent_reply_is_decided_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            self.write_design(workspace)
            state.update(
                {
                    "claude_sessions": {"solution_design": "session-1"},
                    "solution_design": {
                        "last_agent_result": {"subtype": "success", "is_error": False},
                        "pending_agent_text": "已保存的总体方案回复",
                    },
                    "decision_conversations": {
                        "solution_design": {
                            "path": "conversations/solution_design.json",
                            "turn": 0,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/solution_design.json",
                {"messages": [{"role": "system", "content": "system"}, {"role": "assistant", "content": "initial"}]},
            )

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("应先恢复已保存回复的决策")

            async def completed(messages, config):
                self.assertEqual(messages[-1]["content"], "已保存的总体方案回复")
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=unexpected_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")

    def test_blocked_decision_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            self.write_design(workspace)

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            with self.assertRaises(SolutionDesignBlocked) as raised:
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=lambda messages, config: _async_value(
                        decision("blocked", reason="缺少不可替代授权", required_inputs=["外部授权"])
                    ),
                    config_loader=lambda: object(),
                )
            self.assertEqual(raised.exception.required_inputs, ["外部授权"])

    def test_no_applicable_engine_still_requires_solution_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), applicable=False)
            calls = 0

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                nonlocal calls
                calls += 1
                self.write_design(kwargs["cwd"])  # type: ignore[arg-type]
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=lambda messages, config: _async_value(decision("completed")),
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(calls, 1)
            self.assertEqual(outcome["outputs"], [DESIGN_PATH.as_posix()])

    def test_structured_decision_retries_invalid_json_once(self) -> None:
        prompts: list[str] = []

        async def fake_request(messages, config, *, system_prompt, output_model):
            prompts.append(system_prompt)
            if len(prompts) == 1:
                SolutionDesignDecision.model_validate_json("verdict: continue")
            return decision("continue", answer="继续完成方案", reason="仍需核对")

        with patch(
            "steps.step_07_solution_design.step.request_decision",
            new=fake_request,
        ):
            recovered = asyncio.run(
                request_solution_design_decision(
                    [{"role": "user", "content": "方案待核对"}],
                    object(),  # type: ignore[arg-type]
                )
            )
        self.assertEqual(recovered[0]["verdict"], "continue")
        self.assertEqual(len(prompts), 2)
        self.assertIn("上一次响应不是有效 JSON", prompts[1])


def _async_value(value):
    async def result():
        return value

    return result()


if __name__ == "__main__":
    unittest.main()
