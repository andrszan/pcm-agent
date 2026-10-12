from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import run_all
import run_step
from common.files import write_json
from common.frontend_scope import LegacyFrontendContractError
from common.state import read_state


class FrontendContractCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "runs").mkdir()
        for patcher in (
            patch.object(run_step, "DEMO_ROOT", self.root),
            patch.object(run_step, "load_model_policy"),
            patch.object(run_step, "load_settings", return_value=SimpleNamespace(pcm_max_concurrent_projects=1)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def legacy_run(self, step: int) -> tuple[Path, dict]:
        run = self.root / "runs" / f"legacy-{step}"
        (run / "steps/requirements/BR-001").mkdir(parents=True)
        (run / "conversations").mkdir()
        nodes = {2: "project:02_intake", 6: "project:06_bootstrap_foundation", 10: "project:10_ui_ux_framework", 15: "requirement:15_development"}
        key = "development_BR-001" if step == 15 else "project_intake"
        state = {
            "run_id": run.name, "status": "success", "step": step, "current_step": step,
            "current_node": nodes[step],
            "phase": "phase_1_requirement_development" if step == 15 else "project_initialization",
            "workspace": {"root": str(self.root), "final_path": str(self.root / "product")},
            "active_requirement": "BR-001" if step == 15 else None,
            "requirement_cycle": {"development_session_id": "old-session"} if step == 15 else None,
            "claude_sessions": {key: "old-session"},
            "decision_conversations": {key: {"path": f"conversations/{key}.json"}},
        }
        write_json(run / "state.json", state)
        write_json(run / "conversations" / f"{key}.json", {"messages": [{"role": "system", "content": "旧任务快照"}]})
        result_path = run / ("steps/requirements/BR-001/15.json" if step == 15 else "steps/02.json")
        write_json(result_path, {"step": 15 if step == 15 else 2, "status": "success", "outputs": []})
        return run, state

    @staticmethod
    def snapshot(run: Path) -> dict[str, bytes]:
        return {str(p.relative_to(run)): p.read_bytes() for p in run.rglob("*") if p.is_file()}

    @staticmethod
    def args(run: Path, step: int) -> Namespace:
        return Namespace(step=step, run_id=run.name, resume_message_file=None, coordination_locks=None)

    def test_cli_rejects_legacy_before_coordination_or_failure_writes(self) -> None:
        for step in (2, 6, 10, 15):
            with self.subTest(step=step):
                run, _ = self.legacy_run(step)
                before = self.snapshot(run)
                with (
                    patch.object(run_step, "parse_args", return_value=self.args(run, step)),
                    patch.object(run_step, "_ensure_product_claim") as claim,
                    patch.object(run_step, "_execute") as execute,
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(run_step.main(), 1)
                claim.assert_not_called()
                execute.assert_not_called()
                self.assertEqual(self.snapshot(run), before)

    def test_step_exception_rejection_bypasses_scoped_failure_handler(self) -> None:
        run, _ = self.legacy_run(15)
        before = self.snapshot(run)
        with (
            patch.object(run_step, "run_step_fifteen", AsyncMock(side_effect=LegacyFrontendContractError("旧合同"))),
            patch.object(run_step, "development_failure_scope") as failure_scope,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(run_step._execute(self.args(run, 15), Mock()), 1)
        failure_scope.assert_not_called()
        self.assertEqual(self.snapshot(run), before)

    def test_full_runner_rejects_before_product_attachment(self) -> None:
        run, _ = self.legacy_run(15)
        before = self.snapshot(run)
        args = Namespace(resume=run.name, with_quality=False, resume_message_file=None)
        with (
            patch.object(run_all, "_attach_product_lock") as attach,
            patch.object(run_all, "run_child") as child,
            patch.object(run_all, "_print_stop"),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(run_all._run_steps(args, run.name, run, Mock(), None), 1)
        attach.assert_not_called()
        child.assert_not_called()
        self.assertEqual(self.snapshot(run), before)

    def test_full_runner_preserves_nullable_legacy_intake_anchor(self) -> None:
        run, state = self.legacy_run(2)
        state.update(phase=None, step=None, current_node=None)
        write_json(run / "state.json", state)
        before = self.snapshot(run)
        args = Namespace(resume=run.name, with_quality=False, resume_message_file=None)
        with (
            patch.object(run_all, "_attach_product_lock") as attach,
            patch.object(run_all, "run_child") as child,
            patch.object(run_all, "_print_stop"),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(run_all._run_steps(args, run.name, run, Mock(), None), 1)
        attach.assert_not_called()
        child.assert_not_called()
        self.assertEqual(self.snapshot(run), before)

    def test_past_nodes_are_not_reclassified_as_current_legacy(self) -> None:
        for step, next_node in ((2, "project:03_foundation_selection"), (15, "requirement:16_rule_retrospective")):
            with self.subTest(step=step):
                run, state = self.legacy_run(step)
                state.update(step=step + 1, current_step=step + 1, current_node=next_node)
                before = self.snapshot(run)
                run_step.validate_frontend_contract(run, state, step)
                self.assertEqual(self.snapshot(run), before)

    def test_classification_only_state_is_not_legacy(self) -> None:
        run = self.root / "runs" / "classification-only"
        (run / "steps").mkdir(parents=True)
        state = {"current_node": "requirement:15_development", "active_requirement": "BR-001",
                 "development_BR-001": {"frontend_applicability": {"applicable": True, "reason": "有页面"}}}
        run_step.validate_frontend_contract(run, state, 15)
        self.assertFalse((run / "state.json").exists())

    def test_quality_and_feedback_evidence_reaches_both_development_domains(self) -> None:
        import sys
        import types
        from steps.step_15_development import step as development
        from steps.step_15_development import test_step as helpers

        for workflow_name, package, phase in (
            ("product_quality", "quality", "product_quality_iteration"),
            ("product_feedback", "feedback", "product_feedback_iteration"),
        ):
            with self.subTest(workflow=workflow_name), tempfile.TemporaryDirectory() as directory:
                fixture = helpers.DevelopmentTests()
                run, workspace, state = fixture.make_run(Path(directory))
                (workspace / "frontend").mkdir()
                state.update(workflow=workflow_name, phase=phase, applicable_repositories=["root", "frontend"])
                evidence_text = f"{package}: 原场景与当前需求的采纳目标"
                module = types.ModuleType(f"{package}.workflow")
                module.requirement_evidence = Mock(return_value=evidence_text)
                prompts, decision_contexts, sessions = [], [], []

                async def agent(prompt, **kwargs):
                    prompts.append(prompt)
                    sessions.append(kwargs["resume_session_id"])
                    frontend = prompt.startswith("/frontend-ui-ux")
                    value = helpers.agent_result(
                        workspace, session="frontend-session" if frontend else "development-session",
                        text="完整前端交接：仅接口尚需接入" if frontend else "真实集成完成",
                    )
                    skill = "frontend-ui-ux" if frontend else "dev-workflow"
                    value.init.update(skills=[skill], slash_commands=[skill])
                    return value

                async def decide(*args, **kwargs):
                    decision_contexts.append(kwargs["system_prompt"])
                    return helpers.decision("completed")

                with (
                    patch.dict(sys.modules, {f"{package}.workflow": module}),
                    patch.object(development, "classify_frontend_scope", AsyncMock(return_value={"applicable": True, "reason": "需要修复页面"})),
                    patch.object(development, "ensure_frontend_capabilities"),
                ):
                    saved = fixture.run_step(run, state, agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
                self.assertEqual(saved["status"], "success")
                self.assertEqual(sessions, [None, None])
                self.assertEqual(len(prompts), 2)
                for prompt in prompts:
                    self.assertIn(evidence_text, prompt)
                for context in decision_contexts:
                    self.assertIn(evidence_text, context)
                self.assertIn("完整前端交接：仅接口尚需接入", prompts[1])
                self.assertEqual(state["phase"], phase)
                self.assertEqual(state["requirement_cycle"]["development_session_id"], "development-session")
                self.assertEqual(saved["frontend"]["session_id"], "frontend-session")
                module.requirement_evidence.assert_called_once()

    def test_known_prototype_does_not_invent_unknown_false(self) -> None:
        run = self.root / "runs" / "prototype"
        run.mkdir()
        write_json(run / "state.json", {"project_intake": {}})
        self.assertIsNone(run_step._known_prototype(run))
        prototype = {"applicable": True, "entry": "docs/prototype/index.html", "reason": "用户界面"}
        write_json(run / "state.json", {"project_intake": {"prototype": prototype}})
        self.assertEqual(run_step._known_prototype(run), prototype)
        self.assertEqual(read_state(run)["project_intake"]["prototype"], prototype)
