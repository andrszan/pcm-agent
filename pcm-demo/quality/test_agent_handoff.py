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
from quality.models import AuditReport, PoolPlan, RoutingReport


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

    async def test_nonblocking_visual_report_keeps_observations_and_corrections_for_extraction(self) -> None:
        finding = {
            "title": "待办缺少视觉层次", "user_task": "查看待办并处理",
            "trigger": "桌面视口打开工作台与项目详情",
            "observed": "同权重长卡片及重复说明占据主要空间，主要行动不突出",
            "expected": "同等内容与视口下重要事项和主要行动清晰，保留必要说明与全部记录",
            "basis": "工作台用于扫描待办；实际渲染说明识别价值，无量化效率证据",
            "impact": "处理流程可完成，但阅读主次不清",
            "evidence": ["工作台与项目详情截图已读取", "已实际完成处理及返回任务"],
            "priority": "low", "confidence": "high",
        }
        initial = json.dumps(finding, ensure_ascii=False)
        correction = "补充：两个表面使用同一待办组件；撤回所有说明移入 Tooltip 的建议，保留原问题和预期结果"
        self.agent.side_effect = [
            self.result(initial, skill="product-experience-audit"),
            self.result(correction, skill="product-experience-audit"),
        ]
        follow_up = AgentDecision(verdict="continue", answer="只核实共享消费者与必要说明", reason="补齐影响范围", required_inputs=[])
        completed = AgentDecision(verdict="completed", answer="", reason="观察事实和共享影响已交接", required_inputs=[])
        self.decision.side_effect = [(value.model_dump(), 1, value.model_dump_json()) for value in (follow_up, completed)]
        report = AuditReport.model_validate({
            "summary": "任务正常完成，保留有依据的非阻断改善", "applicable": True,
            "coverage": [{"user_task": finding["user_task"], "outcome": "covered", "reason": "处理和返回均成功",
                          "evidence": [finding["evidence"][1]], "blocking_findings": []}],
            "findings": [finding], "duplicates": [], "high_impact": [], "limitations": [],
        })
        self.parse.return_value = report
        raw, parsed = await workflow._task(
            self.run_dir, self.state, "quality_audit_r0001", "quality_audit",
            "检查当前待办任务及代表性共享表面", "交接实际观察与改善价值",
            skill="product-experience-audit", output_model=AuditReport, validate=workflow.validate_audit,
        )
        messages = [message["content"] for message in json.loads(raw)]
        self.assertIn(initial, messages)
        self.assertIn(correction, messages)
        extraction = self.parse.await_args.kwargs["input_model"]
        self.assertEqual(extraction.report, raw)
        self.assertEqual(extraction.context, "检查当前待办任务及代表性共享表面")
        self.assertIs(self.parse.await_args.kwargs["output_model"], AuditReport)
        self.assertEqual(parsed.model_dump(), report.model_dump())
        self.assertEqual(parsed.findings[0].model_dump(), finding)
        self.assertEqual(parsed.coverage[0].blocking_findings, [])
        self.assertEqual(parsed.coverage[0].outcome, "covered")
        self.assertEqual(self.agent.await_count, 2)
        self.parse.assert_awaited_once()

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

    async def test_completion_gap_recovers_through_resume_cli(self) -> None:
        await self.assert_completion_gap_recovers(with_message=False)

    async def test_completion_gap_recovers_through_resume_message_cli(self) -> None:
        await self.assert_completion_gap_recovers(with_message=True)

    async def test_no_included_gap_recovers_through_resume_cli(self) -> None:
        await self.assert_completion_gap_recovers(with_message=False, with_repairs=False)

    async def test_no_included_gap_recovers_through_resume_message_cli(self) -> None:
        await self.assert_completion_gap_recovers(with_message=True, with_repairs=False)

    async def assert_completion_gap_recovers(self, *, with_message: bool, with_repairs: bool = True) -> None:
        import asyncio
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from types import SimpleNamespace

        import run_all
        import run_quality

        self.agent.return_value = self.result("保存缺陷已核验；恢复备份因缺少隔离环境尚未执行", skill="product-experience-audit")
        raw, _ = await workflow._task(
            self.run_dir, self.state, "quality_audit_r0001", "quality_audit",
            "审计保存与恢复备份", "完成可执行调查后交接修复", skill="product-experience-audit",
        )
        self.state.update({
            "run_id": self.run_dir.name,
            "workflow": workflow.WORKFLOW, "phase": workflow.PHASE, "current_node": "quality:complete",
            "status": "success", "step": None, "current_step": None, "active_requirement": None,
            "requirement_cycle": None, "blocked": None, "error": None,
            "quality": {"round": 1, "baseline_requirement_ids": ["BR-001"], "batch_requirement_ids": ["BR-002"]},
            "requirement_registry": {"requirements": [
                {"id": "BR-001", "status": "completed", "completion": {"step": 18}},
                {"id": "BR-002", "status": "completed", "completion": {"step": 18}},
            ]},
        })
        route = {"summary": "修复保存并保留独立恢复缺口", "decisions": [
            {"candidate_id": "C", "action": "include", "reason": "保存失败", "covered_by": None}],
            "document_changes": [], "ready_to_complete": False, "required_inputs": ["隔离恢复环境"]}
        audit = {"report": raw, "versions": {"root": "before"}, "candidates": [{"id": "C"}],
                 "coverage": [
                     {"user_task": "保存", "outcome": "blocked_by_defect", "reason": "保存失败", "blocking_candidates": ["C"]},
                     {"user_task": "恢复备份", "outcome": "gap", "reason": "缺少隔离环境", "blocking_candidates": []},
                 ], "limitations": []}
        plan = {"summary": "保存修复", "requirements": [{"requirement_id": "BR-002", "candidate_ids": ["C"]}],
                "regression_owners": [{"candidate_id": "C", "requirement_id": "BR-002"}]}
        if not with_repairs:
            self.state["current_node"] = "quality:route"
            self.state["quality"]["batch_requirement_ids"] = []
            self.state["requirement_registry"]["requirements"].pop()
            audit["versions"] = {"root": "fixed"}
            audit["coverage"][0].update(outcome="covered", reason="保存可用", blocking_candidates=[])
            route["decisions"][0].update(action="exclude", reason="非阻断偏好")
            self.parse.return_value = RoutingReport.model_validate(route)
        prior_artifacts = (("audit", audit), ("route", route), ("pool", {"plan": plan}), ("register", {"new_ids": ["BR-002"]}))
        for name, data in prior_artifacts if with_repairs else prior_artifacts[:1]:
            workflow._write(self.run_dir / f"quality/rounds/0001/{name}.json", {
                "node": f"quality:{name}", "round": 1, "status": "success", "data": data,
            })
        workflow._write(self.run_dir / "steps/requirements/BR-002/18.json", {
            "status": "success", "requirement_id": "BR-002", "repositories": [{"name": "root", "tip_sha": "fixed"}],
        })
        artifacts = {p: p.read_bytes() for p in (self.run_dir / "quality/rounds/0001").glob("*.json")}
        registry = json.dumps(self.state["requirement_registry"], sort_keys=True)
        workflow._write(self.run_dir / "state.json", self.state)
        blocked = AgentDecision(verdict="blocked", answer="", reason="恢复备份仍缺少隔离环境", required_inputs=["隔离恢复环境"])
        self.decision.return_value = (blocked.model_dump(), 1, blocked.model_dump_json())
        with patch.object(workflow, "main_versions", return_value={"root": "fixed"}), \
             patch.object(workflow, "repositories", return_value=[("root", self.workspace)]), \
             patch.object(workflow, "ancestor", return_value=True), \
             patch.object(run_all, "RUNS_DIR", self.base), \
             patch.object(run_quality, "acquire_execution_locks"), \
             patch.object(run_quality, "attach_product"), \
             patch.object(run_quality, "load_settings", return_value=SimpleNamespace(pcm_max_concurrent_projects=1)), \
             patch.object(run_quality, "load_model_policy", return_value={}), \
             patch.object(run_quality, "_model_policy_snapshot", return_value="test-policy"), \
             patch.object(run_quality, "_model_policy_table", return_value="test-policy"), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            if not with_repairs:
                self.assertEqual(await asyncio.to_thread(run_quality.main, ["--resume", self.run_dir.name, "--node", "quality:route"]), 0)
                self.assertEqual(read_state(self.run_dir)["current_node"], "quality:complete")
                self.parse.assert_awaited_once()
                artifacts = {p: p.read_bytes() for p in (self.run_dir / "quality/rounds/0001").glob("*.json")}
            command = ["--resume", self.run_dir.name, "--node", "quality:complete"]
            self.assertEqual(await asyncio.to_thread(run_quality.main, command), 1)
            self.state = read_state(self.run_dir)
            self.assertEqual(self.state["status"], "blocked")
            self.assertEqual(self.agent.await_count, 2)
            self.assertEqual(workflow.node_resume_keys(self.state), ("quality_audit_r0001",))
            self.assertIn("恢复备份", self.agent.await_args.args[0])
            self.assertIn("隔离恢复环境", self.agent.await_args.args[0])
            self.agent.return_value = self.result("隔离环境已可用，仅补恢复备份：实际恢复与查询结果一致", skill="product-experience-audit")
            completed = AgentDecision(verdict="completed", answer="", reason="独立必要缺口已补证", required_inputs=[])
            self.decision.return_value = (completed.model_dump(), 1, completed.model_dump_json())
            if with_message:
                message = self.base / "resume.txt"
                message.write_text("隔离恢复环境已就绪，请只补恢复备份任务证据", encoding="utf-8")
                command += ["--resume-message-file", str(message)]
            self.assertEqual(await asyncio.to_thread(run_quality.main, command), 0)
        self.state = read_state(self.run_dir)
        self.assertTrue(workflow.is_completed(self.state))
        self.assertEqual(self.agent.await_count, 3)
        followup = self.agent.await_args
        self.assertEqual(followup.kwargs["resume_session_id"], "quality-session")
        if with_message:
            self.assertEqual(followup.args[0], message.read_text())
        self.assertEqual(self.specs[-1].key, "quality_audit_r0001")
        self.assertEqual(registry, json.dumps(self.state["requirement_registry"], sort_keys=True))
        self.assertEqual(artifacts, {p: p.read_bytes() for p in artifacts})
        if not with_repairs:
            self.parse.assert_awaited_once()
            completed_result = json.loads((self.run_dir / "quality/complete.json").read_text())
            self.assertEqual(completed_result["data"]["dispositions"], route["decisions"])

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
