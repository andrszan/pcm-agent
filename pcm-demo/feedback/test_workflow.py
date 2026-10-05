from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.files import write_json
from common.state import read_state
from feedback import workflow as flow
from feedback.models import PoolPlan, RoutingReport, TriageReport
from quality.test_workflow import git


def save_conversation(run, state, key, messages, initial="本批初始任务"):
    path = f"conversations/{key}.json"
    (run / "conversations").mkdir(exist_ok=True)
    write_json(run / path, {"messages": [
        {"role": "system", "content": "本批负责人职责：" + initial},
        {"role": "assistant", "content": initial}, *messages,
    ]})
    state.setdefault("decision_conversations", {})[key] = {"path": path}
    write_json(run / "state.json", state)


def triage_report() -> TriageReport:
    return TriageReport.model_validate({"summary": "已核验保存反馈", "findings": [{
        "title": "保存时保留输入", "kind": "defect", "user_task": "保存材料", "trigger": "保存被拒绝",
        "observed": "已观察当前输入状态", "expected": "保存失败保留输入", "basis": "当前产品承诺",
        "impact": "避免重复录入", "evidence": ["真实操作结果"], "sources": ["反馈第一段"],
        "conclusion": "verified", "mandatory": False,
    }], "limitations": ["只核验提供的反馈"]})


def routing_report(include: bool = False) -> RoutingReport:
    return RoutingReport.model_validate({"summary": "纳入保存修复" if include else "保留本批核验结果", "decisions": [{
        "candidate_id": "F-C001", "action": "include" if include else "satisfied",
        "reason": "保存结果已核验", "covered_by": None,
    }], "document_changes": [], "ready_to_complete": not include})


def pool_plan() -> PoolPlan:
    return PoolPlan.model_validate({"summary": "修复保存结果", "requirements": [
        {"requirement_id": "BR-002", "candidate_ids": ["F-C001"]},
    ], "regression_owners": [{"candidate_id": "F-C001", "requirement_id": "BR-002"}]})


class FeedbackWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "products/sample"
        (self.root / "docs/backlog").mkdir(parents=True)
        self.backlog = self.root / "docs/backlog/backlog.md"
        self.backlog.write_text("BR-001 当前标题\n")
        (self.root / ".gitignore").write_text("backend/\n")
        git(self.root, "init", "-b", "main")
        self.setup_git(self.root)
        git(self.root, "add", "docs/backlog/backlog.md", ".gitignore")
        git(self.root, "commit", "-m", "docs: 初始化")
        self.backend = self.root / "backend"
        self.backend.mkdir()
        git(self.backend, "init", "-b", "main")
        self.setup_git(self.backend)
        (self.backend / "app.py").write_text("print('保存')\n")
        git(self.backend, "add", "app.py")
        git(self.backend, "commit", "-m", "feat: 初始化")
        self.source = {
            "workflow": "product_quality", "phase": "product_quality_iteration", "current_node": "quality:completed",
            "status": "success", "blocked": None, "error": None, "step": None, "current_step": None,
            "active_requirement": None, "requirement_cycle": None,
            "workspace": {"root": str(self.root.parent), "final_path": str(self.root)},
            "applicable_repositories": ["root", "backend"],
            "repositories": [{"name": "root", "path": str(self.root)}, {"name": "backend", "path": str(self.backend)}],
            "requirement_registry": {"schema_version": 1, "source": {"path": "docs/backlog/backlog.md", "sha256": "old"},
                "requirements": [{"id": "BR-001", "title": "历史标题", "order": 1, "depends_on": [],
                                  "status": "completed", "completion": {"step": 18}}]},
        }
        self.source_dir = self.base / "runs/quality"
        self.source_dir.mkdir(parents=True)
        write_json(self.source_dir / "state.json", self.source)
        self.source_bytes = (self.source_dir / "state.json").read_bytes()
        self.run = self.base / "runs/feedback-test"
        self.run.mkdir()
        self.original = self.base / "original.txt"
        self.original.write_text("  保存反馈原文\n")
        self.state = flow.new_state(self.source, "quality", self.run.name)
        (self.run / "feedback").mkdir()
        write_json(self.run / "feedback/input.json", {"source": str(self.original), "content": self.original.read_text(), "attachments": [], "intent": "核验保存"})
        write_json(self.run / "state.json", self.state)
        self.calls = []
        self.include = False
        self.triage = triage_report()
        self.routing = None
        self.catalog_override = None

        async def catalog(state):
            records = [{"id": "BR-001", "title": "当前标题", "order": 1, "depends_on": []}]
            if "BR-002" in self.backlog.read_text():
                records.append({"id": "BR-002", "title": "修复保存", "order": 2, "depends_on": ["BR-001"]})
            return flow._backlog(state)[2], self.catalog_override or records

        async def task(run_dir, state, key, task, prompt, responsibility, **kwargs):
            self.calls.append((key, task, kwargs.get("skill")))
            if key == "feedback_prepare":
                return "既有入口、端口与授权数据可访问", None
            if key == "feedback_triage":
                document = self.root / state["feedback"]["document_path"]
                document.parent.mkdir(parents=True, exist_ok=True)
                document.write_text("# 反馈核验\n" + self.triage.summary + "\n")
                return "完整分诊对话：保存反馈已核验", self.triage
            if key == "feedback_route":
                report = self.routing or routing_report(self.include)
                kwargs["validate"](report)
                return "完整分流对话与负责人决定", report
            if key == "feedback_pool":
                self.backlog.write_text("BR-001 当前标题\nBR-002 修复保存，依赖 BR-001\n")
                plan = pool_plan()
                await kwargs["validate"](plan)
                return "BR-002承接完整保存场景", plan
            if key == "feedback_document":
                document = self.root / state["feedback"]["document_path"]
                routed = flow._prior(run_dir, "route")
                document.write_text(document.read_text() + "\n本批处置：" + routed["summary"] + "\n")
                return "既定处置已写回", None
            if key == "feedback_commit":
                from quality.git import changed_paths
                paths = sorted(changed_paths(self.root, "HEAD"))
                git(self.root, "add", "--", *paths)
                git(self.root, "commit", "-m", "docs: 反馈处理")
                return "已精确提交", None
            if task in flow.DESIGN_TASKS:
                for row in self.routing.document_changes:
                    if row.task == task:
                        path = self.root / row.path
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("# 已授权的局部设计调整\n")
                return "局部调整完成", None
            raise AssertionError(key)

        async def recorded_task(*args, **kwargs):
            raw, parsed = await task(*args, **kwargs)
            save_conversation(args[0], args[1], args[2], [{"role": "user", "content": raw}], args[4])
            return raw, parsed

        for patcher in (
            patch.object(flow, "_catalog", side_effect=catalog),
            patch.object(flow, "_task", side_effect=recorded_task),
            patch.object(flow.LLMConfig, "load", return_value=object()),
        ):
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
            if patcher.attribute == "_task":
                self.task_mock = mocked

    def test_invalid_branch_names_are_rejected_before_state_creation(self):
        before = copy.deepcopy(self.source)
        for identifier in ("feedback bad", "feedback..bad", "feedback~bad", "feedback.lock"):
            with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, "运行标识"):
                flow.new_state(self.source, "quality", identifier)
        self.assertEqual(self.source, before)
        self.assertEqual((self.source_dir / "state.json").read_bytes(), self.source_bytes)
        self.assertEqual(git(self.root, "branch", "--show-current"), "main")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    @staticmethod
    def setup_git(path):
        git(path, "config", "user.name", "测试")
        git(path, "config", "user.email", "test@example.com")

    def execute(self):
        return asyncio.run(flow.run_node(self.run, self.state))

    def reach(self, node):
        for _ in range(10):
            if self.state["current_node"] == node:
                return
            self.execute()
        self.fail(f"未到达 {node}")

    def test_source_is_read_only_and_current_backlog_static_fields_are_used(self):
        self.execute()
        row = self.state["requirement_registry"]["requirements"][0]
        self.assertEqual(row["title"], "当前标题")
        self.assertEqual(row["completion"], {"step": 18})
        self.assertEqual(self.source["requirement_registry"]["requirements"][0]["title"], "历史标题")
        self.assertEqual((self.source_dir / "state.json").read_bytes(), self.source_bytes)
        self.assertNotIn("保存反馈原文", json.dumps(self.state, ensure_ascii=False))

    def test_only_completed_quality_or_feedback_sources_are_accepted(self):
        for change in ({"workflow": "phase_1"}, {"status": "failed"}, {"active_requirement": "BR-001"}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                flow.new_state({**self.source, **change}, "quality", "new")
        source = copy.deepcopy(self.source)
        source["requirement_registry"]["requirements"][0]["status"] = "pending"
        with self.assertRaises(RuntimeError):
            flow.new_state(source, "quality", "new")
        self.reach("feedback:completed")
        self.assertEqual(flow.new_state(self.state, self.run.name, "next")["feedback"]["batch_requirement_ids"], [])

    def test_empty_input_fails_before_prepare_side_effect(self):
        write_json(self.run / "feedback/input.json", {"source": str(self.original), "content": " \n", "attachments": []})
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_input_snapshot_not_original_is_consumed(self):
        self.original.write_text("外部编辑后的新内容")
        self.execute()
        supplied = flow._input(self.run)
        self.assertEqual(supplied.content, "  保存反馈原文\n")
        self.assertEqual(self.original.read_text(), "外部编辑后的新内容")

    def test_unknown_backlog_id_or_dirty_workspace_is_not_reconciled(self):
        self.catalog_override = [{"id": "BR-X", "title": "未知", "order": 1, "depends_on": []}]
        with self.assertRaisesRegex(RuntimeError, "正式 ID"):
            self.execute()
        self.catalog_override = None
        extra = self.root / "unknown.txt"
        extra.write_text("保留")
        with self.assertRaisesRegex(RuntimeError, "未提交"):
            self.execute()
        self.assertEqual(extra.read_text(), "保留")
        self.assertEqual(self.calls, [])

    def test_no_inclusion_commits_only_real_document_and_preserves_code(self):
        before = flow.main_versions(self.state)
        self.reach("feedback:completed")
        after = flow.main_versions(self.state)
        self.assertNotEqual(before["root"], after["root"])
        self.assertEqual(before["backend"], after["backend"])
        changed = git(self.root, "-c", "core.quotepath=false", "diff", "--name-only", before["root"], after["root"])
        self.assertEqual(changed, self.state["feedback"]["document_path"])
        self.assertEqual(self.state["feedback"]["batch_requirement_ids"], [])
        self.assertFalse((self.run / "feedback/register.json").exists())
        self.assertTrue(flow.is_completed(self.state))
        calls = self.calls.copy()
        self.execute()
        self.assertEqual(self.calls, calls)
        self.assertEqual((self.source_dir / "state.json").read_bytes(), self.source_bytes)

    def test_positive_feedback_archives_signal_without_candidates_or_requirements(self):
        signal = "本次保存材料操作很顺畅，没有需要调整的地方。"
        self.original.write_text(signal)
        write_json(self.run / "feedback/input.json", {
            "source": str(self.original), "content": signal, "attachments": [],
        })
        self.triage = TriageReport(summary=signal + "来源：反馈原文；无行动项，推荐为空。", findings=[],
                                   limitations=["仅记录本次正向体验，不代表全产品审计"])
        self.routing = RoutingReport(summary="无行动项，保留反馈信号并归档", decisions=[],
                                     document_changes=[], ready_to_complete=True)
        before = flow.main_versions(self.state)
        backlog = self.backlog.read_bytes()
        self.reach("feedback:completed")
        result = self.execute()["data"]
        document = self.root / self.state["feedback"]["document_path"]
        self.assertIn(self.triage.summary, document.read_text())
        self.assertIn(self.routing.summary, document.read_text())
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["dispositions"], [])
        self.assertEqual(result["completed_requirement_ids"], [])
        self.assertIsNone(result["requirement_bindings"])
        self.assertEqual(self.backlog.read_bytes(), backlog)
        self.assertEqual(self.original.read_text(), signal)
        after = flow.main_versions(self.state)
        self.assertEqual(before["backend"], after["backend"])
        self.assertEqual(git(self.root, "-c", "core.quotepath=false", "diff", "--name-only", before["root"], after["root"]),
                         self.state["feedback"]["document_path"])
        self.assertEqual([row[0] for row in self.calls], [
            "feedback_prepare", "feedback_triage", "feedback_route", "feedback_document", "feedback_commit",
        ])
        self.assertFalse((self.run / "feedback/register.json").exists())
        for call in self.task_mock.await_args_list:
            if call.args[2] in {"feedback_triage", "feedback_route", "feedback_document"}:
                self.assertIn(signal, call.args[4])
        self.assertTrue(flow.is_completed(self.state))

    def test_inclusion_registers_only_new_pending_and_preserves_history(self):
        self.include = True
        self.reach("feedback:select_requirement")
        self.assertEqual(self.state["feedback"]["batch_requirement_ids"], ["BR-002"])
        self.assertEqual([row["status"] for row in self.state["requirement_registry"]["requirements"]], ["completed", "pending"])
        self.state["active_requirement"] = "BR-002"
        evidence = flow.requirement_evidence(self.run, self.state)
        self.assertIn("保存被拒绝", evidence)
        self.assertIn('"F-C001": "BR-002"', evidence)
        self.assertEqual(git(self.root, "branch", "--show-current"), "main")

    def test_targeted_intake_precedes_design_and_breakdown(self):
        self.include = True
        self.routing = routing_report(True)
        from feedback.models import DocumentChange
        self.routing.document_changes = [
            DocumentChange(path="docs/prd/product.md", reason="新增已授权目标", task="project_intake"),
            DocumentChange(path="docs/design/ui.md", reason="交互目标变化", task="ui_ux_framework"),
        ]
        self.reach("feedback:select_requirement")
        self.assertEqual([row[1] for row in self.calls], ["feedback_prepare", "feedback_triage", "feedback_route", "project_intake", "ui_ux_framework", "feedback_pool", "feedback_pool", "requirement_commit"])
        self.assertEqual([row[2] for row in self.calls][1:6], ["product-feedback-triage", None, "project-intake", "ui-ux-framework", "requirement-breakdown"])

    def test_entire_downstream_chain_projects_large_legacy_reports_without_losing_inputs(self):
        from feedback.models import DocumentChange
        self.include = True
        self.routing = routing_report(True)
        self.routing.document_changes = [
            DocumentChange(path=f"docs/design/{task}.md", task=task, reason="承接保存目标")
            for task in flow.DESIGN_TASKS
        ]
        upstream_before = {}
        for name in ("prepare", "triage", "route"):
            self.execute()
            path = self.run / f"feedback/{name}.json"
            saved = json.loads(path.read_text())
            key = f"feedback_{name}"
            messages = json.loads((self.run / f"conversations/{key}.json").read_text())["messages"][2:]
            messages += [{"role": "assistant", "content": f"{name}后续纠正：仅使用隔离数据；原目标不变"}]
            lengths = []
            for size in (1000, 100000):
                old = json.dumps({"report": "旧历史包装" * size}, ensure_ascii=False)
                saved["data"]["report"] = old
                write_json(path, saved)
                save_conversation(self.run, self.state, key, messages, initial=old)
                projected = flow._handoff(self.run, self.state, name)
                lengths.append(len(json.dumps(projected, ensure_ascii=False)))
                self.assertNotIn("旧历史包装", projected["report"])
                self.assertIn(f"{name}后续纠正", projected["report"])
            self.assertEqual(lengths[0], lengths[1])
            upstream_before[path] = path.read_bytes()
            conversation = self.run / f"conversations/{key}.json"
            upstream_before[conversation] = conversation.read_bytes()
        self.execute()
        prompts = {call.args[2]: call.args[4] for call in self.task_mock.await_args_list}
        for key, prompt in prompts.items():
            self.assertNotIn("旧历史包装", prompt)
            self.assertLess(len(prompt), 20000, key)
        for key in ("feedback_triage", "feedback_route", *(f"feedback_{task}" for task in flow.DESIGN_TASKS),
                    "feedback_pool", "feedback_document"):
            self.assertIn("既有入口、端口与授权数据可访问", prompts[key])
            self.assertIn("prepare后续纠正", prompts[key])
            self.assertIn("保存反馈原文", prompts[key])
            self.assertIn(str(self.original), prompts[key])
            self.assertIn("核验保存", prompts[key])
        for key in (*(f"feedback_{task}" for task in flow.DESIGN_TASKS), "feedback_pool", "feedback_document"):
            for text in ("F-C001", "反馈第一段", "只核验提供的反馈", "triage后续纠正", "route后续纠正"):
                self.assertIn(text, prompts[key])
        self.assertEqual(upstream_before, {path: path.read_bytes() for path in upstream_before})

    def test_scope_outside_document_is_preserved_and_blocks_triage(self):
        self.reach("feedback:triage")
        actual = self.task_mock.side_effect
        async def outside(*args, **kwargs):
            result = await actual(*args, **kwargs)
            (self.root / "unrelated.txt").write_text("不自动清理")
            return result
        self.task_mock.side_effect = outside
        with self.assertRaisesRegex(RuntimeError, "范围外"):
            self.execute()
        self.assertEqual((self.root / "unrelated.txt").read_text(), "不自动清理")

    def test_code_repository_drift_blocks_pool_without_cleanup(self):
        self.reach("feedback:pool")
        (self.backend / "app.py").write_text("changed\n")
        with self.assertRaisesRegex(RuntimeError, "未提交"):
            self.execute()
        self.assertEqual((self.backend / "app.py").read_text(), "changed\n")

    def test_branch_creation_interruption_reuses_saved_branch_and_document(self):
        self.reach("feedback:triage")
        actual = flow.git
        def interrupted(path, *args, **kwargs):
            result = actual(path, *args, **kwargs)
            if args[:2] == ("switch", "-c"):
                raise OSError("建分支后中断")
            return result
        with patch.object(flow, "git", side_effect=interrupted), self.assertRaises(OSError):
            self.execute()
        saved = copy.deepcopy(self.state["feedback"])
        self.state = read_state(self.run)
        self.execute()
        self.assertEqual(self.state["feedback"], saved)
        self.assertEqual(sum(row[0] == "feedback_triage" for row in self.calls), 1)

    def test_success_result_interruption_replays_every_node_without_agents(self):
        self.include = True
        for node, following in (("prepare", "triage"), ("triage", "route"), ("route", "pool"),
                                ("pool", "register"), ("register", "select_requirement")):
            self.reach(f"feedback:{node}")
            actual = flow.write_state
            def interrupted(run_dir, state):
                if state["current_node"] == f"feedback:{following}":
                    raise OSError("结果落盘后中断")
                actual(run_dir, state)
            with patch.object(flow, "write_state", side_effect=interrupted), self.assertRaises(OSError):
                self.execute()
            self.state = read_state(self.run)
            calls = self.calls.copy()
            self.execute()
            self.assertEqual(self.calls, calls)
            self.assertEqual(self.state["current_node"], f"feedback:{following}")
        self.assertEqual(self.state["feedback"]["batch_requirement_ids"], ["BR-002"])

    def test_merge_interruption_never_repeats_pool_or_commit(self):
        self.include = True
        self.reach("feedback:pool")
        actual = flow.git
        def interrupted(path, *args, **kwargs):
            result = actual(path, *args, **kwargs)
            if args[:2] == ("merge", "--ff-only"):
                raise OSError("合并后中断")
            return result
        with patch.object(flow, "git", side_effect=interrupted), self.assertRaises(OSError):
            self.execute()
        calls, tip = self.calls.copy(), git(self.root, "rev-parse", "HEAD")
        self.state = read_state(self.run)
        self.execute()
        self.assertEqual(self.calls, calls)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), tip)
        self.assertNotIn("feedback/", git(self.root, "branch", "--list"))

    def test_required_feedback_cannot_be_deferred(self):
        self.triage.findings[0].mandatory = True
        self.routing = routing_report()
        self.routing.decisions[0].action = "defer"
        self.routing.decisions[0].follow_up = "提供生产外隔离数据"
        self.reach("feedback:route")
        with self.assertRaisesRegex(ValueError, "必达"):
            self.execute()
        self.routing = routing_report(True)
        self.execute()
        self.assertEqual(self.state["current_node"], "feedback:pool")
        self.assertIsNone(self.state["blocked"])

    def test_optional_unresolved_is_accurately_retained_at_completion(self):
        self.routing = routing_report()
        self.routing.decisions[0].action = "defer"
        self.routing.decisions[0].follow_up = "取得隔离数据后另批核验"
        self.reach("feedback:completed")
        result = self.execute()["data"]
        self.assertEqual(result["dispositions"][0]["action"], "defer")
        self.assertEqual(result["dispositions"][0]["follow_up"], "取得隔离数据后另批核验")
        self.assertEqual(result["completed_requirement_ids"], [])

    def finish_batch(self):
        self.include = True
        self.reach("feedback:select_requirement")
        (self.root / "docs/fix.md").write_text("修复交接\n")
        git(self.root, "add", "docs/fix.md")
        git(self.root, "commit", "-m", "fix: 保存修复")
        for row in self.state["requirement_registry"]["requirements"]:
            row.update(status="completed", completion={"step": 18})
        path = self.run / "steps/requirements/BR-002/18.json"
        path.parent.mkdir(parents=True)
        write_json(path, {"status": "success", "requirement_id": "BR-002", "repositories": [
            {"name": name, "tip_sha": sha} for name, sha in flow.main_versions(self.state).items()
        ]})
        write_json(self.run / "state.json", self.state)

    def test_completed_batch_and_complete_result_recovery(self):
        self.finish_batch()
        self.reach("feedback:complete")
        with patch.object(flow, "_replace_state", side_effect=OSError("中断")), self.assertRaises(OSError):
            self.execute()
        self.state = read_state(self.run)
        self.execute()
        self.assertTrue(flow.is_completed(self.state))
        self.assertEqual(sum(row[0] == "feedback_triage" for row in self.calls), 1)

    def test_completion_reports_current_progress_and_preserves_phase_history(self):
        self.triage.summary = "已核验保存问题，尚未开发和回归"
        self.triage.limitations = ["尚未开发、回归、提交或合并", "仅核验隔离数据，未覆盖生产环境"]
        self.routing = routing_report(True)
        self.routing.summary = "已纳入保存修复，尚待开发、回归、提交和合并"
        for action, title in (("defer", "其它角色的保存待补证"), ("covered", "详情页保存同批处理")):
            self.triage.findings.append(self.triage.findings[0].model_copy(update={"title": title}))
            self.routing.decisions.append(self.routing.decisions[0].model_copy(update={
                "candidate_id": f"F-C00{len(self.triage.findings)}", "action": action,
                "covered_by": "F-C001" if action == "covered" else None,
                "follow_up": "取得其它角色隔离数据后另批核验" if action == "defer" else "",
            }))
        self.finish_batch()
        self.reach("feedback:complete")
        before = {path: path.read_bytes() for path in (self.run / "feedback").glob("*.json")}
        versions, calls = flow.main_versions(self.state), self.calls.copy()
        result = self.execute()
        data = result["data"]
        self.assertNotEqual(data["summary"], self.routing.summary)
        self.assertIn("已完成开发、验证、提交与合并：BR-002", result["summary"])
        self.assertIn("需求承接：BR-002 ← F-C001（已完成）", data["summary"])
        self.assertIn("完整回归：F-C001 → BR-002（已完成）", data["summary"])
        self.assertIn("F-C003=covered → F-C001", data["summary"])
        self.assertIn("F-C002=defer", data["summary"])
        self.assertIn("不代表全部反馈已解决", data["summary"])
        self.assertIn("分诊时摘要：" + self.triage.summary, data["summary"])
        self.assertIn("范围决定时摘要：" + self.routing.summary, data["summary"])
        self.assertEqual(data["limitations"], ["分诊时：" + text for text in self.triage.limitations])
        self.assertEqual(data["dispositions"], self.routing.model_dump()["decisions"])
        self.assertEqual(data["requirement_bindings"], pool_plan().model_dump())
        self.assertEqual(data["completed_requirement_ids"], ["BR-002"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(flow.main_versions(self.state), versions)
        self.assertEqual(self.calls, calls)

    def test_no_inclusion_completion_distinguishes_archival_from_earlier_limitations(self):
        self.triage.summary = "独立事项待补证"
        self.triage.limitations = ["反馈文档尚未提交与合并", "缺少其它角色隔离数据"]
        self.routing = routing_report()
        self.routing.summary = "暂不纳入，反馈文档尚未提交与合并"
        self.routing.decisions[0].action = "defer"
        self.routing.decisions[0].follow_up = "取得其它角色隔离数据后另批核验"
        self.reach("feedback:complete")
        calls = self.calls.copy()
        result = self.execute()
        data = result["data"]
        self.assertNotEqual(data["summary"], self.routing.summary)
        self.assertIn("反馈文档已提交并合并", result["summary"])
        self.assertIn("本批无纳入需求", data["summary"])
        self.assertNotIn("已完成开发", data["summary"])
        self.assertIn("F-C001=defer", data["summary"])
        self.assertIn("分诊时摘要：" + self.triage.summary, data["summary"])
        self.assertIn("范围决定时摘要：" + self.routing.summary, data["summary"])
        self.assertEqual(data["limitations"], ["分诊时：" + text for text in self.triage.limitations])
        self.assertEqual(data["dispositions"], self.routing.model_dump()["decisions"])
        self.assertIsNone(data["requirement_bindings"])
        self.assertEqual(data["completed_requirement_ids"], [])
        self.assertEqual(self.calls, calls)

    def test_completion_rejects_unrecorded_versions(self):
        self.finish_batch()
        self.reach("feedback:complete")
        (self.root / "docs/other.md").write_text("未知提交")
        git(self.root, "add", "docs/other.md")
        git(self.root, "commit", "-m", "docs: 外部提交")
        with self.assertRaisesRegex(RuntimeError, "最终版本"):
            self.execute()

    def test_completion_requires_feedback_document_in_final_tree(self):
        self.finish_batch()
        self.reach("feedback:complete")
        git(self.root, "rm", "--", self.state["feedback"]["document_path"])
        git(self.root, "commit", "-m", "docs: 错误移除反馈文档")
        with self.assertRaisesRegex(RuntimeError, "缺少本批反馈文档"):
            self.execute()

    def test_select_repeats_and_pending_cannot_complete(self):
        self.include = True
        self.reach("feedback:select_requirement")
        for _ in range(2):
            self.execute()
            self.assertEqual(self.state["step"], 13)
            self.state.update(step=None, current_step=None)
        with self.assertRaisesRegex(RuntimeError, "未完成"):
            flow._complete(self.run, self.state)

    def test_commit_interruption_before_intent_persistence_does_not_recommit(self):
        self.include = True
        self.reach("feedback:pool")
        actual = flow.write_state
        def interrupted(run_dir, state):
            if state["feedback"]["document_intent"]["tip"] is not None:
                raise OSError("提交后intent写入中断")
            actual(run_dir, state)
        with patch.object(flow, "write_state", side_effect=interrupted), self.assertRaises(OSError):
            self.execute()
        calls, tip = self.calls.copy(), git(self.root, "rev-parse", "HEAD")
        self.state = read_state(self.run)
        self.execute()
        self.assertEqual(self.calls, calls)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), tip)
        self.assertEqual(self.state["current_node"], "feedback:register")

    def test_clean_commit_does_not_bypass_blocked_original_session(self):
        self.reach("feedback:pool")
        actual = self.task_mock.side_effect
        committed = False
        async def interrupted(*args, **kwargs):
            nonlocal committed
            if committed and args[2] == "feedback_document":
                return "既有文档收尾已完成", None
            if args[2] == "feedback_commit":
                if not committed:
                    await actual(*args, **kwargs)
                    committed = True
                    self.state["feedback_commit"] = {"last_agent_result": {"subtype": "success"}}
                raise flow.FeedbackBlocked("原会话外部条件仍未解除", ["提供必需授权"])
            return await actual(*args, **kwargs)
        self.task_mock.side_effect = interrupted
        for _ in range(2):
            with self.assertRaises(flow.FeedbackBlocked) as caught:
                self.execute()
            flow.record_failure(self.run, self.state, caught.exception)
            self.assertEqual(self.state["status"], "blocked")
            self.assertEqual(self.state["current_node"], "feedback:pool")
            self.assertNotEqual(git(self.root, "branch", "--show-current"), "main")
            self.assertEqual(git(self.root, "status", "--porcelain=v1"), "")

    def test_branch_cleanup_interruption_recovers_without_duplicate_commit(self):
        self.reach("feedback:pool")
        actual = flow.git
        def interrupted(path, *args, **kwargs):
            result = actual(path, *args, **kwargs)
            if args[:2] == ("branch", "-d"):
                raise OSError("清理后中断")
            return result
        with patch.object(flow, "git", side_effect=interrupted), self.assertRaises(OSError):
            self.execute()
        calls = self.calls.copy()
        self.state = read_state(self.run)
        self.execute()
        self.assertEqual(self.calls, calls)
        self.reach("feedback:completed")
        self.assertTrue(flow.is_completed(self.state))

    def test_covered_chain_handoff_keeps_each_related_original_feedback(self):
        self.include = True
        self.reach("feedback:select_requirement")
        triage_path, route_path = self.run / "feedback/triage.json", self.run / "feedback/route.json"
        triage, routed = json.loads(triage_path.read_text()), json.loads(route_path.read_text())
        for number, title in ((2, "详情页保存也失败"), (3, "批量保存任务受阻")):
            candidate = copy.deepcopy(triage["data"]["candidates"][0])
            candidate.update(id=f"F-C00{number}", title=title)
            triage["data"]["candidates"].append(candidate)
            routed["data"]["decisions"].append({"candidate_id": candidate["id"], "action": "covered",
                                                "reason": "同一保存结果", "covered_by": f"F-C00{number - 1}", "follow_up": ""})
        write_json(triage_path, triage)
        write_json(route_path, routed)
        self.state["active_requirement"] = "BR-002"
        evidence = flow.requirement_evidence(self.run, self.state)
        self.assertIn("详情页保存也失败", evidence)
        self.assertIn("批量保存任务受阻", evidence)
        self.assertIn('"F-C003": "BR-002"', evidence)

    def test_symlink_result_and_document_paths_are_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        result = self.run / "feedback/prepare.json"
        result.symlink_to(outside / "prepare.json")
        with self.assertRaisesRegex(RuntimeError, "符号链接"):
            self.execute()
        result.unlink()
        self.execute()
        (self.root / "docs/feedback").symlink_to(outside, target_is_directory=True)
        with self.assertRaises((RuntimeError, ValueError)):
            self.execute()
        self.assertEqual(list(outside.iterdir()), [])

    def test_missing_attachment_is_an_input_failure_and_original_cannot_be_edited(self):
        supplied = flow._input(self.run).model_dump()
        write_json(self.run / "feedback/input.json", {**supplied, "attachments": [str(self.base / "missing.png")]})
        with self.assertRaisesRegex(ValueError, "附件"):
            self.execute()
        write_json(self.run / "feedback/input.json", {**supplied, "source": str(self.backlog)})
        self.include = True
        self.reach("feedback:pool")
        before = self.backlog.read_bytes()
        with self.assertRaisesRegex(ValueError, "原始材料"):
            self.execute()
        self.assertEqual(self.backlog.read_bytes(), before)

    def test_intent_original_conflicting_with_design_is_rejected_before_writes(self):
        from feedback.models import DocumentChange
        relative = "docs/prd/batch-intent.md"
        original_intent = self.root / relative
        original_intent.parent.mkdir(parents=True)
        original_intent.write_text("本批意图原件必须保持不变\n", encoding="utf-8")
        git(self.root, "add", "--", relative)
        git(self.root, "commit", "-m", "docs: 保留输入原件")
        supplied = flow._input(self.run).model_dump()
        write_json(self.run / "feedback/input.json", {**supplied, "intent_source": str(original_intent)})
        self.include = True
        self.routing = routing_report(True)
        self.routing.document_changes = [DocumentChange(path=relative, task="project_intake", reason="定义调整")]
        self.reach("feedback:route")
        before = original_intent.read_bytes()
        with self.assertRaisesRegex(ValueError, "意图原件"):
            self.execute()
        self.assertEqual(original_intent.read_bytes(), before)
        self.assertFalse(any(task in flow.DESIGN_TASKS for _, task, _ in self.calls))
        with self.assertRaisesRegex(ValueError, "意图原件"):
            flow._protect_inputs(self.run, self.state, {relative})

    def test_local_failures_do_not_become_blocked_or_overwrite_success(self):
        flow.record_failure(self.run, self.state, RuntimeError("本地执行错误"))
        self.assertEqual(self.state["status"], "failed")
        self.assertIsNone(self.state["blocked"])
        actual = self.task_mock.side_effect
        async def checks(*args, **kwargs):
            self.assertEqual(self.state["status"], "failed")
            return await actual(*args, **kwargs)
        self.task_mock.side_effect = checks
        with patch.object(flow, "_advance", side_effect=OSError("中断")), self.assertRaises(OSError):
            self.execute()
        saved = flow.record_failure(self.run, self.state, RuntimeError("不能覆盖成功"))
        self.assertEqual(saved["status"], "success")
        self.execute()
        self.assertEqual(self.state["status"], "success")


if __name__ == "__main__":
    unittest.main()
