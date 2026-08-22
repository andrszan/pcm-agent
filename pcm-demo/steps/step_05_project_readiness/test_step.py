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
from config import load_dev_resource_list
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_03_foundation_selection.step import TemplateSelection
from steps.step_05_project_readiness.step import (
    CHECKLIST,
    COMPLETION_MESSAGE,
    CURRENT_NODE,
    MAX_DECISION_ROUNDS,
    NEXT_NODE,
    ProjectReadinessBlocked,
    checklist_present,
    run,
)


def agent_result(
    *,
    cwd: Path,
    session: str = "session-1",
    text: str = "清单已处理",
    subtype: str = "success",
    is_error: bool = False,
    exception: str | None = None,
) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": ["project-readiness"],
            "slash_commands": ["project-readiness"],
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


class ProjectReadinessTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        (workspace / "docs/requirements").mkdir(parents=True)
        (workspace / "frontend").mkdir(parents=True)
        (workspace / "frontend/app.py").write_text("pass\n", encoding="utf-8")
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
        return run_dir, workspace, state

    def run_step(self, run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(
            run(
                run_dir,
                state,
                resource_loader=lambda: (Path("/resource-list"), "test"),
                **kwargs,
            )
        )

    def test_resource_list_path_must_be_absolute_readable_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "resources.md"
            resource.write_text("safe", encoding="utf-8")
            env_file = root / ".env"
            env_file.write_text(f"PCM_DEV_RESOURCE_LIST={resource}\n", encoding="utf-8")
            self.assertEqual(load_dev_resource_list(env_file), (resource.resolve(), "env_file"))
            env_file.write_text("PCM_DEV_RESOURCE_LIST=relative.md\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "绝对路径"):
                load_dev_resource_list(env_file)
            link = root / "resource-link.md"
            link.symlink_to(resource)
            env_file.write_text(f"PCM_DEV_RESOURCE_LIST={link}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "符号链接"):
                load_dev_resource_list(env_file)

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

    def test_approve_with_checklist_succeeds_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text="SENSITIVE_VALUE",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def unexpected_decision(messages, config):
                raise AssertionError("完成条件满足时不应调用决策模型")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=unexpected_decision,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["outputs"], [CHECKLIST.as_posix()])
            self.assertIn("/project-readiness", calls[0]["prompt"])
            self.assertIn("docs/requirements/项目需求说明.md", calls[0]["prompt"])
            self.assertIn('"frontend"', calls[0]["prompt"])
            self.assertIn("@/resource-list", calls[0]["prompt"])
            saved = read_state(run_dir)
            self.assertEqual((saved["current_step"], saved["current_node"]), (6, NEXT_NODE))
            self.assertEqual(json.loads((run_dir / "steps/05.json").read_text())["status"], "success")
            history = json.loads(
                (run_dir / "conversations/project_readiness.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(
                [item["role"] for item in history],
                ["system", "assistant", "user", "assistant"],
            )
            self.assertEqual(history[2]["content"], "SENSITIVE_VALUE")
            self.assertEqual(history[3]["content"], COMPLETION_MESSAGE)

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("成功复用不应调用 Agent")

            reused = self.run_step(run_dir, saved, agent_runner=unexpected_agent)
            self.assertEqual(reused["status"], "success")
            self.assertIn("确认既有成功", reused["summary"])

            interrupted = read_state(run_dir)
            interrupted.setdefault("project_readiness", {})[
                "pending_agent_text"
            ] = "临时完整回复"
            interrupted.update(
                {
                    "status": "running",
                    "step": 5,
                    "current_step": 5,
                    "current_node": CURRENT_NODE,
                }
            )
            write_state(run_dir, interrupted)
            recovered = self.run_step(run_dir, interrupted, agent_runner=unexpected_agent)
            self.assertEqual(recovered["status"], "success")
            recovered_state = read_state(run_dir)
            self.assertEqual(recovered_state["current_node"], NEXT_NODE)
            self.assertNotIn(
                "pending_agent_text",
                recovered_state["project_readiness"],
            )

    def test_success_history_without_step_result_recovers_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            agent_text = "Agent 最终完整回复"
            (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
            state.update(
                {
                    "claude_sessions": {"project_readiness": "session-1"},
                    "project_readiness": {
                        "last_agent_result": {
                            "subtype": "success",
                            "is_error": False,
                        },
                        "pending_agent_text": agent_text,
                    },
                    "decision_conversations": {
                        "project_readiness": {
                            "path": "conversations/project_readiness.json",
                            "turn": 0,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_readiness.json",
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": "initial"},
                        {"role": "user", "content": agent_text},
                        {"role": "assistant", "content": COMPLETION_MESSAGE},
                    ]
                },
            )

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("成功历史恢复不应再次调用 Agent")

            outcome = self.run_step(run_dir, state, agent_runner=unexpected_agent)
            self.assertEqual(outcome["status"], "success")
            history = json.loads(
                (run_dir / "conversations/project_readiness.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(len(history), 4)
            self.assertEqual(
                sum(
                    item["content"] == COMPLETION_MESSAGE
                    for item in history
                ),
                1,
            )
            self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_saved_decision_recovers_exact_answer_before_agent_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            decision = {
                "action": "continue",
                "answer": "原样恢复的决策指令",
                "reason": "继续完成",
                "required_inputs": [],
            }
            state.update(
                {
                    "claude_sessions": {"project_readiness": "session-1"},
                    "decision_conversations": {
                        "project_readiness": {
                            "path": "conversations/project_readiness.json",
                            "turn": 1,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_readiness.json",
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": "initial"},
                        {"role": "user", "content": "Agent 第一轮完整回复"},
                        {
                            "role": "assistant",
                            "content": json.dumps(decision, ensure_ascii=False),
                        },
                    ]
                },
            )

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                self.assertEqual(prompt, decision["answer"])
                (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text="Agent 第二轮完整回复",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            outcome = self.run_step(run_dir, state, agent_runner=fake_agent)
            self.assertEqual(outcome["status"], "success")
            history = json.loads(
                (run_dir / "conversations/project_readiness.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(history[-2]["content"], "Agent 第二轮完整回复")
            self.assertEqual(history[-1]["content"], COMPLETION_MESSAGE)

    def test_saved_agent_reply_recovers_decision_before_agent_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            state.update(
                {
                    "claude_sessions": {"project_readiness": "session-1"},
                    "decision_conversations": {
                        "project_readiness": {
                            "path": "conversations/project_readiness.json",
                            "turn": 0,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_readiness.json",
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": "initial"},
                        {"role": "user", "content": "Agent 已保存的完整回复"},
                    ]
                },
            )
            decision = {
                "action": "continue",
                "answer": "决策恢复后发送的完整指令",
                "reason": "继续",
                "required_inputs": [],
            }

            async def fake_decision(messages, config):
                self.assertEqual(messages[-1]["content"], "Agent 已保存的完整回复")
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                self.assertEqual(prompt, decision["answer"])
                (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text="Agent 恢复后的完整回复",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=fake_decision,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")
            history = json.loads(
                (run_dir / "conversations/project_readiness.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(
                json.loads(history[3]["content"]),
                decision,
            )
            self.assertEqual(history[-2]["content"], "Agent 恢复后的完整回复")
            self.assertEqual(history[-1]["content"], COMPLETION_MESSAGE)

    def test_missing_checklist_approve_resumes_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    self.assertEqual(
                        read_state(run_dir)["project_readiness"]["pending_agent_prompt"],
                        "请继续创建清单",
                    )
                    (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text=f"Agent 完整回复 {len(calls)}",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def fake_decision(messages, config):
                decision = {"action": "approve", "answer": "请继续创建清单", "reason": "尚未落盘", "required_inputs": []}
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            outcome = self.run_step(run_dir, state, agent_runner=fake_agent, decision_runner=fake_decision, config_loader=lambda: object())
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertEqual(calls[1]["prompt"], "请继续创建清单")
            self.assertNotIn("pending_agent_prompt", read_state(run_dir)["project_readiness"])
            history = json.loads(
                (run_dir / "conversations/project_readiness.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(
                [item["role"] for item in history],
                ["system", "assistant", "user", "assistant", "user", "assistant"],
            )
            self.assertEqual(history[2]["content"], "Agent 完整回复 1")
            self.assertEqual(
                json.loads(history[3]["content"]),
                {
                    "action": "approve",
                    "answer": "请继续创建清单",
                    "reason": "尚未落盘",
                    "required_inputs": [],
                },
            )
            self.assertEqual(history[4]["content"], "Agent 完整回复 2")
            self.assertEqual(history[5]["content"], COMPLETION_MESSAGE)

    def test_budget_limit_with_checklist_still_resumes_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
                if len(calls) == 1:
                    current = agent_result(
                        cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                        text="达到预算上限前尚未完成",
                        subtype="error_max_budget_usd",
                        is_error=True,
                        exception="Exception: Reached maximum budget",
                    )
                else:
                    current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def fake_decision(messages, config):
                decision = {
                    "action": "approve",
                    "answer": "继续完成核验",
                    "reason": "清单存在但 Agent 尚未正常结束",
                    "required_inputs": [],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=fake_decision,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertEqual(calls[0]["max_turns"], 24)
            self.assertEqual(calls[0]["max_budget_usd"], 8.0)

    def test_turn_limit_resumes_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls = 0

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                nonlocal calls
                calls += 1
                if calls == 1:
                    current = agent_result(
                        cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                        subtype="error_max_turns",
                        is_error=True,
                        exception="Exception: Reached maximum turns",
                    )
                else:
                    (workspace / CHECKLIST).write_text("# 准备\n", encoding="utf-8")
                    current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def fake_decision(messages, config):
                decision = {
                    "action": "continue" if calls == 1 else "approve",
                    "answer": "继续完成核验",
                    "reason": "恢复原 session",
                    "required_inputs": [],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=fake_decision,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(calls, 2)

    def test_saved_blocked_decision_recovers_without_agent_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            decision = {
                "action": "blocked",
                "answer": "等待外部资源",
                "reason": "缺少真实外部账号",
                "required_inputs": ["外部账号"],
            }
            state.update(
                {
                    "claude_sessions": {"project_readiness": "session-1"},
                    "decision_conversations": {
                        "project_readiness": {
                            "path": "conversations/project_readiness.json",
                            "turn": 1,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_readiness.json",
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": "initial"},
                        {"role": "user", "content": "Agent 完整阻塞回复"},
                        {
                            "role": "assistant",
                            "content": json.dumps(decision, ensure_ascii=False),
                        },
                    ]
                },
            )

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("已保存 blocked 决策不应再次调用 Agent")

            with self.assertRaises(ProjectReadinessBlocked) as raised:
                self.run_step(run_dir, state, agent_runner=unexpected_agent)
            self.assertEqual(str(raised.exception), decision["reason"])
            self.assertEqual(raised.exception.required_inputs, decision["required_inputs"])

    def test_persisted_decision_round_limit_applies_across_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            state.update(
                {
                    "claude_sessions": {"project_readiness": "session-1"},
                    "decision_conversations": {
                        "project_readiness": {
                            "path": "conversations/project_readiness.json",
                            "turn": MAX_DECISION_ROUNDS - 1,
                        }
                    },
                }
            )
            write_state(run_dir, state)
            (run_dir / "conversations").mkdir()
            messages = [
                {"role": "system", "content": "system"},
                {"role": "assistant", "content": "initial"},
            ]
            for index in range(MAX_DECISION_ROUNDS):
                messages.append(
                    {"role": "user", "content": f"Agent 第 {index + 1} 轮完整回复"}
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "action": "continue",
                                "answer": f"继续第 {index + 1} 轮",
                                "reason": "尚未完成",
                                "required_inputs": [],
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
            messages.append(
                {"role": "user", "content": "等待第七次决策的 Agent 回复"}
            )
            write_json(
                run_dir / "conversations/project_readiness.json",
                {"messages": messages},
            )

            async def unexpected_decision(messages, config):
                raise AssertionError("达到累计上限后不应调用决策模型")

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("达到累计上限后不应调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "决策循环达到上限"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=unexpected_agent,
                    decision_runner=unexpected_decision,
                    config_loader=lambda: object(),
                )
            self.assertEqual(
                read_state(run_dir)["decision_conversations"]["project_readiness"]["turn"],
                MAX_DECISION_ROUNDS,
            )

    def test_blocked_skill_session_and_input_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))

            async def blocked_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text="Agent 完整阻塞回复",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked_decision(messages, config):
                decision = {
                    "action": "blocked",
                    "answer": "SENSITIVE_ANSWER",
                    "reason": "SENSITIVE_REASON",
                    "required_inputs": ["SENSITIVE_INPUT"],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with self.assertRaises(ProjectReadinessBlocked) as raised:
                self.run_step(run_dir, state, agent_runner=blocked_agent, decision_runner=blocked_decision, config_loader=lambda: object())
            self.assertEqual(str(raised.exception), "SENSITIVE_REASON")
            self.assertEqual(raised.exception.required_inputs, ["SENSITIVE_INPUT"])
            self.assertNotIn(
                "pending_agent_text",
                read_state(run_dir)["project_readiness"],
            )
            history = json.loads(
                (run_dir / "conversations/project_readiness.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(history[-2]["content"], "Agent 完整阻塞回复")
            self.assertEqual(
                json.loads(history[-1]["content"]),
                {
                    "action": "blocked",
                    "answer": "SENSITIVE_ANSWER",
                    "reason": "SENSITIVE_REASON",
                    "required_inputs": ["SENSITIVE_INPUT"],
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))

            async def missing_skill(prompt: str, **kwargs: object) -> ClaudeRunResult:
                return ClaudeRunResult(
                    {
                        "cwd": str(kwargs["cwd"]),
                        "skills": [],
                        "slash_commands": [],
                    },
                    "",
                    "success",
                    False,
                    "session-1",
                    "end_turn",
                    1,
                    0.1,
                    None,
                )

            with self.assertRaisesRegex(RuntimeError, "未加载 project-readiness Skill"):
                self.run_step(run_dir, state, agent_runner=missing_skill)
            self.assertNotIn(
                "pending_agent_text",
                read_state(run_dir)["project_readiness"],
            )

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            state["claude_sessions"] = {"project_readiness": "old"}
            write_state(run_dir, state)

            async def changed_session(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    session="new",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            with self.assertRaisesRegex(RuntimeError, "session ID 不一致"):
                self.run_step(run_dir, state, agent_runner=changed_session)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "frontend/app.py").unlink()
            (workspace / "frontend").rmdir()
            with self.assertRaisesRegex(RuntimeError, "基础工程"):
                self.run_step(run_dir, state)

    def test_sdk_exception_text_is_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))

            async def failing_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    subtype="error_during_execution",
                    is_error=True,
                    exception="SENSITIVE_EXCEPTION",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            with self.assertRaisesRegex(RuntimeError, "Agent SDK 执行异常"):
                self.run_step(run_dir, state, agent_runner=failing_agent)
            self.assertNotIn(
                "SENSITIVE_EXCEPTION",
                (run_dir / "state.json").read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "pending_agent_text",
                read_state(run_dir)["project_readiness"],
            )
            history = json.loads(
                (run_dir / "conversations/project_readiness.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(
                [item["role"] for item in history],
                ["system", "assistant"],
            )

    def test_decision_exception_text_is_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))

            async def finished_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def failing_decision(messages, config):
                raise RuntimeError("SENSITIVE_DECISION_EXCEPTION")

            with self.assertRaisesRegex(RuntimeError, "AI-compatible 决策失败"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=finished_agent,
                    decision_runner=failing_decision,
                    config_loader=lambda: object(),
                )
            persisted = (run_dir / "state.json").read_text(encoding="utf-8") + (
                run_dir / "conversations/project_readiness.json"
            ).read_text(encoding="utf-8")
            self.assertNotIn("SENSITIVE_DECISION_EXCEPTION", persisted)
            self.assertNotIn(
                "pending_agent_text",
                read_state(run_dir)["project_readiness"],
            )

    def test_product_outputs_reject_parent_segments_and_symlinked_parents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            step_two = json.loads((run_dir / "steps/02.json").read_text(encoding="utf-8"))
            step_two["outputs"][0] = "docs/requirements/../requirements/项目需求说明.md"
            write_json(run_dir / "steps/02.json", step_two)
            with self.assertRaisesRegex(RuntimeError, r"不能包含 \.\."):
                self.run_step(run_dir, state)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            source = workspace / "docs/requirements"
            outside = Path(directory) / "outside-requirements"
            source.rename(outside)
            source.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "不能包含符号链接"):
                self.run_step(run_dir, state)

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

    def test_cli_handles_corrupt_state_without_traceback(self) -> None:
        run_dir = DEMO_ROOT / "runs" / "corrupt-step-five-test"
        if run_dir.exists():
            self.skipTest("本地测试 run 已存在")
        try:
            (run_dir / "steps").mkdir(parents=True)
            (run_dir / "state.json").write_text("{invalid", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(DEMO_ROOT / "run_step.py"),
                    "--step",
                    "5",
                    "--run-id",
                    run_dir.name,
                ],
                cwd=DEMO_ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertNotIn("Traceback", completed.stderr)
            saved = json.loads((run_dir / "steps/05.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "failed")
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)


if __name__ == "__main__":
    unittest.main()
