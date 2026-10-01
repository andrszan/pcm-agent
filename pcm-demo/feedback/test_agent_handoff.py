from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from common import agent_decision_loop as loop
from common.claude_agent import ClaudeRunResult
from common.decision import AgentDecision
from common.files import write_json
from common.state import read_state
from feedback import workflow
from feedback.models import PoolPlan, TriageReport
from feedback.test_workflow import git, routing_report, triage_report
from model_policy import AgentProfile


class FeedbackAgentHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.run = self.base / "run"
        self.root = self.base / "product"
        self.run.mkdir()
        self.root.mkdir()
        self.state = {"workspace": {"root": str(self.base), "final_path": str(self.root)}}
        self.agent = AsyncMock()
        completed = AgentDecision(verdict="completed", answer="", reason="本批核验完成", required_inputs=[])
        self.decision = AsyncMock(return_value=(completed.model_dump(), 1, completed.model_dump_json()))
        self.parse = AsyncMock(return_value=triage_report())
        self.specs = []

        async def run_loop(*args, **kwargs):
            self.specs.append(args[3])
            return await loop.run_agent_decision_loop(*args, **kwargs, agent_runner=self.agent,
                                                     decision_runner=self.decision, config_loader=lambda: object())

        for patcher in (
            patch.object(workflow, "run_agent_decision_loop", side_effect=run_loop),
            patch.object(workflow, "parse_response", self.parse),
            patch.object(workflow.LLMConfig, "load", return_value=object()),
            patch.object(loop, "get_agent_profile", return_value=AgentProfile("planning", "test-model", "high")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def result(self, text, *, skill="product-feedback-triage"):
        return ClaudeRunResult(init={"cwd": str(self.root), "skills": [skill] if skill else [],
                                     "slash_commands": [skill] if skill else []},
                               text=text, result_subtype="success", is_error=False, session_id="feedback-session",
                               stop_reason=None, num_turns=1, total_cost_usd=0, exception=None)

    async def triage(self, **kwargs):
        return await workflow._task(self.run, self.state, "feedback_triage", "feedback_triage",
                                    "本批输入、意图、授权和唯一反馈文档位置", "依据完整交接收敛核验",
                                    skill="product-feedback-triage", output_model=TriageReport, **kwargs)

    async def test_full_multi_turn_conversation_keeps_correction_and_other_findings(self):
        self.agent.side_effect = [
            self.result("完整报告：保存失败丢失输入；另有权限误判待核实"),
            self.result("补充：撤销权限误判，保存问题不变"),
        ]
        decisions = [AgentDecision(verdict="continue", answer="只核实权限疑点", reason="局部补证", required_inputs=[]),
                     AgentDecision(verdict="completed", answer="", reason="完整核验已交接", required_inputs=[])]
        self.decision.side_effect = [(value.model_dump(), 1, value.model_dump_json()) for value in decisions]
        raw, parsed = await self.triage()
        extracted = self.parse.await_args.kwargs["input_model"].report
        for text in ("保存失败丢失输入", "撤销权限误判", "只核实权限疑点"):
            self.assertIn(text, raw)
            self.assertIn(text, extracted)
        self.assertEqual(parsed, triage_report())
        self.assertEqual(self.agent.await_count, 2)
        self.parse.assert_awaited_once()
        self.assertEqual(self.agent.await_args.kwargs["resume_session_id"], "feedback-session")

    async def test_structural_repair_continues_same_session_and_preserves_report(self):
        self.agent.side_effect = [self.result("首次完整核验"), self.result("已补齐来源引用")]
        self.parse.side_effect = [ValueError("缺少来源引用"), triage_report()]
        raw, _ = await self.triage()
        self.assertIn("首次完整核验", raw)
        self.assertIn("已补齐来源引用", raw)
        self.assertEqual(self.agent.await_count, 2)
        self.assertEqual(self.agent.await_args.kwargs["resume_session_id"], "feedback-session")
        self.assertEqual(self.state["claude_sessions"], {"feedback_triage": "feedback-session"})

    async def test_extraction_retry_does_not_rerun_completed_triage(self):
        self.agent.return_value = self.result("完整核验原文与限制")
        self.parse.side_effect = [RuntimeError("提取服务临时失败"), triage_report()]
        with self.assertRaises(RuntimeError):
            await self.triage()
        self.state = read_state(self.run)
        raw, _ = await self.triage()
        self.agent.assert_awaited_once()
        self.decision.assert_awaited_once()
        self.assertEqual(self.parse.await_count, 2)
        for call in self.parse.await_args_list:
            self.assertEqual(call.kwargs["input_model"].report, raw)

    async def test_skill_must_be_loaded_before_decision_or_extraction(self):
        self.agent.return_value = self.result("回复却未加载能力", skill=None)
        with self.assertRaises(loop.AgentExecutionFailure):
            await self.triage()
        self.decision.assert_not_awaited()
        self.parse.assert_not_awaited()

    async def test_plain_prepare_returns_full_saved_handoff_without_extraction(self):
        self.agent.return_value = self.result("准备完成\n入口与操作边界", skill=None)
        raw, parsed = await workflow._task(self.run, self.state, "feedback_prepare", "feedback_prepare",
                                           "准备本批必要现场", "交接运行条件")
        self.assertIn("准备完成\n入口与操作边界", [message["content"] for message in json.loads(raw)])
        self.assertIsNone(parsed)
        self.assertIsNone(self.specs[0].skill_name)
        self.parse.assert_not_awaited()
        before = {path: path.read_bytes() for path in self.run.rglob("*.json")}
        loop.agent_conversation_report(self.run, self.state, self.specs[0])
        self.assertEqual(before, {path: path.read_bytes() for path in self.run.rglob("*.json")})

    async def test_missing_split_dependency_is_repaired_in_original_breakdown_session(self):
        self.state["requirement_registry"] = {"requirements": []}
        catalog = [{"id": "BR-001", "title": "接口", "order": 1, "depends_on": []},
                   {"id": "BR-002", "title": "完整结果", "order": 2, "depends_on": []}]
        plan = PoolPlan.model_validate({"summary": "拆分同一目标", "requirements": [
            {"requirement_id": "BR-001", "candidate_ids": ["F-C001"]},
            {"requirement_id": "BR-002", "candidate_ids": ["F-C001"]},
        ], "regression_owners": [{"candidate_id": "F-C001", "requirement_id": "BR-002"}]})
        validations = []
        async def validate(report):
            validations.append(copy_catalog := json.loads(json.dumps(catalog)))
            workflow._validate_increment(self.state, copy_catalog, report)
        async def agent(prompt, **kwargs):
            if kwargs.get("resume_session_id"):
                catalog[1]["depends_on"] = ["BR-001"]
                return self.result("已补齐真实依赖", skill="requirement-breakdown")
            return self.result("新增两项需求并指定回归归属", skill="requirement-breakdown")
        self.agent.side_effect = agent
        self.parse.return_value = plan
        raw, parsed = await workflow._task(self.run, self.state, "feedback_pool", "feedback_pool",
                                           "拆分目标并安排最终回归", "交接新增需求与真实依赖",
                                           skill="requirement-breakdown", output_model=PoolPlan, validate=validate)
        self.assertEqual(len(validations), 2)
        self.assertEqual(validations[0][1]["depends_on"], [])
        self.assertEqual(validations[1][1]["depends_on"], ["BR-001"])
        self.assertEqual(parsed, plan)
        self.assertIn("已补齐真实依赖", raw)
        self.assertEqual(self.agent.await_args.kwargs["resume_session_id"], "feedback-session")

    async def test_fresh_node_interruption_persists_running_and_accepts_original_session_message(self):
        self.state.update(workflow=workflow.WORKFLOW, phase=workflow.PHASE, current_node="feedback:prepare",
                          status="success", blocked=None, error=None, step=None, current_step=None)

        async def prepare(run_dir, state, message):
            return await workflow._task(run_dir, state, "feedback_prepare", "feedback_prepare",
                                        "准备本批必要现场", "交接运行条件", resume_message=message)

        async def interrupted_agent(prompt, **kwargs):
            update = self.result("", skill=None)
            update.result_subtype = None
            kwargs["on_update"](update)
            raise asyncio.CancelledError()

        self.agent.side_effect = interrupted_agent
        with patch.object(workflow, "_prepare", side_effect=prepare):
            with self.assertRaises(asyncio.CancelledError):
                await workflow.run_node(self.run, self.state)
            self.state = read_state(self.run)
            self.assertEqual(self.state["status"], "running")
            self.assertFalse(workflow.node_result_path(self.run, self.state).exists())
            message_file = self.base / "resume.txt"
            message_file.write_text("继续使用现有隔离数据核验", encoding="utf-8")
            message = loop.prepare_node_resume_message(
                self.run, self.state, self.state["current_node"], workflow.node_resume_keys(self.state), message_file,
            )
            self.assertEqual(message.target_key, "feedback_prepare")
            self.agent.side_effect = None
            self.agent.return_value = self.result("入口与操作边界已准备", skill=None)
            await workflow.run_node(self.run, self.state, resume_message=message)
        self.assertTrue(message.consumed)
        self.assertEqual(self.agent.await_args.kwargs["resume_session_id"], "feedback-session")
        self.assertEqual(self.agent.await_args.args[0], "继续使用现有隔离数据核验")

    async def test_route_external_authorization_blocks_and_resumes_same_session_through_public_api(self):
        backlog = self.root / "docs/backlog/backlog.md"
        backlog.parent.mkdir(parents=True)
        backlog.write_text("BR-001 保存材料\n", encoding="utf-8")
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "测试")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "add", "--", "docs/backlog/backlog.md")
        git(self.root, "commit", "-m", "docs: 初始化")
        base = git(self.root, "rev-parse", "HEAD")
        branch = "feedback/route-test/documents"
        git(self.root, "switch", "-c", branch)
        document_relative = "docs/feedback/batch.md"
        document = self.root / document_relative
        document.parent.mkdir(parents=True)
        document.write_text("# 原分诊文档\n保存反馈事实与限制\n", encoding="utf-8")
        document_before = document.read_bytes()
        self.state.update(
            workflow=workflow.WORKFLOW, phase=workflow.PHASE, current_node="feedback:route",
            status="success", blocked=None, error=None, step=None, current_step=None,
            applicable_repositories=["root"], repositories=[{"name": "root", "path": str(self.root)}],
            requirement_registry={"source": {"path": "docs/backlog/backlog.md"}, "requirements": [
                {"id": "BR-001", "status": "completed", "title": "保存材料", "order": 1, "depends_on": []},
            ]},
            feedback={"document_path": document_relative, "document_intent": {
                "branch": branch, "base": base, "versions": {"root": base}, "allowed_paths": [document_relative], "tip": None,
            }},
        )
        (self.run / "feedback").mkdir()
        write_json(self.run / "feedback/input.json", {"source": str(self.base / "original.md"), "content": "原反馈正文",
                                                       "attachments": [], "intent": "本批必须解决保存问题，外部数据须单独授权"})
        input_before = (self.run / "feedback/input.json").read_bytes()
        candidate = triage_report().findings[0].model_dump()
        candidate["mandatory"] = True
        full_triage = json.dumps([{"role": "user", "content": "原核验：保存失败丢失输入，另有权限疑点"},
                                 {"role": "assistant", "content": "保留保存发现，只澄清权限疑点"},
                                 {"role": "user", "content": "补证：权限疑点已撤销，保存问题不变"}], ensure_ascii=False)
        write_json(self.run / "feedback/triage.json", {"phase": workflow.PHASE, "node": "feedback:triage", "status": "success", "data": {
            "report": full_triage, "candidates": [{"id": "F-C001", **candidate}], "limitations": [],
            "document_path": document_relative, "versions": {"root": base},
        }})
        incomplete = routing_report()
        incomplete.ready_to_complete = False
        incomplete.decisions[0].action = "defer"
        incomplete.decisions[0].follow_up = "取得隔离数据授权"
        incomplete.required_inputs = ["提供隔离数据授权"]
        self.parse.side_effect = [incomplete, routing_report(True)]
        self.agent.side_effect = [self.result(text, skill=None) for text in (
            "候选处置已整理，但保存修复仍需外部隔离数据授权", "本批必达，不能延期；准确交接缺少的隔离数据授权",
            "已依据新授权解除限制，采纳保存修复，保留原核验结论",
        )]
        decisions = [
            AgentDecision(verdict="completed", answer="", reason="已整理选择", required_inputs=[]),
            AgentDecision(verdict="blocked", answer="", reason="必达修复缺少不可替代的隔离数据授权", required_inputs=["提供隔离数据授权"]),
            AgentDecision(verdict="completed", answer="", reason="授权已交接，纳入目标已确定", required_inputs=[]),
        ]
        self.decision.side_effect = [(row.model_dump(), 1, row.model_dump_json()) for row in decisions]
        with self.assertRaises(workflow.FeedbackBlocked) as caught:
            await workflow.run_node(self.run, self.state)
        workflow.record_failure(self.run, self.state, caught.exception)
        self.state = read_state(self.run)
        self.assertEqual(self.state["status"], "blocked")
        self.assertEqual(self.state["current_node"], "feedback:route")
        saved_conversation = json.loads((self.run / "conversations/feedback_route.json").read_text())
        self.assertEqual(json.loads(saved_conversation["messages"][-1]["content"])["verdict"], "blocked")
        self.assertEqual(self.agent.await_count, 2)
        self.parse.assert_awaited_once()
        message_file = self.base / "authorization.txt"
        message_file.write_text("隔离数据使用授权已具备，仅限原批次保存修复", encoding="utf-8")
        message = loop.prepare_node_resume_message(
            self.run, self.state, self.state["current_node"], workflow.node_resume_keys(self.state), message_file,
        )
        self.assertEqual(message.target_key, "feedback_route")
        result = await workflow.run_node(self.run, self.state, resume_message=message)
        self.assertTrue(message.consumed)
        self.assertEqual(self.state["current_node"], "feedback:pool")
        self.assertEqual(self.state["status"], "success")
        self.assertIsNone(self.state["blocked"])
        self.assertEqual(result["data"]["decisions"][0]["action"], "include")
        self.assertEqual(result["data"]["required_inputs"], [])
        self.assertIn(message.content, result["data"]["report"])
        self.assertIn("原核验：保存失败丢失输入", self.agent.await_args_list[0].args[0])
        self.assertIn("权限疑点已撤销", self.agent.await_args_list[0].args[0])
        self.assertIn("本批必须解决保存问题", self.agent.await_args_list[0].args[0])
        self.assertEqual(self.agent.await_count, 3)
        self.assertIsNone(self.agent.await_args_list[0].kwargs["resume_session_id"])
        for call in self.agent.await_args_list[1:]:
            self.assertEqual(call.kwargs["resume_session_id"], "feedback-session")
        self.assertTrue(all(call.kwargs["task"] == "feedback_route" for call in self.agent.await_args_list))
        self.assertTrue(all(spec.skill_name is None and spec.task == "feedback_route" for spec in self.specs))
        self.assertEqual(document.read_bytes(), document_before)
        self.assertEqual((self.run / "feedback/input.json").read_bytes(), input_before)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), base)
        self.assertEqual(git(self.root, "branch", "--show-current"), branch)

    async def test_blocked_original_session_receives_resume_message_without_reset(self):
        self.agent.side_effect = [self.result("缺少必要外部授权"), self.result("授权已核实，完成核验")]
        decisions = [AgentDecision(verdict="blocked", answer="", reason="需要外部数据授权", required_inputs=["提供隔离数据授权"]),
                     AgentDecision(verdict="completed", answer="", reason="必要条件已具备", required_inputs=[])]
        self.decision.side_effect = [(value.model_dump(), 1, value.model_dump_json()) for value in decisions]
        with self.assertRaises(workflow.FeedbackBlocked):
            await self.triage()
        self.state = read_state(self.run)
        message = loop.ResumeMessage(target_key="feedback_triage", content="隔离数据授权已具备")
        raw, _ = await self.triage(resume_message=message)
        self.assertTrue(message.consumed)
        self.assertIn("隔离数据授权已具备", raw)
        self.assertIn("缺少必要外部授权", raw)
        self.assertEqual(self.agent.await_args.kwargs["resume_session_id"], "feedback-session")


if __name__ == "__main__":
    unittest.main()
