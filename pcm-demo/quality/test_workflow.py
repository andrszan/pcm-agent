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
        self.execute()
        self.assertEqual(self.state["current_node"], "quality:complete")
        route_path = self.run / "quality/rounds/0001/route.json"
        route_bytes = route_path.read_bytes()
        with self.assertRaises(flow.QualityBlocked) as caught:
            self.execute()
        result = flow.record_failure(self.run, self.state, caught.exception)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.state["current_node"], "quality:complete")
        self.assertFalse(flow.is_completed(self.state))
        self.assertEqual(route_path.read_bytes(), route_bytes)
        self.routing.assert_awaited_once()

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

    def test_nonblocking_visual_findings_reach_pool_and_regression_owner(self):
        report = audit_report()
        data = report.model_dump()
        data["coverage"] = [{
            "user_task": "扫描待办并进入处理", "outcome": "covered",
            "reason": "工作台和项目详情的任务入口均可正常使用",
            "evidence": ["桌面视口实际操作与截图"], "blocking_findings": [],
        }]
        data["findings"] = [{
            "title": f"{surface}待办主次不清", "user_task": "扫描待办并进入处理",
            "trigger": f"桌面视口在{surface}查看真实待办列表",
            "observed": f"{surface}以同权重长卡片呈现待办，重复元信息占据主要空间",
            "expected": "同等内容与视口下能辨认重要事项和下一步，保留必要事实与全部记录",
            "basis": "当前产品工作台用于扫描待办；实际渲染支持层次改善，不依赖用户研究",
            "impact": "任务可完成，但事项与主要行动难以扫描识别",
            "evidence": [f"{surface}桌面截图已读取", "进入、处理和返回列表均成功"],
            "priority": "low", "confidence": "high",
        } for surface in ("工作台", "项目详情", "团队待办")]
        report = AuditReport.model_validate(data)
        validate_audit(report)
        route = route_report(True)
        route.decisions[0].reason = "已有渲染事实与产品价值，复用共享样式即可改善，纳入当前范围"
        routed = route.model_dump()
        routed["decisions"].extend({
            "candidate_id": f"Q001-C00{index}", "action": "covered",
            "reason": "共享待办展示模式，合并改善但保留相关表面回归",
            "covered_by": f"Q001-C00{index - 1}",
        } for index in (2, 3))
        self.routing.side_effect = None
        self.routing.return_value = RoutingReport.model_validate(routed)
        with patch(f"{__name__}.audit_report", return_value=report):
            self.reach("quality:select_requirement")

        audit = flow._prior(self.run, self.state, "audit")
        candidates = [{"id": f"Q001-C{index:03d}", **finding}
                      for index, finding in enumerate(data["findings"], 1)]
        self.assertEqual(audit["candidates"], candidates)
        self.assertEqual(audit["coverage"][0]["outcome"], "covered")
        self.assertEqual(audit["coverage"][0]["blocking_candidates"], [])
        route_input = self.routing.await_args.kwargs["input_model"]
        self.assertEqual(route_input.report, audit["report"])
        self.assertEqual(json.loads(route_input.context)["审计"]["candidates"], candidates)
        pool_call = next(call for call in flow._task.call_args_list if call.args[2] == "quality_pool_r0001")
        pool_input = json.loads(pool_call.args[4].split("\n", 2)[2])
        self.assertEqual(pool_input["审计"], audit)
        self.assertEqual(pool_input["分流"]["decisions"], routed["decisions"])
        pooled = flow._prior(self.run, self.state, "pool")
        self.assertEqual(pooled["plan"]["requirements"], [
            {"requirement_id": "BR-002", "candidate_ids": ["Q001-C001"]},
        ])
        self.assertEqual(pooled["plan"]["regression_owners"], [
            {"candidate_id": "Q001-C001", "requirement_id": "BR-002"},
        ])
        self.execute()
        from steps.step_13_select_requirement.step import run
        run(self.run, self.state)
        evidence = json.loads(flow.requirement_evidence(self.run, self.state).split("\n", 1)[1])
        self.assertEqual(evidence["原发现"], candidates)
        self.assertEqual(evidence["受阻任务"], [])
        self.assertEqual(evidence["完整回归归属"], {candidate["id"]: "BR-002" for candidate in candidates})
        self.assertEqual(self.state["current_node"], "requirement:14_trd_design")

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

    def finish_repair_batch(self):
        self.defect = True
        self.reach("quality:select_requirement")
        (self.root / "fix.txt").write_text("修复结果")
        git(self.root, "add", "fix.txt")
        git(self.root, "commit", "-m", "fix: 修复任务")
        for row in self.state["requirement_registry"]["requirements"]:
            row.update(status="completed", completion={"step": 18})
        (self.run / "steps/requirements/BR-002").mkdir(parents=True)
        write_json(self.run / "steps/requirements/BR-002/18.json", {
            "status": "success", "requirement_id": "BR-002",
            "repositories": [{"name": "root", "tip_sha": git(self.root, "rev-parse", "HEAD")}],
        })

    def test_repaired_batch_completes_after_one_audit(self):
        self.finish_repair_batch()
        self.reach("quality:completed")
        self.assertEqual([key for key in self.calls if key.startswith("quality_audit_")], ["quality_audit_r0001"])
        self.assertNotIn("max_rounds", self.state["quality"])
        self.assertTrue(flow.is_completed(self.state))

    def test_repaired_batch_does_not_swallow_independent_gap(self):
        self.finish_repair_batch()
        path = self.run / "quality/rounds/0001/audit.json"
        audit = json.loads(path.read_text())
        audit["data"]["coverage"].append({
            "user_task": "恢复备份", "outcome": "gap", "reason": "必要恢复证据未交接",
            "evidence": [], "blocking_candidates": [],
        })
        write_json(path, audit)
        self.reach("quality:complete")
        with self.assertRaisesRegex(RuntimeError, "恢复备份") as caught:
            self.execute()
        result = flow.record_failure(self.run, self.state, caught.exception)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(flow.is_completed(self.state))

    def assert_repaired_batch_retains_external_inputs(self, *, has_gap):
        self.finish_repair_batch()
        path = self.run / "quality/rounds/0001/route.json"
        route = json.loads(path.read_text())
        route["data"]["required_inputs"] = ["提供隔离恢复环境及可验证备份"]
        write_json(path, route)
        if has_gap:
            audit_path = self.run / "quality/rounds/0001/audit.json"
            audit = json.loads(audit_path.read_text())
            audit["data"]["coverage"].append({
                "user_task": "恢复备份", "outcome": "gap", "reason": "缺少隔离恢复环境",
                "evidence": [], "blocking_candidates": [],
            })
            write_json(audit_path, audit)
        self.reach("quality:complete")
        with self.assertRaises(flow.QualityBlocked) as caught:
            self.execute()
        result = flow.record_failure(self.run, self.state, caught.exception)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"]["required_inputs"], route["data"]["required_inputs"])
        self.assertFalse(flow.is_completed(self.state))

    def test_repaired_batch_retains_external_inputs_with_gap(self):
        self.assert_repaired_batch_retains_external_inputs(has_gap=True)

    def test_repaired_batch_retains_external_inputs_without_gap(self):
        self.assert_repaired_batch_retains_external_inputs(has_gap=False)

    def test_repaired_defect_blocked_tasks_trust_completed_regression_owner(self):
        self.blocked = True
        self.finish_repair_batch()
        self.reach("quality:completed")
        self.assertTrue(flow.is_completed(self.state))
        self.assertEqual([key for key in self.calls if key.startswith("quality_audit_")], ["quality_audit_r0001"])

    def test_later_batches_handoff_structured_dispositions_without_conversation_wrappers(self):
        self.defect = True
        previous = route_report(True)
        previous.decisions[0].action = "exclude"
        previous.decisions[0].reason = "此现象只发生于明确范围外的离线模式；联网前提成立时无需新增能力"
        previous.ready_to_complete = True
        self.routing.side_effect = None
        self.routing.return_value = previous
        self.reach("quality:completed")
        # 原对话不进入后续批次；候选、决定及其前提仍须可直接读取。
        for name in ("audit", "route"):
            path = self.run / f"quality/rounds/0001/{name}.json"
            value = json.loads(path.read_text())
            value["data"]["report"] = "不应递归传递的旧 system/conversation 包装"
            write_json(path, value)
        original = self.run
        original_state = copy.deepcopy(self.state)
        source_before = {p.relative_to(original): p.read_bytes() for p in original.rglob("*.json")}
        task_mock = flow._task
        for index in range(2):
            self.defect = False
            self.routing.return_value = route_report()
            source_id = self.run.name
            self.run = self.base / "runs" / f"later-{index}"
            self.run.mkdir()
            self.state = flow.new_state(self.state, source_id, self.run.name)
            self.reach("quality:route")
            audit_call = next(call for call in reversed(task_mock.call_args_list) if call.args[3] == "quality_audit")
            self.execute()
            for context in (audit_call.args[4], self.routing.await_args.kwargs["input_model"].context):
                self.assertIn(previous.decisions[0].reason, context)
                self.assertIn("保存失败丢失输入", context)
                self.assertIn(original.name, context)
                self.assertNotIn("不应递归传递的旧 system/conversation 包装", context)
            self.reach("quality:completed")
        self.assertEqual(source_before, {p.relative_to(original): p.read_bytes() for p in original.rglob("*.json")})
        self.assertEqual(original_state, read_state(original))

    def test_history_rejects_unsafe_cyclic_and_symlinked_sources(self):
        for source_id in ("../original", self.run.name):
            with self.subTest(source_id=source_id), self.assertRaisesRegex(RuntimeError, "来源运行标识"):
                flow._history(self.run, {**self.state, "source_run_id": source_id})
        linked = self.run.parent / "linked-source"
        linked.symlink_to(self.source_dir, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "符号链接"):
            flow._history(self.run, {**self.state, "source_run_id": linked.name})
        self.assertEqual((self.source_dir / "state.json").read_bytes(), self.source_bytes)

    def test_historical_exclusion_does_not_veto_new_evidence(self):
        self.defect = True
        previous = route_report(True)
        previous.decisions[0].action = "exclude"
        previous.decisions[0].reason = "离线场景不在当前承诺内"
        previous.ready_to_complete = True
        self.routing.side_effect = None
        self.routing.return_value = previous
        self.reach("quality:completed")
        source_id = self.run.name
        self.run = self.base / "runs" / "new-evidence"
        self.run.mkdir()
        self.state = flow.new_state(self.state, source_id, self.run.name)
        revised = route_report(True)
        revised.decisions[0].reason = "新增证据：联网正常时同样丢失输入，原排除前提不成立"
        self.routing.return_value = revised
        self.reach("quality:pool")
        route = flow._prior(self.run, self.state, "route")
        self.assertEqual(route["decisions"], revised.model_dump()["decisions"])

    def test_repair_completion_rejects_missing_merge_result(self):
        self.finish_repair_batch()
        (self.run / "steps/requirements/BR-002/18.json").unlink()
        self.reach("quality:complete")
        with self.assertRaises(RuntimeError):
            self.execute()

    def test_repair_completion_rejects_unknown_version(self):
        self.finish_repair_batch()
        (self.root / "other.txt").write_text("外部变更")
        git(self.root, "add", "other.txt")
        git(self.root, "commit", "-m", "docs: 外部变化")
        self.reach("quality:complete")
        with self.assertRaisesRegex(RuntimeError, "版本"):
            self.execute()

    def test_completion_resume_does_not_restart_audit(self):
        self.finish_repair_batch()
        self.reach("quality:complete")
        with patch.object(flow, "_replace_state", side_effect=OSError("状态写入中断")):
            with self.assertRaises(OSError):
                self.execute()
        self.state = read_state(self.run)
        before = self.calls.copy()
        self.execute()
        self.assertTrue(flow.is_completed(self.state))
        self.assertEqual(before, self.calls)

    def test_pending_repair_cannot_complete(self):
        self.defect = True
        self.reach("quality:select_requirement")
        with self.assertRaisesRegex(RuntimeError, "未完成"):
            flow._complete(self.run, self.state)

    def test_current_version_must_match_audited_version_at_completion(self):
        self.reach("quality:complete")
        self.backlog.write_text(self.backlog.read_text() + "说明\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "docs: 外部变化")
        with self.assertRaisesRegex(RuntimeError, "未覆盖当前"):
            self.execute()

    def enable_remote(self):
        self.state["remote_sync"] = {
            "enabled": True, "project_name": "sample", "repositories": {
                "root": {"url": "git@gitlab.com:baiyiyu/andrszan/pcm-projects/sample/sample.git", "project_id": 1},
            },
        }

    def test_remote_contract_is_inherited_without_upstream_completion(self):
        self.reach("quality:completed")
        self.enable_remote()
        source = copy.deepcopy(self.state)
        source["phase_one_completion"] = {"push": "upstream-receipt"}
        with patch.object(flow, "sync_repositories") as sync:
            child = flow.new_state(source, self.run.name, "next-quality")
        self.assertEqual(child["remote_sync"], source["remote_sync"])
        child["remote_sync"]["repositories"]["root"]["project_id"] = 99
        self.assertEqual(source["remote_sync"]["repositories"]["root"]["project_id"], 1)
        self.assertNotIn("phase_one_completion", child)
        self.assertEqual(child["quality"]["batch_requirement_ids"], [])
        sync.assert_not_called()
        self.assertNotIn("remote_sync", flow.new_state(self.source, "original", "legacy"))

    def test_new_phase_one_source_requires_terminal_success_and_inherits_remote_identity(self):
        self.enable_remote()
        source = {**copy.deepcopy(self.source), "remote_sync": copy.deepcopy(self.state["remote_sync"])}
        with self.assertRaises(RuntimeError):
            flow.new_state(source, "original", "next-quality")
        source.update(current_node="phase_1:completed", step=None, current_step=None)
        child = flow.new_state(source, "original", "next-quality")
        self.assertEqual(child["remote_sync"], source["remote_sync"])
        child["remote_sync"]["repositories"]["root"]["project_id"] = 99
        self.assertEqual(source["remote_sync"]["repositories"]["root"]["project_id"], 1)

    def test_legacy_completion_does_not_push_or_create_remote_results(self):
        with patch.object(flow, "sync_repositories") as sync:
            self.reach("quality:completed")
        sync.assert_not_called()
        self.assertFalse((self.run / "quality/push.json").exists())
        self.assertFalse((self.run / "quality/local-completion.json").exists())

    def check_remote_completion(self, *, repair):
        self.enable_remote()
        if repair:
            self.finish_repair_batch()
        self.reach("quality:complete")
        versions = flow.main_versions(self.state)
        registry = copy.deepcopy(self.state["requirement_registry"])
        calls = self.calls.copy()
        with patch.object(flow, "sync_repositories", return_value=[]) as sync:
            self.execute()
        sync.assert_called_once_with(self.run, self.state, self.run / "quality/push.json", targets=versions)
        self.assertTrue(flow.is_completed(self.state))
        self.assertEqual(self.state["requirement_registry"], registry)
        self.assertEqual(self.calls, calls)

    def test_remote_completion_with_repairs(self):
        self.check_remote_completion(repair=True)

    def test_remote_completion_without_repairs(self):
        self.check_remote_completion(repair=False)

    def test_remote_failure_reuses_successful_coverage_repair_and_targets(self):
        self.enable_remote()
        self.finish_repair_batch()
        path = self.run / "quality/rounds/0001/audit.json"
        audit = json.loads(path.read_text())
        audit["data"]["coverage"].append({"user_task": "恢复备份", "outcome": "gap",
            "reason": "必要恢复证据未交接", "evidence": [], "blocking_candidates": []})
        write_json(path, audit)
        self.reach("quality:complete")
        registry = copy.deepcopy(self.state["requirement_registry"])
        versions = flow.main_versions(self.state)
        with patch.object(flow, "_task", return_value=("已补齐恢复备份证据", None)) as task, \
             patch.object(flow, "sync_repositories", side_effect=RuntimeError("root 网络失败")) as sync:
            with self.assertRaises(RuntimeError) as caught:
                self.execute()
            result = flow.record_failure(self.run, self.state, caught.exception)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(flow.is_completed(self.state))
            self.assertEqual(self.state["current_node"], "quality:complete")
            task.assert_awaited_once()
            sync.assert_called_once()
        self.state = read_state(self.run)
        with patch.object(flow, "_task", side_effect=AssertionError("不能重跑补证")), \
             patch.object(flow, "_local_completion", side_effect=AssertionError("应复用本地成功结果")), \
             patch.object(flow, "sync_repositories", return_value=[]) as sync:
            self.execute()
        sync.assert_called_once_with(self.run, self.state, self.run / "quality/push.json", targets=versions)
        self.assertTrue(flow.is_completed(self.state))
        self.assertEqual(self.state["requirement_registry"], registry)

    def test_remote_authentication_failure_is_blocked_and_recoverable(self):
        self.enable_remote()
        self.reach("quality:complete")
        with patch.object(flow, "sync_repositories", side_effect=flow.RemoteBlocked("root 缺少 SSH 写权限")):
            with self.assertRaises(flow.RemoteBlocked) as caught:
                self.execute()
        result = flow.record_failure(self.run, self.state, caught.exception)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["blocked"]["required_inputs"])
        self.assertIsNone(result["error"])
        with patch.object(flow, "sync_repositories", return_value=[]):
            self.execute()
        self.assertTrue(flow.is_completed(self.state))

    def test_remote_success_result_recovers_without_another_push(self):
        self.enable_remote()
        self.reach("quality:complete")
        with patch.object(flow, "sync_repositories", return_value=[]) as sync, \
             patch.object(flow, "_advance", side_effect=OSError("推进中断")):
            with self.assertRaises(OSError):
                self.execute()
        sync.assert_called_once()
        self.state = read_state(self.run)
        with patch.object(flow, "sync_repositories") as sync:
            self.execute()
            self.execute()
        sync.assert_not_called()
        self.assertTrue(flow.is_completed(self.state))

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
