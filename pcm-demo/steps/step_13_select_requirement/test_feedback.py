from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.requirement_context import phase_for, selection_node_for
from common import requirement_registry
from common.state import write_state
from steps.step_12_initialize_requirement_registry import step as initialization
from steps.step_13_select_requirement import step as selection, test_step as selection_tests
from steps.step_14_trd_design import step as trd, test_step as trd_tests
from steps.step_15_development import step as development, test_step as development_tests
from steps.step_16_rule_retrospective import step as retrospective, test_step as retrospective_tests
from steps.step_17_commit import step as commit, test_step as commit_tests
from steps.step_18_merge import step as merge, test_step as merge_tests


def feedback_state(state: dict) -> None:
    state.update(workflow="product_feedback", phase="product_feedback_iteration")
    if state.get("requirement_cycle") is not None:
        state["requirement_cycle"]["return_node_after_completion"] = "feedback:select_requirement"
    if state["current_node"] == selection.CURRENT_NODE:
        state.update(step=13, current_step=13, current_node="feedback:select_requirement")


class FeedbackRequirementLoopTests(unittest.TestCase):
    def test_context_defaults_and_unknown_workflow(self) -> None:
        self.assertEqual(phase_for({}), initialization.PHASE)
        self.assertEqual(selection_node_for({}), selection.CURRENT_NODE)
        state = {"workflow": "product_feedback"}
        self.assertEqual(phase_for(state), "product_feedback_iteration")
        self.assertEqual(selection_node_for(state), "feedback:select_requirement")
        for value in (None, "", "phase_1", "unknown", {}):
            for helper in (phase_for, selection_node_for):
                with self.subTest(value=value, helper=helper), self.assertRaises(RuntimeError):
                    helper({"workflow": value})
        catalog = [{"id": "REQ-001", "title": "账户", "order": 1, "depends_on": []}]
        for module in (initialization, requirement_registry):
            parsed = module.RequirementCatalog(requirements=[module.RequirementStatic(**catalog[0])])
            self.assertEqual(module.validate_catalog(parsed), catalog)

    def test_feedback_selection_recovery_preserves_existing_requirements(self) -> None:
        fixture = selection_tests.SelectRequirementTests()
        requirements = [
            {**item, "status": "completed" if index == 0 else "pending",
             "completion": {"step": 18} if index == 0 else None}
            for index, item in enumerate(fixture.catalog())
        ]
        historical = copy.deepcopy(requirements[0])
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = fixture.make_run(Path(directory), ["root"], requirements)
            feedback_state(state)
            unselected = copy.deepcopy(state)
            unselected.update(step=None, current_step=None)
            before = copy.deepcopy(unselected)
            with self.assertRaises(RuntimeError):
                selection.run(run_dir, unselected)
            self.assertEqual(unselected, before)
            saved = selection.run(run_dir, state)
            self.assertEqual(saved["requirement_id"], "REQ-002")
            self.assertEqual(state["phase"], "product_feedback_iteration")
            self.assertEqual(state["requirement_cycle"]["return_node_after_completion"], "feedback:select_requirement")
            self.assertEqual(state["requirement_registry"]["requirements"][0], historical)
            self.assertTrue(selection.has_complete_success(run_dir, state))
            self.assertIsNotNone(selection.failure_scope(run_dir, state))
            self.assertEqual(selection.run(run_dir, state), saved)
            state["workflow"] = "unknown"
            self.assertFalse(selection.has_complete_success(run_dir, state))
            self.assertIsNone(selection.failure_scope(run_dir, state))
            with self.assertRaises(RuntimeError):
                selection.run(run_dir, state)

    def test_feedback_agent_steps_input_scoping_blocked_and_success_recovery(self) -> None:
        cases = (
            (trd, trd_tests, trd_tests.TRDDesignTests, trd.TRDDesignBlocked),
            (development, development_tests, development_tests.DevelopmentTests, development.DevelopmentBlocked),
            (retrospective, retrospective_tests, retrospective_tests.RuleRetrospectiveTests, retrospective.RuleRetrospectiveBlocked),
        )
        for step, helpers, fixture_type, blocked_type in cases:
            for verdict in ("completed", "blocked"):
                with self.subTest(step=step.STEP, verdict=verdict), tempfile.TemporaryDirectory() as directory:
                    fixture = fixture_type()
                    run_dir, workspace, state = fixture.make_run(Path(directory))
                    feedback_state(state)
                    # 无关历史项不必具备全量静态字段；当前步骤只消费活动需求。
                    historical = {"id": "OLD", "status": "completed", "completion": {"step": 18}}
                    state["requirement_registry"]["requirements"].append(historical.copy())
                    write_state(run_dir, state)
                    prompts, decisions = [], []
                    evidence = Mock(return_value="反馈 F-001：原场景\r\n  采纳目标与必要决定；regression owner BR-001\n")
                    workflow = types.ModuleType("feedback.workflow")
                    workflow.requirement_evidence = evidence

                    async def agent(prompt, **kwargs):
                        prompts.append(prompt)
                        if step is trd:
                            fixture.write_trd(workspace, state)
                        return helpers.agent_result(workspace)

                    async def decide(*args, **kwargs):
                        decisions.append(kwargs["system_prompt"])
                        return helpers.decision(verdict, required_inputs=["测试外部输入"] if verdict == "blocked" else [])

                    with patch.dict(sys.modules, {"feedback.workflow": workflow}):
                        kwargs = dict(agent_runner=agent, decision_runner=decide, config_loader=lambda: object())
                        if verdict == "blocked":
                            with self.assertRaises(blocked_type):
                                fixture.run_step(run_dir, state, **kwargs)
                            self.assertEqual(state["current_step"], step.STEP)
                            self.assertIsNotNone(step.failure_scope(run_dir, state))
                        else:
                            saved = fixture.run_step(run_dir, state, **kwargs)
                            self.assertEqual(state["current_step"], step.STEP + 1)
                            self.assertTrue(step.has_complete_success(run_dir, state))
                            evidence.side_effect = AssertionError("成功恢复不应读取反馈输入")
                            self.assertEqual(fixture.run_step(run_dir, state, **kwargs), saved)
                        self.assertEqual(state["phase"], "product_feedback_iteration")
                        self.assertEqual(state["requirement_registry"]["requirements"][-1], historical)
                        if step in (trd, development):
                            evidence.assert_called_once_with(run_dir, state)
                            self.assertIn(evidence.return_value, prompts[0])
                            context_text = decisions[0].split("<project_context>", 1)[1].split("</project_context>", 1)[0]
                            project_context, _ = json.JSONDecoder().raw_decode(context_text[context_text.index("{"):])
                            self.assertEqual(project_context["当前需求相关原反馈与采纳目标"], evidence.return_value)
                        else:
                            evidence.assert_not_called()
                        state["workflow"] = "unknown"
                        self.assertFalse(step.has_complete_success(run_dir, state))
                        self.assertIsNone(step.failure_scope(run_dir, state))
                        with self.assertRaises(RuntimeError):
                            fixture.run_step(run_dir, state, **kwargs)

    def test_feedback_commit_and_merge_use_real_git_and_return_to_feedback(self) -> None:
        fixture = commit_tests.RequirementCommitTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        run_dir, workspace, state, _ = fixture.make_run(["web"])
        feedback_state(state)
        historical = {"id": "OLD", "status": "completed", "completion": {"step": 18}}
        state["requirement_registry"]["requirements"].append(historical.copy())
        self.assertIsNotNone(commit.failure_scope(run_dir, state))
        invalid = copy.deepcopy(state)
        invalid["workflow"] = "unknown"
        self.assertIsNone(commit.failure_scope(run_dir, invalid))
        self.assertFalse(commit.has_complete_success(run_dir, invalid))
        with self.assertRaises(RuntimeError):
            asyncio.run(commit.run(run_dir, invalid))
        saved = asyncio.run(commit.run(run_dir, state))
        self.assertEqual(state["phase"], "product_feedback_iteration")
        self.assertTrue(commit.has_complete_success(run_dir, state))
        self.assertEqual(asyncio.run(commit.run(run_dir, state)), saved)
        self.assertIsNotNone(merge.failure_scope(run_dir, state))
        merge.run(run_dir, state)
        self.assertEqual((state["step"], state["current_step"], state["current_node"]), (None, None, "feedback:select_requirement"))
        self.assertEqual(state["phase"], "product_feedback_iteration")
        self.assertEqual(state["requirement_registry"]["requirements"][0]["status"], "completed")
        self.assertEqual(state["requirement_registry"]["requirements"][-1], historical)
        self.assertIsNone(state["active_requirement"])
        self.assertIsNone(state["requirement_cycle"])
        for repository in (workspace, workspace / "web"):
            self.assertEqual(commit_tests.command("branch", "--show-current", cwd=repository), "main")
        self.assertIsNone(merge.failure_scope(run_dir, state))

    def test_feedback_merge_saved_success_recovers_without_git_writes(self) -> None:
        fixture = merge_tests.RequirementMergeTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        run_dir, _, state, repositories, _, tips = fixture.make_run(["web"])
        feedback_state(state)
        with patch.object(merge, "_advance", side_effect=RuntimeError("模拟结果落盘后中断")):
            with self.assertRaises(RuntimeError):
                merge.run(run_dir, state)
        self.assertTrue(merge.has_complete_success(run_dir, state))
        self.assertIsNotNone(merge.failure_scope(run_dir, state))
        with patch.object(merge, "_git_write", side_effect=AssertionError("成功恢复不能重复写 Git")):
            saved = merge.run(run_dir, state)
        self.assertEqual(saved["status"], "success")
        self.assertEqual(state["current_node"], "feedback:select_requirement")
        fixture.assert_final(repositories, tips)

    def test_feedback_merge_rejects_wrong_return_node_and_unknown_workflow(self) -> None:
        fixture = merge_tests.RequirementMergeTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        run_dir, _, state, _, _, _ = fixture.make_run()
        feedback_state(state)
        for mutation in ({"workflow": "unknown"}, {"phase": initialization.PHASE}):
            invalid = copy.deepcopy(state)
            invalid.update(mutation)
            self.assertFalse(merge.has_complete_success(run_dir, invalid))
            self.assertIsNone(merge.failure_scope(run_dir, invalid))
            with self.assertRaises(RuntimeError):
                merge.run(run_dir, invalid)
        state["requirement_cycle"]["return_node_after_completion"] = selection.CURRENT_NODE
        with self.assertRaises(RuntimeError):
            merge.run(run_dir, state)


if __name__ == "__main__":
    unittest.main()
