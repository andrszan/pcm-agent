from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.files import write_json
from common.state import read_state
from quality import workflow as flow
from quality.models import AuditReport, PoolPlan, RoutingReport, validate_audit, validate_pool_plan, validate_routing


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


def audit_report(defect: bool = False, blocked: bool = False) -> AuditReport:
    return AuditReport.model_validate({
        "summary": "已执行主要任务", "applicable": True,
        "coverage": [{"user_task": "保存材料", "outcome": "blocked_by_defect" if blocked else "covered",
                      "reason": "已观察实际结果", "evidence": ["浏览器操作与服务返回"], "blocking_findings": [0] if blocked else []}],
        "findings": [{"title": "保存失败丢失输入", "user_task": "保存材料", "trigger": "服务拒绝保存",
                      "observed": "输入被清空", "expected": "保留输入并重试", "basis": "当前产品承诺",
                      "impact": "用户必须重复录入", "evidence": ["真实操作与持久化查询"], "priority": "high", "confidence": "high"}] if defect else [],
        "duplicates": [], "high_impact": [], "limitations": [],
    })


def route_report(defect: bool = False) -> RoutingReport:
    return RoutingReport.model_validate({"summary": "纳入明确缺陷" if defect else "无尚应处理问题",
        "decisions": [{"candidate_id": "Q001-C001", "action": "include", "reason": "影响主要任务", "covered_by": None}] if defect else [],
        "document_changes": [], "ready_to_complete": not defect})


def pool_plan() -> PoolPlan:
    return PoolPlan.model_validate({"summary": "修复保存", "requirements": [{"requirement_id": "BR-002", "candidate_ids": ["Q001-C001"]}],
                                    "regression_owners": [{"candidate_id": "Q001-C001", "requirement_id": "BR-002"}]})


class QualityWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "products" / "sample"
        (self.root / "docs/backlog").mkdir(parents=True)
        self.backlog = self.root / "docs/backlog/backlog.md"
        self.backlog.write_text("BR-001 当前标题\n")
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "测试")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "add", "docs/backlog/backlog.md")
        git(self.root, "commit", "-m", "docs: 初始需求")
        self.old = {"id": "BR-001", "title": "历史标题", "order": 1, "depends_on": [], "status": "completed", "completion": {"step": 18}}
        self.source = {"status": "success", "phase": "phase_1_requirement_development", "step": 13, "current_step": 13,
                       "current_node": "phase_1:select_requirement", "active_requirement": None, "requirement_cycle": None,
                       "blocked": None, "error": None, "workspace": {"root": str(self.root.parent), "final_path": str(self.root)},
                       "applicable_repositories": ["root"], "repositories": [{"name": "root", "path": str(self.root)}],
                       "requirement_registry": {"schema_version": 1, "source": {"path": "docs/backlog/backlog.md", "sha256": "historical"}, "requirements": [self.old]}}
        self.source_dir = self.base / "runs" / "original"
        self.source_dir.mkdir(parents=True)
        write_json(self.source_dir / "state.json", self.source)
        self.source_bytes = (self.source_dir / "state.json").read_bytes()
        self.run = self.base / "runs" / "quality-test"
        self.run.mkdir()
        self.state = flow.new_state(self.source, "original", self.run.name)
        write_json(self.run / "state.json", self.state)
        self.calls: list[str] = []
        self.defect = False
        self.blocked = False
        self.catalog_override = None

        async def catalog(state):
            _, _, source = flow._backlog(state)
            records = [{"id": "BR-001", "title": "当前标题", "order": 1, "depends_on": []}]
            if "BR-002" in self.backlog.read_text():
                records.append({"id": "BR-002", "title": "修复保存", "order": 2, "depends_on": ["BR-001"]})
            return source, self.catalog_override or records

        async def task(run_dir, state, key, task, prompt, responsibility, **kwargs):
            self.calls.append(key)
            if key == "quality_prepare":
                return "全部任务、开发身份和端口已准备，数据可复位", None
            if key.startswith("quality_audit_"):
                return "已执行审计", audit_report(self.defect, self.blocked)
            if key.startswith("quality_pool_commit_"):
                git(self.root, "add", "docs/backlog/backlog.md")
                git(self.root, "commit", "-m", "docs: 新增修复需求")
                return "已精确提交", None
            if key.startswith("quality_pool_"):
                self.backlog.write_text("BR-001 当前标题\nBR-002 修复保存，依赖 BR-001\n")
                plan = pool_plan()
                await kwargs["validate"](plan)
                return "新增 BR-002，负责原场景回归", plan
            raise AssertionError(key)

        self.addCleanup(patch.stopall)
        patch.object(flow, "_catalog", side_effect=catalog).start()
        patch.object(flow, "_task", side_effect=task).start()
        self.routing = patch.object(flow, "parse_response", side_effect=lambda *a, **kw: route_report(self.defect)).start()
        patch.object(flow.LLMConfig, "load", return_value=object()).start()

    def execute(self):
        return asyncio.run(flow.run_node(self.run, self.state))

    def reach(self, node):
        for _ in range(10):
            if self.state["current_node"] == node:
                return
            self.execute()
        self.fail(f"未到达 {node}")

    def test_route_uses_one_decision_and_no_agent_session(self):
        self.defect = True
        self.reach("quality:route")
        before = self.calls.copy()
        self.execute()
        self.assertEqual(self.calls, before)
        self.routing.assert_awaited_once()
        self.assertEqual(self.state["current_node"], "quality:pool")
        self.assertEqual(flow.node_resume_keys({**self.state, "current_node": "quality:route"}), ())

    def test_route_invalid_candidates_fails_without_agent_loop(self):
        self.reach("quality:route")
        self.routing.side_effect = None
        self.routing.return_value = route_report(True)
        before = self.calls.copy()
        with self.assertRaisesRegex(ValueError, "多出=.*Q001-C001"):
            self.execute()
        self.assertEqual(before, self.calls)
        self.routing.assert_awaited_once()

    def test_route_records_real_external_block_without_false_completion(self):
        self.reach("quality:route")
        self.routing.side_effect = None
        report = route_report()
        report.ready_to_complete = False
        report.required_inputs = ["提供隔离恢复环境及可验证备份"]
        report.summary = "必要恢复任务缺少隔离环境，没有当前可推进修复"
        self.routing.return_value = report
        with self.assertRaises(flow.QualityBlocked) as caught:
            self.execute()
        result = flow.record_failure(self.run, self.state, caught.exception)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.state["current_node"], "quality:route")
        self.routing.return_value = route_report()
        self.execute()
        self.assertEqual(self.state["current_node"], "quality:complete")

    def test_first_prepare_has_a_known_timing_start(self):
        from common.timing import StepTiming
        timer = StepTiming()
        timer.begin_attempt(node="quality:prepare")
        timer.bind_run(self.run, existing=True)
        self.assertIsNotNone(timer.record["started_at"])
        self.assertEqual(timer.record["agent_elapsed_seconds"], 0.0)
        self.assertFalse(flow.is_completed(self.state))

    def test_initial_id_handoff_preserves_history_but_uses_current_title(self):
        self.execute()
        self.assertEqual(self.state["requirement_registry"]["requirements"][0]["title"], "当前标题")
        self.assertEqual(self.state["requirement_registry"]["requirements"][0]["completion"], {"step": 18})
        self.assertNotEqual(self.state["requirement_registry"]["source"]["sha256"], "historical")
        self.assertEqual((self.source_dir / "state.json").read_bytes(), self.source_bytes)
        self.assertEqual(self.source["requirement_registry"]["requirements"][0]["title"], "历史标题")

    def test_unfinished_source_and_unknown_ids_are_rejected(self):
        source = copy.deepcopy(self.source)
        source["requirement_registry"]["requirements"][0]["status"] = "pending"
        with self.assertRaises(RuntimeError):
            flow.new_state(source, "original", "new")
        self.catalog_override = [{"id": "BR-X", "title": "未知", "order": 1, "depends_on": []}]
        with self.assertRaisesRegex(RuntimeError, "正式 ID"):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_dirty_workspace_is_preserved(self):
        extra = self.root / "unknown.png"
        extra.write_bytes(b"keep")
        with self.assertRaisesRegex(RuntimeError, "未提交"):
            self.execute()
        self.assertEqual(extra.read_bytes(), b"keep")
        self.assertEqual(self.calls, [])

    def test_no_findings_completes_without_new_requirements_or_commits(self):
        before = git(self.root, "rev-parse", "HEAD")
        self.reach("quality:completed")
        self.assertTrue(flow.is_completed(self.state))
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), before)
        self.assertEqual(len(self.state["requirement_registry"]["requirements"]), 1)
        calls = self.calls.copy()
        self.execute()
        self.assertEqual(self.calls, calls)
        self.assertEqual((self.source_dir / "state.json").read_bytes(), self.source_bytes)

    def test_pool_register_and_requirement_evidence(self):
        self.defect = self.blocked = True
        self.reach("quality:select_requirement")
        self.assertEqual(git(self.root, "branch", "--show-current"), "main")
        items = self.state["requirement_registry"]["requirements"]
        self.assertEqual([row["status"] for row in items], ["completed", "pending"])
        self.assertIsNone(self.state["step"])
        self.execute()
        self.assertEqual(self.state["step"], 13)
        from steps.step_13_select_requirement.step import run
        run(self.run, self.state)
        evidence = flow.requirement_evidence(self.run, self.state)
        self.assertIn("服务拒绝保存", evidence)
        self.assertIn("BR-002", evidence)
        self.assertEqual(self.state["current_node"], "requirement:14_trd_design")
        self.assertEqual(self.state["requirement_cycle"]["return_node_after_completion"], "quality:select_requirement")

    def test_covered_chain_preserves_all_original_tasks_for_regression(self):
        self.defect = True
        self.reach("quality:select_requirement")
        audit_path = self.run / "quality/rounds/0001/audit.json"
        route_path = self.run / "quality/rounds/0001/route.json"
        audit = json.loads(audit_path.read_text())
        route = json.loads(route_path.read_text())
        for index, title in ((2, "详情页仍丢失输入"), (3, "复测任务无法继续")):
            candidate = copy.deepcopy(audit["data"]["candidates"][0])
            candidate.update(id=f"Q001-C00{index}", title=title, trigger=title)
            audit["data"]["candidates"].append(candidate)
            route["data"]["decisions"].append({"candidate_id": candidate["id"], "action": "covered",
                "reason": "共同障碍", "covered_by": f"Q001-C00{index - 1}"})
        audit["data"]["coverage"].append({"user_task": "安排复测", "outcome": "blocked_by_defect",
            "reason": "复测无法继续", "evidence": ["实际复现"], "blocking_candidates": ["Q001-C003"]})
        write_json(audit_path, audit)
        write_json(route_path, route)
        self.state["active_requirement"] = "BR-002"
        evidence = flow.requirement_evidence(self.run, self.state)
        self.assertIn("详情页仍丢失输入", evidence)
        self.assertIn("复测任务无法继续", evidence)
        self.assertIn("安排复测", evidence)
        self.assertIn('"Q001-C003": "BR-002"', evidence)

    def test_pool_recovers_after_merge_without_repeating_agents(self):
        self.defect = True
        self.reach("quality:pool")
        real_git = flow.git
        failed = False

        def interrupt(path, *args, **kwargs):
            nonlocal failed
            value = real_git(path, *args, **kwargs)
            if args[:2] == ("merge", "--ff-only") and not failed:
                failed = True
                raise RuntimeError("模拟合并后中断")
            return value

        with patch.object(flow, "git", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "模拟"):
                self.execute()
        before = git(self.root, "rev-parse", "HEAD")
        calls = self.calls.copy()
        self.execute()
        self.assertEqual(self.calls, calls)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), before)
        self.assertEqual(self.state["current_node"], "quality:register")
        self.assertNotIn("quality/", git(self.root, "branch", "--list"))

    def test_register_result_state_interruption_keeps_completed_items(self):
        self.defect = True
        self.reach("quality:register")
        with patch.object(flow, "write_state", side_effect=OSError("状态写入中断")):
            with self.assertRaises(OSError):
                self.execute()
        self.state = read_state(self.run)
        self.execute()
        self.assertEqual([row["status"] for row in self.state["requirement_registry"]["requirements"]], ["completed", "pending"])
        self.assertEqual(self.state["quality"]["batch_requirement_ids"], ["BR-002"])

    def test_pool_result_state_interruption_does_not_recommit(self):
        self.defect = True
        self.reach("quality:pool")
        actual = flow.write_state

        def interrupt(run_dir, state):
            if state["current_node"] == "quality:register":
                raise OSError("状态推进中断")
            actual(run_dir, state)

        with patch.object(flow, "write_state", side_effect=interrupt):
            with self.assertRaises(OSError):
                self.execute()
        self.state = read_state(self.run)
        calls = self.calls.copy()
        self.execute()
        self.assertEqual(self.calls, calls)
        self.assertEqual(self.state["current_node"], "quality:register")

    def test_new_round_budget_and_final_reaudit(self):
        self.defect = True
        self.state["quality"]["max_rounds"] = 1
        self.reach("quality:select_requirement")
        for row in self.state["requirement_registry"]["requirements"]:
            row.update(status="completed", completion={"step": 18})
        self.execute()
        self.assertEqual(self.state["quality"]["round"], 2)
        self.assertEqual(self.state["current_node"], "quality:audit")
        with self.assertRaises(flow.IterationLimit) as raised:
            self.execute()
        flow.record_failure(self.run, self.state, raised.exception)
        self.assertFalse(flow.is_completed(self.state))
        self.assertEqual(self.state["error"]["type"], "iteration_limit")
        with self.assertRaises(ValueError):
            flow.increase_round_limit(self.state, 1)
        flow.increase_round_limit(self.state, 2)
        self.defect = False
        self.reach("quality:completed")
        self.assertIn("quality_audit_r0002", self.calls)
        self.assertTrue(flow.is_completed(self.state))

    def test_current_version_must_match_audited_version_at_completion(self):
        self.reach("quality:complete")
        self.backlog.write_text(self.backlog.read_text() + "说明\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "docs: 外部变化")
        with self.assertRaisesRegex(RuntimeError, "未覆盖当前"):
            self.execute()

    def test_result_paths_reject_symbolic_links(self):
        external = self.base / "outside"
        external.mkdir()
        (self.run / "quality").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "符号链接"):
            flow.node_result_path(self.run, self.state)
        self.assertEqual(list(external.iterdir()), [])


class QualityModelTests(unittest.TestCase):
    def test_blocked_tasks_must_point_to_real_finding(self):
        data = audit_report(True, True).model_dump()
        data["coverage"][0]["blocking_findings"] = [9]
        with self.assertRaises(ValueError):
            validate_audit(AuditReport.model_validate(data))

    def test_coverage_gap_is_retained_but_prevents_completion(self):
        data = audit_report().model_dump()
        data["coverage"][0].update(outcome="gap", evidence=[], reason="必要身份缺失")
        parsed = AuditReport.model_validate(data)
        self.assertEqual(parsed.coverage[0].outcome, "gap")
        validate_audit(parsed)
        with self.assertRaisesRegex(ValueError, "不能收口"):
            validate_routing(route_report(), {"candidates": [], "coverage": data["coverage"]}, [])

    def test_gap_with_real_fixes_can_proceed_but_cannot_complete(self):
        data = audit_report(True).model_dump()
        data["coverage"].append({"user_task": "恢复备份", "outcome": "gap", "reason": "缺少隔离环境",
                                 "evidence": [], "blocking_findings": []})
        validate_audit(AuditReport.model_validate(data))
        audit = {"candidates": [{"id": "Q001-C001"}], "coverage": data["coverage"]}
        report = route_report(True)
        report.required_inputs = ["提供隔离恢复环境"]
        validate_routing(report, audit, [])
        report.ready_to_complete = True
        with self.assertRaisesRegex(ValueError, "不能收口"):
            validate_routing(report, audit, [])

    def test_completed_history_cannot_absorb_current_defect(self):
        audit = {"candidates": [{"id": "Q001-C001"}], "coverage": []}
        report = route_report(True)
        report.decisions[0].action = "covered"
        report.decisions[0].covered_by = "BR-001"
        with self.assertRaisesRegex(ValueError, "已完成"):
            validate_routing(report, audit, [{"id": "BR-001", "status": "completed"}])

    def test_uncovered_blocking_task_cannot_be_excluded(self):
        report = route_report(True)
        report.decisions[0].action = "exclude"
        report.ready_to_complete = True
        audit = {"candidates": [{"id": "Q001-C001"}], "coverage": [{"outcome": "blocked_by_defect", "blocking_candidates": ["Q001-C001"]}]}
        with self.assertRaisesRegex(ValueError, "不能排除"):
            validate_routing(report, audit, [])

    def test_pool_requires_total_mapping_and_unique_regression_owner(self):
        plan = pool_plan()
        validate_pool_plan(plan, route_report(True).model_dump(), {"BR-001"})
        plan.regression_owners = []
        with self.assertRaisesRegex(ValueError, "完整回归"):
            validate_pool_plan(plan, route_report(True).model_dump(), {"BR-001"})

    def test_split_finding_requires_owner_dependency(self):
        state = {"requirement_registry": {"requirements": [{"id": "BR-001", "title": "旧", "order": 1, "depends_on": [], "status": "completed"}]}}
        plan = PoolPlan.model_validate({"summary": "拆分", "requirements": [
            {"requirement_id": "BR-002", "candidate_ids": ["C"]}, {"requirement_id": "BR-003", "candidate_ids": ["C"]}],
            "regression_owners": [{"candidate_id": "C", "requirement_id": "BR-003"}]})
        catalog = [{"id": "BR-001", "title": "旧", "order": 1, "depends_on": []},
                   {"id": "BR-002", "title": "实现", "order": 2, "depends_on": []},
                   {"id": "BR-003", "title": "集成", "order": 3, "depends_on": []}]
        with self.assertRaisesRegex(ValueError, "必要依赖"):
            flow._validate_increment(state, catalog, plan)
        catalog[2]["depends_on"] = ["BR-002"]
        flow._validate_increment(state, catalog, plan)


if __name__ == "__main__":
    unittest.main()
