from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
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
from steps.step_06_project_bootstrap.step import (
    BootstrapDecision,
    COMPLETION_MESSAGE,
    CURRENT_NODE,
    NEXT_NODE,
    PROJECT_BOOTSTRAP_MAX_BUDGET_USD,
    PROJECT_BOOTSTRAP_MAX_TURNS,
    ProjectBootstrapBlocked,
    request_bootstrap_decision,
    run,
)


def agent_result(
    *,
    cwd: Path,
    session: str = "session-1",
    text: str = "项目化完整回复",
    subtype: str = "success",
    is_error: bool = False,
    exception: str | None = None,
    skills: list[str] | None = None,
) -> ClaudeRunResult:
    loaded = ["project-bootstrap"] if skills is None else skills
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": loaded,
            "slash_commands": loaded,
        },
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
            {
                "step": 5,
                "status": "success",
                "outputs": [checklist],
            },
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

    def test_completed_decision_succeeds_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config):
                self.assertEqual(messages[-1]["content"], "项目化完整回复")
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["outputs"], ["frontend"])
            self.assertIn("/project-bootstrap", calls[0]["prompt"])
            self.assertIn("docs/requirements/项目需求说明.md", calls[0]["prompt"])
            self.assertIn("@./frontend", calls[0]["prompt"])
            self.assertIn("产品根 README", calls[0]["prompt"])
            self.assertNotIn("git_url", calls[0]["prompt"])
            self.assertNotIn("origin", calls[0]["prompt"])
            self.assertNotIn("第 6 步", calls[0]["prompt"])
            self.assertNotIn("PCM", calls[0]["prompt"])
            self.assertEqual(calls[0]["max_turns"], PROJECT_BOOTSTRAP_MAX_TURNS)
            self.assertEqual(calls[0]["max_budget_usd"], PROJECT_BOOTSTRAP_MAX_BUDGET_USD)

            saved = read_state(run_dir)
            self.assertEqual((saved["step"], saved["current_node"]), (7, NEXT_NODE))
            history = json.loads(
                (run_dir / "conversations/project_bootstrap.json").read_text(
                    encoding="utf-8"
                )
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

    def test_continue_resumes_same_session_then_completes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text=f"完整回复 {len(calls)}",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            decisions = iter(
                [
                    decision("continue", answer="继续执行真实验证", reason="尚未完成"),
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
            self.assertEqual(calls[1]["prompt"], "继续执行真实验证")

    def test_budget_limit_uses_decision_and_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            calls = 0

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                nonlocal calls
                calls += 1
                if calls == 1:
                    current = agent_result(
                        cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                        text="预算结束前尚未完成",
                        subtype="error_max_budget_usd",
                        is_error=True,
                        exception="budget",
                    )
                else:
                    current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            decisions = iter(
                [
                    decision("continue", answer="恢复后继续", reason="预算中断"),
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
            self.assertEqual(calls, 2)

    def test_saved_agent_reply_runs_decision_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            state.update(
                {
                    "claude_sessions": {"project_bootstrap": "session-1"},
                    "project_bootstrap": {
                        "last_agent_result": {"subtype": "success", "is_error": False},
                        "pending_agent_text": "已保存的 Agent 完整回复",
                    },
                    "decision_conversations": {
                        "project_bootstrap": {
                            "path": "conversations/project_bootstrap.json",
                            "turn": 0,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_bootstrap.json",
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": "initial"},
                    ]
                },
            )

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("应先恢复已保存回复的决策")

            async def completed(messages, config):
                self.assertEqual(messages[-1]["content"], "已保存的 Agent 完整回复")
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=unexpected_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")
            self.assertTrue(workspace.is_dir())

    def test_saved_continue_decision_restores_exact_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            saved_decision, _, raw = decision(
                "continue", answer="原样恢复的项目化指令", reason="尚未完成"
            )
            state.update(
                {
                    "claude_sessions": {"project_bootstrap": "session-1"},
                    "decision_conversations": {
                        "project_bootstrap": {
                            "path": "conversations/project_bootstrap.json",
                            "turn": 1,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_bootstrap.json",
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": "initial"},
                        {"role": "user", "content": "第一轮完整回复"},
                        {"role": "assistant", "content": raw},
                    ]
                },
            )

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                self.assertEqual(prompt, saved_decision["answer"])
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config):
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")

    def test_saved_blocked_decision_does_not_call_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            _, _, raw = decision(
                "blocked",
                reason="缺少真实外部授权",
                required_inputs=["外部授权"],
            )
            state.update(
                {
                    "claude_sessions": {"project_bootstrap": "session-1"},
                    "decision_conversations": {
                        "project_bootstrap": {
                            "path": "conversations/project_bootstrap.json",
                            "turn": 1,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_bootstrap.json",
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": "initial"},
                        {"role": "user", "content": "阻塞回复"},
                        {"role": "assistant", "content": raw},
                    ]
                },
            )

            async def unexpected(*args, **kwargs):
                raise AssertionError("已保存 blocked 不应再次调用")

            with self.assertRaises(ProjectBootstrapBlocked) as raised:
                self.run_step(run_dir, state, agent_runner=unexpected)
            self.assertEqual(raised.exception.required_inputs, ["外部授权"])

    def test_completed_decision_recovers_state_advance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            _, _, raw = decision("completed")
            state.update(
                {
                    "claude_sessions": {"project_bootstrap": "session-1"},
                    "project_bootstrap": {
                        "last_agent_result": {"subtype": "success", "is_error": False}
                    },
                    "decision_conversations": {
                        "project_bootstrap": {
                            "path": "conversations/project_bootstrap.json",
                            "turn": 1,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_bootstrap.json",
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": "initial"},
                        {"role": "user", "content": "最终完整回复"},
                        {"role": "assistant", "content": raw},
                    ]
                },
            )

            async def unexpected(*args, **kwargs):
                raise AssertionError("已完成决定不应再次调用")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_staged_changes_and_nested_git_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def staging_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / "README.md").write_text("project\n", encoding="utf-8")
                subprocess.run(
                    ["git", "add", "README.md"], cwd=workspace, check=True, capture_output=True
                )
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config):
                return decision("completed")

            with self.assertRaisesRegex(RuntimeError, "不得暂存"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=staging_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def git_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / "frontend/.git").mkdir()
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config):
                return decision("completed")

            with self.assertRaisesRegex(RuntimeError, r"嵌套 \.git"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=git_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )

    def test_skill_session_and_decision_schema_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))

            async def missing_skill(prompt: str, **kwargs: object) -> ClaudeRunResult:
                return agent_result(cwd=kwargs["cwd"], skills=[])  # type: ignore[arg-type, index]

            with self.assertRaisesRegex(RuntimeError, "未加载 project-bootstrap Skill"):
                self.run_step(run_dir, state, agent_runner=missing_skill)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            state["claude_sessions"] = {"project_bootstrap": "old-session"}
            write_state(run_dir, state)

            async def changed_session(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(
                    cwd=kwargs["cwd"], session="new-session"  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            with self.assertRaisesRegex(RuntimeError, "session ID 不一致"):
                self.run_step(run_dir, state, agent_runner=changed_session)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def invalid_decision(messages, config):
                data = {
                    "verdict": "continue",
                    "answer": "",
                    "reason": "invalid",
                    "required_inputs": [],
                }
                return data, 1, json.dumps(data)

            with self.assertRaisesRegex(RuntimeError, "缺少有效提示"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=invalid_decision,
                    config_loader=lambda: object(),
                )

    def test_structured_decision_retries_invalid_json_once(self) -> None:
        prompts: list[str] = []

        async def fake_request(messages, config, *, system_prompt, output_model):
            prompts.append(system_prompt)
            if len(prompts) == 1:
                BootstrapDecision.model_validate_json("verdict: continue")
            return decision("continue", answer="确认执行", reason="计划待确认")

        with patch(
            "steps.step_06_project_bootstrap.step.request_decision",
            new=fake_request,
        ):
            recovered = asyncio.run(
                request_bootstrap_decision(
                    [{"role": "user", "content": "项目化计划待确认"}],
                    object(),  # type: ignore[arg-type]
                )
            )
        self.assertEqual(recovered[0]["verdict"], "continue")
        self.assertEqual(len(prompts), 2)
        self.assertIn("上一次响应不是有效 JSON", prompts[1])

    def test_decision_limit_blocks_saved_continue_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            messages = [
                {"role": "system", "content": "system"},
                {"role": "assistant", "content": "initial"},
            ]
            for index in range(8):
                _, _, raw = decision(
                    "continue", answer=f"继续 {index + 1}", reason="尚未完成"
                )
                messages.extend(
                    [
                        {"role": "user", "content": f"Agent 回复 {index + 1}"},
                        {"role": "assistant", "content": raw},
                    ]
                )
            state.update(
                {
                    "claude_sessions": {"project_bootstrap": "session-1"},
                    "project_bootstrap": {"pending_agent_prompt": "不应执行的第九轮"},
                    "decision_conversations": {
                        "project_bootstrap": {
                            "path": "conversations/project_bootstrap.json",
                            "turn": 8,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_bootstrap.json", {"messages": messages}
            )

            async def unexpected(*args, **kwargs):
                raise AssertionError("达到累计上限后不应调用 Agent 或决策模型")

            with self.assertRaisesRegex(RuntimeError, "决策循环达到上限"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=unexpected,
                    decision_runner=unexpected,
                )

    def test_no_applicable_foundation_skips_without_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory), applicable=False)

            async def unexpected(*args, **kwargs):
                raise AssertionError("无适用工程不应调用 Agent")

            outcome = self.run_step(run_dir, state, agent_runner=unexpected)
            self.assertEqual(outcome["status"], "success")
            self.assertFalse(outcome["applicable"])
            self.assertEqual(outcome["outputs"], [])

    def test_no_applicable_foundation_still_rejects_staged_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), applicable=False)
            (workspace / "README.md").write_text("staged\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "README.md"], cwd=workspace, check=True, capture_output=True
            )
            with self.assertRaisesRegex(RuntimeError, "不得暂存"):
                self.run_step(run_dir, state)

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
