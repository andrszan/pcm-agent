from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.agent_decision_loop import BLOCKED_RESUME_PROMPT, ResumeMessage, prepare_resume_message
from common.claude_agent import ClaudeRunResult
from common.files import write_json
from common.state import read_state, write_requirement_step_result, write_state
from model_policy import get_agent_profile
from steps.step_15_development.step import (
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    STEP,
    DevelopmentBlocked,
    result,
    run,
)
import steps.step_15_development.step as development_step


def agent_result(
    workspace: Path,
    *,
    session: str = "development-session-1",
    text: str = "已完成实现、适用测试、真实验证和审查，没有剩余工作、验证缺口或阻断项。",
) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(workspace),
            "skills": ["dev-workflow"],
            "slash_commands": ["dev-workflow"],
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
    value = {
        "verdict": verdict,
        "answer": answer,
        "reason": reason,
        "required_inputs": required_inputs or [],
    }
    return value, 1, json.dumps(value, ensure_ascii=False)


class DevelopmentTests(unittest.TestCase):
    def setUp(self) -> None:
        classifier = patch.object(
            development_step, "classify_frontend_scope",
            AsyncMock(return_value={"applicable": False, "reason": "当前需求只涉及后端"}),
        )
        self.classifier = classifier.start()
        self.addCleanup(classifier.stop)

    def make_run(self, root: Path) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        trd_path = "docs/trd/BR-001.md"
        (workspace / "docs/trd").mkdir(parents=True)
        (workspace / trd_path).write_text(
            "# 活动 TRD\n\nTRD_CONTEXT_MARKER：必须验证账户锁定恢复。\n",
            encoding="utf-8",
        )
        (root / "可信开发资源清单.md").write_text(
            "RESOURCE_SECRET_MARKER=不得内联\n", encoding="utf-8"
        )
        (run_dir / "steps").mkdir(parents=True)
        state = {
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "requirement_registry": {
                "schema_version": 1,
                "requirements": [
                    {
                        "id": "BR-001",
                        "title": "账户访问",
                        "order": 1,
                        "depends_on": [],
                        "status": "active",
                        "completion": None,
                    }
                ],
            },
            "active_requirement": "BR-001",
            "requirement_cycle": {
                "requirement_id": "BR-001",
                "branch": "req/br-001",
                "trd_path": trd_path,
            },
            "blocked": None,
            "error": None,
        }
        write_requirement_step_result(
            run_dir,
            "BR-001",
            14,
            {
                "step": 14,
                "name": "形成活动 TRD",
                "status": "success",
                "summary": "已完成。",
                "applicable": True,
                "outputs": [trd_path],
                "blocked": None,
                "error": None,
                "requirement_id": "BR-001",
                "branch": "req/br-001",
                "trd_path": trd_path,
                "trd_session_id": "trd-session-1",
            },
        )
        write_state(run_dir, state)
        return run_dir, workspace, state

    @staticmethod
    def run_step(run_dir: Path, state: dict, **kwargs: object) -> dict:
        resource_list = run_dir.parent / "可信开发资源清单.md"
        kwargs.setdefault("resource_loader", lambda: (resource_list, "test"))
        return asyncio.run(run(run_dir, state, **kwargs))

    def test_prompt_completed_result_and_session_are_requirement_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []
            decision_prompts: list[str] = []

            async def agent(prompt: str, **_: object) -> ClaudeRunResult:
                prompts.append(prompt)
                return agent_result(workspace)

            async def decide(*_: object, **kwargs: object) -> tuple[dict, int, str]:
                decision_prompts.append(str(kwargs["system_prompt"]))
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )

            self.assertEqual(len(prompts), 1)
            self.assertTrue(prompts[0].startswith("/dev-workflow\n"))
            self.assertIn("BR-001 账户访问", prompts[0])
            self.assertIn("docs/trd/BR-001.md", prompts[0])
            self.assertIn("docs/requirements/项目准备清单.md", prompts[0])
            self.assertIn(str(run_dir.parent / "可信开发资源清单.md"), prompts[0])
            self.assertNotIn("RESOURCE_SECRET_MARKER", prompts[0])
            self.assertEqual(len(decision_prompts), 1)
            self.assertIn("docs/trd/BR-001.md", decision_prompts[0])
            self.assertIn("docs/requirements/项目准备清单.md", decision_prompts[0])
            self.assertIn(str(run_dir.parent / "可信开发资源清单.md"), decision_prompts[0])
            self.assertNotIn("RESOURCE_SECRET_MARKER", decision_prompts[0])
            self.assertIn("TRD_CONTEXT_MARKER：必须验证账户锁定恢复。", decision_prompts[0])
            self.assertIn(development_step.DEVELOPMENT_DECISION_RULES, decision_prompts[0])
            self.assertNotIn("TRD_CONTEXT_MARKER", prompts[0])
            self.assertEqual(saved["outputs"], [])
            self.assertEqual(saved["development_session_id"], "development-session-1")
            self.assertEqual(saved["frontend"], {"applicable": False, "reason": "当前需求只涉及后端", "session_id": None})
            self.classifier.assert_awaited_once()
            self.assertNotIn("frontend_ui_ux_BR-001", state["claude_sessions"])
            self.assertEqual(
                set(saved),
                {
                    "step",
                    "name",
                    "status",
                    "summary",
                    "applicable",
                    "outputs",
                    "blocked",
                    "error",
                    "requirement_id",
                    "trd_path",
                    "development_session_id",
                    "frontend",
                },
            )
            completed = read_state(run_dir)
            self.assertEqual(completed["claude_sessions"]["development_BR-001"], "development-session-1")
            self.assertEqual(
                completed["requirement_cycle"]["development_session_id"], "development-session-1"
            )
            self.assertEqual(
                (completed["step"], completed["current_step"], completed["current_node"]),
                (16, 16, NEXT_NODE),
            )

    def test_unavailable_resource_list_is_handed_off_without_preempting_agent(self) -> None:
        for error in (ValueError("缺少配置"), OSError("不可读取")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                prompts: list[str] = []
                decision_prompts: list[str] = []

                def unavailable_loader() -> tuple[Path, str]:
                    raise error

                async def agent(prompt: str, **_: object) -> ClaudeRunResult:
                    prompts.append(prompt)
                    return agent_result(workspace)

                async def decide(*_: object, **kwargs: object) -> tuple[dict, int, str]:
                    decision_prompts.append(str(kwargs["system_prompt"]))
                    return decision("completed")

                saved = self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                    resource_loader=unavailable_loader,
                )

                self.assertEqual(saved["status"], "success")
                self.assertEqual(len(prompts), 1)
                self.assertIn("当前配置不可用", prompts[0])
                self.assertIn('"available": false', decision_prompts[0])
                self.assertNotIn(str(error), prompts[0])
                self.assertNotIn(str(error), decision_prompts[0])

    def test_blocked_saves_session_and_keeps_current_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("blocked", reason="缺少外部授权", required_inputs=["外部授权"])

            with self.assertRaises(DevelopmentBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            saved = json.loads(
                (run_dir / "steps/requirements/BR-001/15.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["status"], "blocked")
            self.assertEqual(saved["development_session_id"], "development-session-1")
            blocked = read_state(run_dir)
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(
                (blocked["step"], blocked["current_step"], blocked["current_node"]),
                (STEP, STEP, CURRENT_NODE),
            )
            self.assertEqual(
                blocked["requirement_cycle"]["development_session_id"], "development-session-1"
            )

    def test_continue_reuses_development_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[tuple[object, object, object, object]] = []
            resource_loads = 0
            decisions = iter(
                [
                    decision("continue", answer="请继续完成遗漏。"),
                    decision("completed"),
                ]
            )

            async def agent(_prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append(
                    (
                        kwargs.get("resume_session_id"),
                        kwargs.get("task"),
                        kwargs.get("model"),
                        kwargs.get("effort"),
                    )
                )
                value = agent_result(workspace)
                value.text = f"第 {len(calls)} 轮完成情况。"
                return value

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return next(decisions)

            def load_resources() -> tuple[Path, str]:
                nonlocal resource_loads
                resource_loads += 1
                return run_dir.parent / "可信开发资源清单.md", "test"

            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                resource_loader=load_resources,
            )
            profile = get_agent_profile("development")
            self.assertEqual(resource_loads, 1)
            self.assertEqual(
                calls,
                [
                    (None, "development", profile.model, profile.effort),
                    (
                        "development-session-1",
                        "development",
                        profile.model,
                        profile.effort,
                    ),
                ],
            )

    def test_eight_continue_decisions_still_allow_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls = 0
            decisions = iter(
                [decision("continue", answer=f"继续完成第 {index} 轮。") for index in range(8)]
                + [decision("completed")]
            )

            async def agent(_prompt: str, **_kwargs: object) -> ClaudeRunResult:
                nonlocal calls
                calls += 1
                value = agent_result(workspace)
                value.text = f"第 {calls} 轮完成情况。"
                return value

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return next(decisions)

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )

            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls, 9)

    def test_saved_success_recovers_advance_and_advanced_rerun_skips_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            original_write_state = development_step.write_state

            def interrupt_advance(path: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("simulated state interruption")
                original_write_state(path, value)

            with patch.object(development_step, "write_state", side_effect=interrupt_advance):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=decide,
                        config_loader=lambda: object(),
                    )
            interrupted = read_state(run_dir)
            self.assertEqual(
                json.loads(
                    (run_dir / "steps/requirements/BR-001/15.json").read_text(encoding="utf-8")
                )["status"],
                "success",
            )

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("不应再次调用 Agent")

            def forbidden_resource_loader() -> tuple[Path, str]:
                raise AssertionError("成功恢复和幂等重跑不应加载可信开发资源清单")

            recovered = self.run_step(
                run_dir,
                interrupted,
                agent_runner=forbidden,
                resource_loader=forbidden_resource_loader,
            )
            self.assertEqual(recovered["status"], "success")
            advanced = read_state(run_dir)
            self.assertEqual(
                self.run_step(
                    run_dir,
                    advanced,
                    agent_runner=forbidden,
                    resource_loader=forbidden_resource_loader,
                ),
                recovered,
            )

    def test_inconsistent_or_unusable_trd_fails_before_agent(self) -> None:
        for case in ("result-mismatch", "missing", "empty"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                trd = workspace / "docs/trd/BR-001.md"
                if case == "result-mismatch":
                    path = run_dir / "steps/requirements/BR-001/14.json"
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    saved["trd_path"] = "docs/trd/other.md"
                    write_json(path, saved)
                elif case == "missing":
                    trd.unlink()
                else:
                    trd.write_text("\n", encoding="utf-8")

                async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                    raise AssertionError("TRD 预检失败时不得调用 Agent")

                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state, agent_runner=forbidden)



def frontend_agent_result(workspace: Path, **kwargs: object) -> ClaudeRunResult:
    value = agent_result(workspace, **kwargs)
    value.init["skills"].append("frontend-ui-ux")
    value.init["slash_commands"].append("frontend-ui-ux")
    return value


class FrontendDevelopmentTests(unittest.TestCase):
    make_run = DevelopmentTests.make_run
    run_step = staticmethod(DevelopmentTests.run_step)

    def setUp(self) -> None:
        self.classify = AsyncMock(return_value={"applicable": True, "reason": "有用户交互"})
        self.classify_patch = patch.object(development_step, "classify_frontend_scope", self.classify)
        self.capability_patch = patch.object(development_step, "ensure_frontend_capabilities")
        self.classify_patch.start()
        self.capabilities = self.capability_patch.start()
        self.addCleanup(self.classify_patch.stop)
        self.addCleanup(self.capability_patch.stop)

    def ui_run(self, root: Path) -> tuple[Path, Path, dict]:
        run_dir, workspace, state = self.make_run(root)
        state["applicable_repositories"] = ["root", "frontend", "backend"]
        (workspace / "frontend").mkdir()
        write_state(run_dir, state)
        return run_dir, workspace, state

    @staticmethod
    def snapshot(run_dir: Path) -> dict[str, bytes]:
        return {str(path.relative_to(run_dir)): path.read_bytes()
                for path in run_dir.rglob("*") if path.is_file()}

    def test_legacy_current_scene_is_read_only_before_classification(self) -> None:
        for kind in ("session", "cycle-session", "reference", "conversation", "success"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                run_dir, _, state = self.make_run(Path(directory))
                if kind == "session":
                    state["claude_sessions"] = {"development_BR-001": "old-session"}
                elif kind == "cycle-session":
                    state["requirement_cycle"]["development_session_id"] = "old-session"
                elif kind == "reference":
                    state["decision_conversations"] = {"development_BR-001": {"path": "conversations/development_BR-001.json"}}
                elif kind == "conversation":
                    path = run_dir / "conversations/development_BR-001.json"
                    path.parent.mkdir()
                    path.write_text('{"messages": []}', encoding="utf-8")
                else:
                    write_requirement_step_result(run_dir, "BR-001", 15, {"status": "success"})
                write_state(run_dir, state)
                before = self.snapshot(run_dir)
                original = json.loads(json.dumps(state))
                with self.assertRaises(development_step.LegacyFrontendContractError):
                    self.run_step(run_dir, state)
                self.assertEqual(self.snapshot(run_dir), before)
                self.assertEqual(state, original)
                self.classify.assert_not_awaited()

    def test_historical_success_does_not_acquire_new_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            state.update(step=16, current_step=16, current_node=development_step.NEXT_NODE)
            state["claude_sessions"] = {"development_BR-001": "old-session"}
            state["requirement_cycle"]["development_session_id"] = "old-session"
            saved = development_step.result("success", "历史已完成", requirement_id="BR-001",
                                trd_path="docs/trd/BR-001.md", development_session_id="old-session")
            write_requirement_step_result(run_dir, "BR-001", 15, saved)
            write_state(run_dir, state)
            before = self.snapshot(run_dir)
            development_step.validate_existing_contract(run_dir, state)
            self.assertEqual(self.run_step(run_dir, state), saved)
            self.assertEqual(self.snapshot(run_dir), before)
            self.classify.assert_not_awaited()

    def test_frontend_then_integration_use_full_handoff_and_updated_trd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))
            prompts, systems, calls = [], [], []
            verdicts = iter([decision("continue", answer="补充窄屏结果"), decision("completed"), decision("completed")])

            async def agent(prompt: str, **kwargs: object):
                prompts.append(prompt)
                calls.append((kwargs["task"], kwargs.get("resume_session_id")))
                self.assertIn("frontend_applicability", read_state(run_dir)["development_BR-001"])
                if len(prompts) < 3:
                    self.assertNotIn("development_session_id", state["requirement_cycle"])
                    (workspace / "docs/trd/BR-001.md").write_text("# TRD\n授权修订后的输入语义", encoding="utf-8")
                    return frontend_agent_result(workspace, session="frontend-session", text="入口与模拟边界" if len(prompts) == 1 else "局部窄屏补证")
                self.assertEqual(state["current_node"], CURRENT_NODE)
                self.assertFalse((run_dir / "steps/requirements/BR-001/15.json").exists())
                return frontend_agent_result(workspace)

            async def decide(*_: object, **kwargs: object):
                systems.append(kwargs["system_prompt"])
                return next(verdicts)

            saved = self.run_step(run_dir, state, agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
            self.assertTrue(prompts[0].startswith("/frontend-ui-ux\n"))
            self.assertIn("/ui-ux-pro-max:ui-ux-pro-max", prompts[0])
            self.assertTrue(prompts[2].startswith("/dev-workflow\n"))
            for handoff in ("入口与模拟边界", "局部窄屏补证"):
                self.assertIn(handoff, prompts[2])
                self.assertIn(handoff, systems[2])
            self.assertIn("授权修订后的输入语义", systems[2])
            self.assertEqual(calls, [("development", None), ("development", "frontend-session"), ("development", None)])
            self.assertEqual(saved["frontend"], {"applicable": True, "reason": "有用户交互", "session_id": "frontend-session"})
            self.assertEqual(state["requirement_cycle"]["development_session_id"], "development-session-1")
            self.assertEqual(state["requirement_registry"]["requirements"][0]["status"], "active")
            self.assertIsNone(state["requirement_registry"]["requirements"][0]["completion"])
            self.classify.assert_awaited_once()
            self.assertEqual(self.classify.await_args.kwargs["purpose"], "requirement")
            self.assertIn("TRD_CONTEXT_MARKER", self.classify.await_args.kwargs["context"])
            for prompt in (prompts[0], prompts[2], systems[0], systems[2]):
                self.assertNotIn(str(run_dir), prompt)
                self.assertNotRegex(prompt, r"第\s*(14|15|16)\s*步|requirement:15")

    def test_frontend_blocked_preserves_scope_without_backend_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))
            agent = AsyncMock(return_value=frontend_agent_result(workspace, session="frontend-session"))
            decide = AsyncMock(return_value=decision("blocked", reason="缺少设计输入", required_inputs=["设计输入"]))
            with self.assertRaises(development_step.DevelopmentBlocked) as caught:
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
            self.assertIsNone(caught.exception.development_session_id)
            self.assertEqual(caught.exception.frontend["session_id"], "frontend-session")
            self.assertNotIn("development_session_id", state["requirement_cycle"])
            self.assertEqual(state["current_node"], development_step.CURRENT_NODE)
            scope = development_step.failure_scope(run_dir, state)
            self.assertEqual(scope["frontend"], caught.exception.frontend)
            saved = json.loads((run_dir / "steps/requirements/BR-001/15.json").read_text())
            self.assertEqual(saved["frontend"], scope["frontend"])
            agent.assert_awaited_once()

    def test_backend_failure_resume_does_not_rerun_frontend_or_classify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))
            calls = []

            async def agent(prompt: str, **kwargs: object):
                calls.append(kwargs.get("resume_session_id"))
                if len(calls) == 1:
                    return frontend_agent_result(workspace, session="frontend-session")
                value = frontend_agent_result(workspace, session="backend-session")
                if len(calls) == 2:
                    value.result_subtype = None
                    value.text = ""
                    kwargs["on_update"](value)
                    raise OSError("后端连接中断")
                return value

            decide = AsyncMock(return_value=decision("completed"))
            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
            resumed = read_state(run_dir)
            self.assertEqual(resumed["requirement_cycle"]["development_session_id"], "backend-session")
            message = ResumeMessage(target_key="development_BR-001", content="后端连接已恢复")
            saved = self.run_step(run_dir, resumed, agent_runner=agent, decision_runner=decide, config_loader=lambda: object(), resume_message=message)
            self.assertTrue(message.consumed)
            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls, [None, None, "backend-session"])
            self.classify.assert_awaited_once()

    def test_frontend_blocked_resume_targets_frontend_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))
            calls = []
            verdicts = iter([decision("blocked", reason="缺少设计输入", required_inputs=["设计输入"]), decision("completed"), decision("completed")])

            async def agent(prompt: str, **kwargs: object):
                calls.append((prompt, kwargs.get("resume_session_id")))
                return frontend_agent_result(workspace, session="frontend-session" if len(calls) < 3 else "backend-session")

            async def decide(*_: object, **__: object):
                return next(verdicts)

            with self.assertRaises(development_step.DevelopmentBlocked):
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
            message = ResumeMessage(target_key="frontend_ui_ux_BR-001", content="已提供必要设计输入")
            saved = self.run_step(run_dir, read_state(run_dir), agent_runner=agent, decision_runner=decide, config_loader=lambda: object(), resume_message=message)
            self.assertTrue(message.consumed)
            self.assertEqual(calls[1], (message.content, "frontend-session"))
            self.assertTrue(calls[2][0].startswith("/dev-workflow\n"))
            self.assertIsNone(calls[2][1])
            self.assertEqual(saved["development_session_id"], "backend-session")
            self.classify.assert_awaited_once()

    def test_frontend_blocked_then_backend_init_interruption_remains_message_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))
            calls = []
            verdicts = iter([
                decision("blocked", reason="缺少设计输入", required_inputs=["设计输入"]),
                decision("completed"), decision("completed"),
            ])

            async def agent(prompt: str, **kwargs: object):
                calls.append((prompt, kwargs.get("resume_session_id")))
                value = frontend_agent_result(workspace, session="frontend-session" if len(calls) < 3 else "backend-session")
                if len(calls) == 3:
                    value.result_subtype = None
                    value.text = ""
                    kwargs["on_update"](value)
                    raise asyncio.CancelledError()
                return value

            async def decide(*_: object, **__: object):
                return next(verdicts)

            with self.assertRaises(DevelopmentBlocked):
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
            with self.assertRaises(asyncio.CancelledError):
                self.run_step(run_dir, read_state(run_dir), agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
            interrupted = read_state(run_dir)
            message_file = Path(directory) / "resume.txt"
            message_file.write_text("继续后端实现", encoding="utf-8")
            message = prepare_resume_message(message_file, run_dir, interrupted, STEP)
            self.assertEqual(message.target_key, "development_BR-001")
            self.assertEqual(interrupted["status"], "running")
            self.assertIsNone(interrupted["blocked"])
            self.assertIsNone(interrupted["error"])
            saved = self.run_step(run_dir, interrupted, agent_runner=agent, decision_runner=decide, config_loader=lambda: object(), resume_message=message)
            self.assertTrue(message.consumed)
            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls[-1], ("继续后端实现", "backend-session"))
            self.assertEqual(len(calls), 4)

    def test_existing_backend_blocked_keeps_automatic_resume_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))
            calls = []
            verdicts = iter([decision("completed"), decision("blocked", reason="缺少后端授权", required_inputs=["授权"]), decision("completed")])

            async def agent(prompt: str, **kwargs: object):
                calls.append((prompt, kwargs.get("resume_session_id")))
                return frontend_agent_result(workspace, session="frontend-session" if len(calls) == 1 else "backend-session")

            async def decide(*_: object, **__: object):
                return next(verdicts)

            with self.assertRaises(DevelopmentBlocked):
                self.run_step(run_dir, state, agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
            saved = self.run_step(run_dir, read_state(run_dir), agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
            self.assertEqual(saved["status"], "success")
            self.assertEqual(calls[-1], (BLOCKED_RESUME_PROMPT, "backend-session"))
            self.assertEqual(len(calls), 3)

    def test_frontend_execution_failure_preserves_known_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))

            async def agent(_prompt: str, **kwargs: object):
                update = frontend_agent_result(workspace, session="frontend-session", text="")
                update.result_subtype = None
                kwargs["on_update"](update)
                raise OSError("前端通道中断")

            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, state, agent_runner=agent, config_loader=lambda: object())
            scope = development_step.failure_scope(run_dir, read_state(run_dir))
            self.assertIsNone(scope["development_session_id"])
            self.assertEqual(scope["frontend"]["session_id"], "frontend-session")
            self.assertNotIn("development_BR-001", state["claude_sessions"])
            self.assertEqual(development_step.result("failed", "执行失败", **scope)["frontend"], scope["frontend"])

    def test_completed_conversations_and_success_write_windows_resume_without_agents(self) -> None:
        for window in ("before-result", "before-advance"):
            with self.subTest(window=window), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.ui_run(Path(directory))
                agent = AsyncMock(side_effect=[frontend_agent_result(workspace, session="frontend-session"), frontend_agent_result(workspace)])
                decide = AsyncMock(return_value=decision("completed"))
                original = development_step.write_state

                def interrupt_advance(path: Path, value: dict):
                    if value.get("current_node") == development_step.NEXT_NODE:
                        raise OSError("状态推进中断")
                    original(path, value)

                interruption = (patch.object(development_step, "write_requirement_step_result", side_effect=OSError("结果写入中断"))
                                if window == "before-result" else patch.object(development_step, "write_state", side_effect=interrupt_advance))
                with interruption, self.assertRaises(OSError):
                    self.run_step(run_dir, state, agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
                agent_calls, decision_calls = agent.await_count, decide.await_count
                recovered = self.run_step(run_dir, read_state(run_dir), agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
                self.assertEqual(recovered["status"], "success")
                self.assertEqual(agent.await_count, agent_calls)
                self.assertEqual(decide.await_count, decision_calls)
                before = self.snapshot(run_dir)
                self.assertEqual(self.run_step(run_dir, read_state(run_dir)), recovered)
                self.assertEqual(self.snapshot(run_dir), before)
                self.assertEqual(self.classify.await_count, 1)
                self.classify.reset_mock()

    def test_pure_frontend_requirement_still_runs_integration_without_backend_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))
            state["applicable_repositories"] = ["root", "frontend"]
            agent = AsyncMock(side_effect=[frontend_agent_result(workspace, session="frontend-session"), frontend_agent_result(workspace)])
            saved = self.run_step(run_dir, state, agent_runner=agent, decision_runner=AsyncMock(return_value=decision("completed")), config_loader=lambda: object())
            self.assertEqual(agent.await_count, 2)
            self.assertEqual(saved["status"], "success")
            self.assertFalse((workspace / "backend").exists())


    def test_saved_applicability_only_resumes_without_reclassification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            scope = {"applicable": False, "reason": "纯后端需求"}
            state["development_BR-001"] = {"frontend_applicability": scope}
            write_state(run_dir, state)
            agent = AsyncMock(return_value=frontend_agent_result(workspace))
            saved = self.run_step(run_dir, state, agent_runner=agent, decision_runner=AsyncMock(return_value=decision("completed")), config_loader=lambda: object())
            self.assertEqual(saved["frontend"], {**scope, "session_id": None})
            agent.assert_awaited_once()
            self.assertTrue(agent.await_args.args[0].startswith("/dev-workflow\n"))
            self.assertNotIn("frontend_ui_ux_BR-001", state["claude_sessions"])
            self.classify.assert_not_awaited()
            self.capabilities.assert_not_called()

    def test_backend_only_requirement_skips_frontend_even_with_frontend_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))
            self.classify.return_value = {"applicable": False, "reason": "仅调整后端规则"}
            agent = AsyncMock(return_value=frontend_agent_result(workspace))
            saved = self.run_step(run_dir, state, agent_runner=agent, decision_runner=AsyncMock(return_value=decision("completed")), config_loader=lambda: object())
            self.assertFalse(saved["frontend"]["applicable"])
            self.assertIsNone(saved["frontend"]["session_id"])
            self.assertEqual(agent.await_count, 1)
            self.assertNotIn("frontend_ui_ux_BR-001", state["claude_sessions"])
            self.capabilities.assert_not_called()

    def test_current_success_requires_strict_matching_frontend_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.ui_run(Path(directory))
            agent = AsyncMock(side_effect=[frontend_agent_result(workspace, session="frontend-session"), frontend_agent_result(workspace)])
            saved = self.run_step(run_dir, state, agent_runner=agent, decision_runner=AsyncMock(return_value=decision("completed")), config_loader=lambda: object())
            state.update(step=15, current_step=15, current_node=development_step.CURRENT_NODE)
            for invalid in (None, {"applicable": 1, "reason": "有用户交互", "session_id": "frontend-session"},
                            {"applicable": True, "reason": "", "session_id": "frontend-session"},
                            {"applicable": True, "reason": "有用户交互", "session_id": "wrong-session"}):
                with self.subTest(frontend=invalid):
                    write_requirement_step_result(run_dir, "BR-001", 15, {**saved, "frontend": invalid})
                    self.assertFalse(development_step.has_complete_success(run_dir, state))
            write_requirement_step_result(run_dir, "BR-001", 15, saved)
            self.assertTrue(development_step.has_complete_success(run_dir, state))

    def test_invalid_classification_never_becomes_not_applicable(self) -> None:
        for scope in ({"applicable": "false", "reason": "后端"}, {"applicable": False, "reason": ""}, None):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as directory:
                run_dir, _, state = self.make_run(Path(directory))
                self.classify.return_value = scope
                agent = AsyncMock()
                with self.assertRaises((RuntimeError, ValueError)):
                    self.run_step(run_dir, state, agent_runner=agent, config_loader=lambda: object())
                agent.assert_not_awaited()
                self.assertNotIn("frontend", development_step.failure_scope(run_dir, state))

    def test_malformed_saved_classification_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            state["development_BR-001"] = {"frontend_applicability": {"applicable": "false", "reason": "错误"}}
            write_state(run_dir, state)
            before = self.snapshot(run_dir)
            with self.assertRaises((RuntimeError, ValueError)):
                self.run_step(run_dir, state)
            self.assertEqual(self.snapshot(run_dir), before)
            self.classify.assert_not_awaited()

    def test_missing_frontend_or_capability_fails_before_agent(self) -> None:
        for kind in ("repository", "capability"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.ui_run(Path(directory))
                if kind == "repository":
                    state["applicable_repositories"] = ["root", "backend"]
                else:
                    self.capabilities.side_effect = RuntimeError("缺少前端能力")
                agent = AsyncMock()
                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state, agent_runner=agent, config_loader=lambda: object())
                agent.assert_not_awaited()
                self.assertTrue(development_step.failure_scope(run_dir, state)["frontend"]["applicable"])
                self.assertIsNone(development_step.failure_scope(run_dir, state)["frontend"]["session_id"])

    def test_both_domains_receive_quality_and_feedback_evidence(self) -> None:
        for workflow, module, phase in (("product_quality", "quality.workflow", "product_quality_iteration"), ("product_feedback", "feedback.workflow", "product_feedback_iteration")):
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.ui_run(Path(directory))
                state.update(workflow=workflow, phase=phase)
                prompts, systems = [], []

                async def agent(prompt: str, **_: object):
                    prompts.append(prompt)
                    return frontend_agent_result(workspace, session="frontend-session" if len(prompts) == 1 else "backend-session")

                async def decide(*_: object, **kwargs: object):
                    systems.append(kwargs["system_prompt"])
                    return decision("completed")

                with patch(f"{module}.requirement_evidence", return_value="原场景与采纳目标_MARKER"):
                    self.run_step(run_dir, state, agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
                self.assertEqual(len(prompts), 2)
                for text in prompts + systems:
                    self.assertIn("原场景与采纳目标_MARKER", text)


if __name__ == "__main__":
    unittest.main()
