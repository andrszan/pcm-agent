from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from common import agent_decision_loop as loop
from common.claude_agent import ClaudeRunResult
from common.decision import AgentDecision
from common.state import read_state
from model_policy import AgentProfile
from quality import workflow
from quality.models import AuditReport, PoolPlan


class QualityAgentHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.run_dir = self.base / "run"
        self.workspace = self.base / "product"
        self.run_dir.mkdir()
        self.workspace.mkdir()
        self.state = {"workspace": {"root": str(self.base), "final_path": str(self.workspace)}}
        self.agent = AsyncMock()
        completed = AgentDecision(verdict="completed", answer="", reason="任务完成", required_inputs=[])
        self.decision = AsyncMock(return_value=(completed.model_dump(), 1, completed.model_dump_json()))
        self.parse = AsyncMock()
        self.specs = []

        async def real_loop(*args, **kwargs):
            self.specs.append(args[3])
            return await loop.run_agent_decision_loop(
                *args, **kwargs, agent_runner=self.agent, decision_runner=self.decision,
                config_loader=lambda: object(),
            )

        for patcher in (
            patch.object(workflow, "run_agent_decision_loop", side_effect=real_loop),
            patch.object(workflow, "parse_response", self.parse),
            patch.object(workflow.LLMConfig, "load", return_value=object()),
            patch.object(loop, "get_agent_profile", return_value=AgentProfile("planning", "test-model", "high")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def result(self, text: str, *, skill: str | None = None) -> ClaudeRunResult:
        return ClaudeRunResult(
            init={"cwd": str(self.workspace), "skills": [skill] if skill else [],
                  "slash_commands": [skill] if skill else []},
            text=text, result_subtype="success", is_error=False, session_id="quality-session",
            stop_reason=None, num_turns=1, total_cost_usd=0, exception=None,
        )

    async def audit(self):
        return await workflow._task(
            self.run_dir, self.state, "quality_audit_r0001", "quality_audit",
            "当前用户任务及运行边界", "核验用户任务并交接观察结果",
            skill="product-experience-audit", output_model=AuditReport,
        )

    def report(self) -> AuditReport:
        return AuditReport.model_validate({
            "summary": "保存任务已检查", "applicable": True,
            "coverage": [{"user_task": "保存", "outcome": "covered", "reason": "结果符合承诺",
                          "evidence": ["保存操作结果"], "blocking_findings": []}],
            "findings": [], "duplicates": [], "high_impact": [], "limitations": [],
        })

    async def test_incremental_reply_keeps_full_audit_and_corrections(self) -> None:
        self.agent.side_effect = [
            self.result("完整审计：保存失败丢失输入；另有权限误判待核实", skill="product-experience-audit"),
            self.result("补充：运行版本已核对；撤销权限误判，其余发现不变", skill="product-experience-audit"),
        ]
        follow_up = AgentDecision(verdict="continue", answer="只补运行版本并核实权限误判", reason="补证", required_inputs=[])
        completed = AgentDecision(verdict="completed", answer="", reason="完整审计及补证已交接", required_inputs=[])
        self.decision.side_effect = [
            (value.model_dump(), 1, value.model_dump_json()) for value in (follow_up, completed)
        ]
        self.parse.return_value = self.report()
        raw, _ = await self.audit()
        extracted = self.parse.await_args.kwargs["input_model"].report
        for text in ("保存失败丢失输入", "撤销权限误判", "只补运行版本并核实权限误判"):
            self.assertIn(text, extracted)
            self.assertIn(text, raw)
        self.assertEqual(self.agent.await_count, 2)
        self.assertEqual(self.parse.await_count, 1)

    async def test_plain_task_completes_without_skill_and_returns_saved_reply(self) -> None:
        self.agent.return_value = self.result("准备完成\n保留完整交接")
        raw, parsed = await workflow._task(
            self.run_dir, self.state, "quality_prepare", "quality_prepare",
            "准备审计条件", "交接可访问运行条件",
        )
        self.assertIn("准备完成\n保留完整交接", [m["content"] for m in json.loads(raw)])
        self.assertIsNone(parsed)
        self.assertIsNone(self.specs[0].skill_name)
        self.assertEqual(loop.agent_conversation_report(self.run_dir, self.state, self.specs[0]), raw)
        self.agent.assert_awaited_once()
        self.decision.assert_awaited_once()
        self.parse.assert_not_awaited()

    async def test_conversation_report_is_read_only(self) -> None:
        self.agent.return_value = self.result("准备完成")
        await workflow._task(self.run_dir, self.state, "quality_prepare", "quality_prepare", "准备", "交接")
        before = {p.relative_to(self.run_dir): p.read_bytes() for p in self.run_dir.rglob("*.json")}
        state_before = json.dumps(self.state, sort_keys=True)
        loop.agent_conversation_report(self.run_dir, self.state, self.specs[0])
        self.assertEqual(state_before, json.dumps(self.state, sort_keys=True))
        self.assertEqual(before, {p.relative_to(self.run_dir): p.read_bytes() for p in self.run_dir.rglob("*.json")})

    async def test_audit_requires_loaded_skill_before_decision_and_extraction(self) -> None:
        self.agent.return_value = self.result("审计回复但未加载 Skill")
        with self.assertRaises(loop.AgentExecutionFailure):
            await self.audit()
        self.decision.assert_not_awaited()
        self.parse.assert_not_awaited()

    async def test_extraction_failure_resumes_completed_audit_without_rerunning_agent(self) -> None:
        original = "审计完整原文\n保存任务证据与限制"
        self.agent.return_value = self.result(original, skill="product-experience-audit")
        self.parse.side_effect = [RuntimeError("结构提取服务暂不可用"), self.report()]
        with self.assertRaises(RuntimeError):
            await self.audit()
        self.state = read_state(self.run_dir)
        raw, parsed = await self.audit()
        self.assertIn(original, [m["content"] for m in json.loads(raw)])
        self.assertEqual(parsed, self.report())
        self.agent.assert_awaited_once()
        self.decision.assert_awaited_once()
        self.assertEqual(self.parse.await_count, 2)
        for call in self.parse.await_args_list:
            self.assertEqual(call.kwargs["input_model"].report, raw)
            self.assertEqual(call.kwargs["input_model"].context, "当前用户任务及运行边界")
            self.assertIs(call.kwargs["output_model"], AuditReport)
        self.assertEqual(loop.latest_agent_reply(self.run_dir, self.state, self.specs[-1]), original)

    async def test_async_pool_validation_repairs_missing_owner_dependency_in_same_session(self) -> None:
        self.state["requirement_registry"] = {"requirements": []}
        catalog = [
            {"id": "BR-001", "title": "接口修复", "order": 1, "depends_on": []},
            {"id": "BR-002", "title": "完整场景回归", "order": 2, "depends_on": []},
        ]
        plan = PoolPlan.model_validate({
            "summary": "同一候选由两个需求承接",
            "requirements": [
                {"requirement_id": "BR-001", "candidate_ids": ["Q001-C001"]},
                {"requirement_id": "BR-002", "candidate_ids": ["Q001-C001"]},
            ],
            "regression_owners": [{"candidate_id": "Q001-C001", "requirement_id": "BR-002"}],
        })
        load_catalog = AsyncMock(return_value=catalog)
        failed_validation = []

        async def validate(report):
            current = await load_catalog()
            try:
                workflow._validate_increment(self.state, current, report)
            except ValueError as error:
                failed_validation.append(error)
                raise

        async def agent(prompt, **kwargs):
            if kwargs.get("resume_session_id") is not None:
                catalog[1]["depends_on"] = ["BR-001"]
                return self.result("已补齐回归依赖", skill="requirement-breakdown")
            return self.result("入池方案已形成", skill="requirement-breakdown")

        self.agent.side_effect = agent
        self.parse.return_value = plan
        raw, parsed = await workflow._task(
            self.run_dir, self.state, "quality_pool_r0001", "quality_pool",
            "把候选拆分并指定完整场景回归归属", "形成入池方案与必要依赖",
            skill="requirement-breakdown", output_model=PoolPlan, validate=validate,
        )
        self.assertEqual(len(failed_validation), 1)
        self.assertEqual(load_catalog.await_count, 2)
        self.assertEqual(self.agent.await_count, 2)
        self.assertEqual(self.decision.await_count, 2)
        self.assertEqual(self.parse.await_count, 2)
        first, repaired = self.agent.await_args_list
        self.assertIsNone(first.kwargs.get("resume_session_id"))
        self.assertEqual(repaired.kwargs["resume_session_id"], "quality-session")
        self.assertEqual(self.state["claude_sessions"], {"quality_pool_r0001": "quality-session"})
        self.assertIn("已补齐回归依赖", raw)
        self.assertEqual(parsed, plan)
        self.assertEqual(catalog[1]["depends_on"], ["BR-001"])
        workflow._validate_increment(self.state, catalog, parsed)

    async def test_structural_gap_returns_to_original_session_and_extracts_repaired_reply(self) -> None:
        self.agent.side_effect = [
            self.result("首次审计回复", skill="product-experience-audit"),
            self.result("补齐证据后的审计回复", skill="product-experience-audit"),
        ]
        self.parse.side_effect = [ValueError("保存任务缺少观察证据"), self.report()]
        raw, parsed = await self.audit()
        self.assertIn("首次审计回复", raw)
        self.assertIn("补齐证据后的审计回复", raw)
        self.assertEqual(parsed, self.report())
        self.assertEqual(self.agent.await_count, 2)
        self.assertEqual(self.decision.await_count, 2)
        first, repaired = self.agent.await_args_list
        self.assertIsNone(first.kwargs.get("resume_session_id"))
        self.assertEqual(repaired.kwargs["resume_session_id"], "quality-session")
        self.assertNotEqual(first.args[0], repaired.args[0])
        self.assertIn("首次审计回复", self.parse.await_args_list[0].kwargs["input_model"].report)
        self.assertEqual(self.parse.await_args_list[1].kwargs["input_model"].report, raw)
        self.assertEqual(self.state["claude_sessions"], {"quality_audit_r0001": "quality-session"})


if __name__ == "__main__":
    unittest.main()
