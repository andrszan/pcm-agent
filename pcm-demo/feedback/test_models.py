from __future__ import annotations

import copy
import unittest

from common.requirement_registry import validate_catalog
from feedback.models import DocumentChange, FeedbackInput, validate_pool_plan, validate_routing
from feedback.test_workflow import pool_plan, routing_report, triage_report
from feedback.workflow import _validate_increment


class FeedbackModelTests(unittest.TestCase):
    def setUp(self):
        self.triage = {"candidates": [{"id": "F-C001", **triage_report().findings[0].model_dump()}]}

    def test_input_preserves_original_and_rejects_relative_paths(self):
        value = FeedbackInput(source="/original.txt", content=" \n原文\n ", attachments=["/screen.png"])
        self.assertEqual(value.content, " \n原文\n ")
        self.assertEqual(value.intent, "")
        self.assertIsNone(value.intent_source)
        for change in ({"source": "relative.txt"}, {"attachments": ["relative.png"]},
                       {"intent_source": "relative-intent.md"}, {"intent_source": ""}, {"content": "", "attachments": []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                FeedbackInput.model_validate({**value.model_dump(), **change})

    def test_optional_intent_source_accepts_old_input_null_and_absolute_path(self):
        old_input = {"source": "/original.md", "content": "反馈原文", "attachments": [], "intent": "本批意图"}
        self.assertIsNone(FeedbackInput.model_validate(old_input).intent_source)
        for source in (None, "/original-intent.md"):
            parsed = FeedbackInput.model_validate({**old_input, "intent_source": source})
            self.assertEqual(parsed.intent_source, source)
            self.assertEqual(parsed.intent, "本批意图")

    def test_routing_rejects_missing_duplicate_and_unknown_candidates(self):
        for identifiers in ([], ["F-C001", "F-C001"], ["F-C999"]):
            report = routing_report()
            report.decisions = [report.decisions[0].model_copy(update={"candidate_id": value}) for value in identifiers]
            with self.subTest(identifiers=identifiers), self.assertRaisesRegex(ValueError, "集合"):
                validate_routing(report, self.triage, [])

    def test_covered_references_cannot_use_history_unknown_or_cycles(self):
        for reference in ("BR-001", "F-C999", "F-C001"):
            report = routing_report(True)
            report.decisions[0].action = "covered"
            report.decisions[0].covered_by = reference
            with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, "归属"):
                validate_routing(report, self.triage, [{"id": "BR-001", "status": "completed"}])

    def test_mandatory_covered_chain_cannot_hide_deferral(self):
        second = copy.deepcopy(self.triage["candidates"][0])
        second.update(id="F-C002", mandatory=True)
        self.triage["candidates"].append(second)
        report = routing_report()
        report.decisions[0].action = "defer"
        report.decisions[0].follow_up = "后续授权"
        report.decisions.append(report.decisions[0].model_copy(update={"candidate_id": "F-C002", "action": "covered", "covered_by": "F-C001"}))
        with self.assertRaisesRegex(ValueError, "必达"):
            validate_routing(report, self.triage, [])
        report.decisions[0].action = "include"
        report.ready_to_complete = False
        validate_routing(report, self.triage, [])

    def test_satisfied_requires_evidence_and_defer_requires_follow_up(self):
        report = routing_report()
        self.triage["candidates"][0]["evidence"] = []
        with self.assertRaisesRegex(ValueError, "核验事实"):
            validate_routing(report, self.triage, [])
        report.decisions[0].action = "defer"
        with self.assertRaisesRegex(ValueError, "后续条件"):
            validate_routing(report, self.triage, [])
        report.decisions[0].follow_up = "取得新的观察材料后继续"
        validate_routing(report, self.triage, [])

    def test_no_quality_coverage_gate_for_authorized_new_capability(self):
        self.triage["candidates"][0].update(kind="new_capability", observed="当前尚无此能力", evidence=[], mandatory=True)
        report = routing_report(True)
        validate_routing(report, self.triage, [])
        self.assertFalse(report.ready_to_complete)

    def test_design_paths_reject_traversal_history_private_and_pool_documents(self):
        for path in ("/tmp/escape.md", "../escape.md", "docs/trd/history.md", "docs/ignore/resource.md",
                     "docs/backlog/backlog.md", "docs/feedback/other.md", "src/main.py"):
            report = routing_report(True)
            report.document_changes = [DocumentChange(path=path, reason="测试边界", task="project_intake")]
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_routing(report, self.triage, [])

    def test_no_inclusion_cannot_change_definition(self):
        report = routing_report()
        report.document_changes = [DocumentChange(path="docs/prd/product.md", reason="越界", task="project_intake")]
        with self.assertRaisesRegex(ValueError, "没有纳入"):
            validate_routing(report, self.triage, [])

    def test_pool_requires_total_mapping_and_unique_owner(self):
        report = routing_report(True).model_dump()
        for mutation in ("history", "unknown", "no_owner", "duplicate_owner"):
            plan = pool_plan()
            if mutation == "history":
                plan.requirements[0].requirement_id = "BR-001"
            elif mutation == "unknown":
                plan.requirements[0].candidate_ids = ["F-C999"]
            elif mutation == "no_owner":
                plan.regression_owners = []
            else:
                plan.regression_owners.append(plan.regression_owners[0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_pool_plan(plan, report, {"BR-001"})

    def test_split_owner_requires_real_transitive_dependencies_and_static_history(self):
        plan = pool_plan()
        plan.requirements.append(plan.requirements[0].model_copy(update={"requirement_id": "BR-003"}))
        plan.regression_owners[0].requirement_id = "BR-003"
        old = {"id": "BR-001", "title": "旧需求", "order": 1, "depends_on": []}
        state = {"requirement_registry": {"requirements": [{**old, "status": "completed"}]}}
        catalog = [old, {"id": "BR-002", "title": "接口", "order": 2, "depends_on": []},
                   {"id": "BR-003", "title": "完整场景", "order": 3, "depends_on": []}]
        validate_pool_plan(plan, routing_report(True).model_dump(), {"BR-001"})
        with self.assertRaisesRegex(ValueError, "必要依赖"):
            _validate_increment(state, validate_catalog(catalog), plan)
        catalog[2]["depends_on"] = ["BR-002"]
        _validate_increment(state, validate_catalog(catalog), plan)
        for dependency in ("BR-999", "BR-003"):
            catalog[1]["depends_on"] = [dependency]
            with self.subTest(dependency=dependency), self.assertRaises(RuntimeError):
                validate_catalog(catalog)
        catalog[1]["depends_on"] = []
        changed = copy.deepcopy(catalog)
        changed[0]["title"] = "修改历史需求"
        with self.assertRaisesRegex(ValueError, "既有需求"):
            _validate_increment(state, validate_catalog(changed), plan)


if __name__ == "__main__":
    unittest.main()
