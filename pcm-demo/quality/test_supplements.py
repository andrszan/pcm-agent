from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from common.files import write_json
from common.state import read_state
from quality import workflow as flow
from quality.workflow import _task as run_quality_task
from quality import test_workflow as fixtures
from quality.test_workflow import git, audit_report


class SupplementTests(unittest.TestCase):
    execute = fixtures.QualityWorkflowTests.execute
    reach = fixtures.QualityWorkflowTests.reach

    def setUp(self):
        fixtures.QualityWorkflowTests.setUp(self)
        self.reach("quality:complete")
        (self.root / ".gitignore").write_text("backend/\nfrontend/\n")
        git(self.root, "add", ".gitignore")
        git(self.root, "commit", "-m", "docs: 隔离代码仓")
        for name in ("frontend", "backend"):
            path = self.root / name
            path.mkdir()
            git(path, "init", "-b", "main")
            git(path, "config", "user.name", "测试")
            git(path, "config", "user.email", "test@example.com")
            (path / "fix.py").write_text("before\n")
            git(path, "add", "fix.py")
            git(path, "commit", "-m", "feat: baseline")
            (path / "fix.py").write_text("fixed\n")
            self.state["applicable_repositories"].append(name)
            self.state["repositories"].append({"name": name, "path": str(path)})
        self.key = "quality_audit_r0001"
        self.state["claude_sessions"] = {self.key: "original-session"}
        self.state["decision_conversations"] = {self.key: {"path": f"conversations/{self.key}.json"}}
        self.messages = [{"role": "system", "content": "任务"},
                         {"role": "assistant", "content": "补齐必要证据"},
                         {"role": "user", "content": "补证发现诊断与工具合同错误，已有修复需要正式登记"}]
        (self.run / "conversations").mkdir()
        write_json(self.run / f"conversations/{self.key}.json", {"messages": self.messages})
        self.owner = self.base / "owner.md"
        self.owner.write_text("负责人同意将诊断与工具合同修复作为一个正式补充需求接管，复用开发与合并流程。")
        self.handoff = self.base / "handoff.md"
        self.handoff.write_text("已修复诊断及工具合同，单元测试通过，剩余真实会话补证。")
        def source(path):
            return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "quote": path.read_text()}
        self.input = {
            "run_id": self.run.name, "product_path": str(self.root), "audit_session_id": "original-session",
            "finding_source": {"message_index": 2, "sha256": hashlib.sha256(self.messages[2]["content"].encode()).hexdigest(),
                               "quote": self.messages[2]["content"]},
            "owner_decision": source(self.owner), "handoff_source": source(self.handoff),
            "findings": [audit_report(True).findings[0].model_dump()],
            "implementation": "已实现诊断与合同修复", "validation": ["隔离回归通过"], "remaining": ["原会话真实补证"],
            "repositories": {
                name: {"head": git(path, "rev-parse", "HEAD"), "changes": [] if name == "root" else [
                    {"path": "fix.py", "change": "M", "sha256": hashlib.sha256((path / "fix.py").read_bytes()).hexdigest(),
                     "mode": "100644", "base_sha256": hashlib.sha256(b"before\n").hexdigest(), "base_mode": "100644"}
                ]} for name, path in flow.repositories(self.state)
            },
        }
        self.input_file = self.base / "supplement.json"
        write_json(self.input_file, self.input)
        write_json(self.run / "state.json", self.state)

    def begin(self):
        flow.begin_supplement(self.run, self.state, self.input_file)

    def test_supplement_entry_preserves_history_and_accepts_exact_dirty_set(self):
        history = {p: p.read_bytes() for p in (self.run / "quality").rglob("*.json")}
        self.begin()
        self.assertEqual(self.state["current_node"], "quality:route")
        self.assertEqual(self.state["quality"]["round"], 1)
        self.assertEqual(self.state["quality"]["batch_requirement_ids"], [])
        self.assertEqual(self.state["quality"]["supplement"]["batch_requirement_ids"], [])
        self.assertTrue((self.run / "quality/supplements/0001/input.json").is_file())
        before = copy.deepcopy(self.state)
        self.begin()
        self.assertEqual(self.state, before)
        for path, content in history.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual((self.root / "backend/fix.py").read_text(), "fixed\n")

    def configure_supplement_tasks(self):
        from quality.models import PoolPlan, RoutingReport
        self.routing.side_effect = None
        self.routing.return_value = RoutingReport.model_validate({
            "summary": "登记已有诊断及合同修复", "decisions": [{"candidate_id": "S001-C001", "action": "include",
            "reason": "恢复用户任务", "covered_by": None}], "document_changes": [], "ready_to_complete": False,
        })
        previous_task = flow._task.side_effect

        async def task(run_dir, state, key, task, prompt, responsibility, **kwargs):
            if key == "quality_pool_s0001":
                self.calls.append(key)
                self.backlog.write_text("BR-001 当前标题\nBR-002 修复保存，依赖 BR-001\n")
                plan = PoolPlan.model_validate({"summary": "唯一接管需求", "requirements": [
                    {"requirement_id": "BR-002", "candidate_ids": ["S001-C001"]}],
                    "regression_owners": [{"candidate_id": "S001-C001", "requirement_id": "BR-002"}]})
                await kwargs["validate"](plan)
                return "已有实现与验证归属 BR-002", plan
            return await previous_task(run_dir, state, key, task, prompt, responsibility, **kwargs)
        flow._task.side_effect = task

    def reach_selection(self):
        self.begin()
        self.configure_supplement_tasks()
        self.reach("quality:select_requirement")
        self.execute()

    def merge_supplement(self):
        from common.state import write_requirement_step_result
        from steps.step_13_select_requirement import step as selection
        from steps.step_17_commit import step as commit
        from steps.step_18_merge import step as merge
        self.reach_selection()
        selection.run(self.run, self.state)
        (self.root / "docs/trd").mkdir()
        (self.root / "docs/trd/BR-002.md").write_text("已承接实现和必要验证\n")
        result_repos = []
        for name, path in flow.repositories(self.state):
            git(path, "add", "docs/trd/BR-002.md" if name == "root" else "fix.py")
            git(path, "commit", "-m", "fix: 正式需求接管修复")
            tip = git(path, "rev-parse", "HEAD")
            record = self.state["requirement_cycle"]["repositories"][name]
            record.update(tip_sha=tip, merged=False)
            result_repos.append({"name": name, "path": "." if name == "root" else name,
                                 "base_sha": record["base_sha"], "tip_sha": tip})
        self.state["requirement_cycle"].update(trd_path="docs/trd/BR-002.md", development_session_id="fixture-development")
        self.state.update(step=18, current_step=18, current_node="requirement:18_merge")
        saved = commit.result("success", "隔离测试的已提交交接", requirement_id="BR-002", branch="req/br-002", repositories=result_repos)
        write_requirement_step_result(self.run, "BR-002", 17, saved)
        merge.run(self.run, self.state)
        self.execute()
        self.assertEqual(self.state["current_node"], "quality:complete")

    def test_invalid_entries_sources_and_unknown_changes_have_no_side_effects(self):
        scenarios = [
            ("node", lambda: self.state.update(current_node="quality:route")),
            ("active", lambda: self.state.update(active_requirement="BR-001")),
            ("pending", lambda: self.state["requirement_registry"]["requirements"][0].update(status="pending")),
            ("run", lambda: self.input.update(run_id="other")),
            ("product", lambda: self.input.update(product_path=str(self.base))),
            ("session", lambda: self.input.update(audit_session_id="other")),
            ("source", lambda: self.input["finding_source"].update(sha256="0" * 64)),
            ("owner", lambda: self.input["owner_decision"].update(quote="未经记录的决定")),
            ("handoff", lambda: self.input["handoff_source"].update(sha256="0" * 64)),
            ("missing-repo", lambda: self.input["repositories"].pop("frontend")),
            ("unknown", lambda: (self.root / "backend/unknown.py").write_text("unknown")),
        ]
        initial_state, initial_input = copy.deepcopy(self.state), copy.deepcopy(self.input)
        for name, mutate in scenarios:
            with self.subTest(name=name):
                self.state, self.input = copy.deepcopy(initial_state), copy.deepcopy(initial_input)
                mutate()
                write_json(self.input_file, self.input)
                before = copy.deepcopy(self.state)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.begin()
                self.assertEqual(self.state, before)
                self.assertFalse((self.run / "quality/supplements").exists())
                self.assertEqual(git(self.root, "branch", "--show-current"), "main")
        (self.root / "backend/unknown.py").unlink()

    def test_exact_adoption_rejects_content_mode_index_head_paths_and_operations(self):
        from quality.git import validate_adoption
        path = self.root / "backend"
        record = self.input["repositories"]["backend"]
        mutations = [
            lambda row: row["changes"][0].update(sha256="0" * 64),
            lambda row: row["changes"][0].update(mode="100755"),
            lambda row: row["changes"][0].update(base_sha256="0" * 64),
            lambda row: row.update(head="0" * 40),
            lambda row: row["changes"][0].update(path="../fix.py"),
            lambda row: row["changes"][0].update(path="/tmp/fix.py"),
            lambda row: row["changes"][0].update(path="*.py"),
            lambda row: row["changes"].clear(),
        ]
        for mutation in mutations:
            invalid = copy.deepcopy(record)
            mutation(invalid)
            with self.assertRaises(RuntimeError):
                validate_adoption(path, invalid)
        git(path, "add", "fix.py")
        with self.assertRaisesRegex(RuntimeError, "staged"):
            validate_adoption(path, record)
        git(path, "restore", "--staged", "fix.py")
        (path / "fix.py").chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "模式"):
            validate_adoption(path, record)
        (path / "fix.py").chmod(0o644)
        (path / "fix.py").unlink()
        (path / "fix.py").symlink_to(self.owner)
        with self.assertRaisesRegex(RuntimeError, "符号链接"):
            validate_adoption(path, record)
        (path / "fix.py").unlink()
        (path / "fix.py").write_text("fixed\n")
        for marker in ("MERGE_HEAD", "rebase-merge"):
            operation = path / ".git" / marker
            if marker == "MERGE_HEAD":
                operation.write_text(record["head"] + "\n")
            else:
                operation.mkdir()
            with self.assertRaisesRegex(RuntimeError, "Git 操作"):
                validate_adoption(path, record)
            operation.rmdir() if operation.is_dir() else operation.unlink()
        self.assertEqual(validate_adoption(path, record), record["head"])

    def test_add_delete_binary_and_ignored_files(self):
        from quality.git import validate_adoption
        path = self.root / "backend"
        record = copy.deepcopy(self.input["repositories"]["backend"])
        (path / "fix.py").unlink()
        record["changes"][0].update(change="D", sha256=None, mode=None)
        (path / "binary.dat").write_bytes(b"\x00\xff\x80")
        record["changes"].append({"path": "binary.dat", "change": "A", "sha256": hashlib.sha256(b"\x00\xff\x80").hexdigest(),
                                  "mode": "100644", "base_mode": None, "base_sha256": None})
        with (path / ".git/info/exclude").open("a") as stream:
            stream.write("\n.env\n")
        (path / ".env").write_text("DO_NOT_READ=private")
        original_read = Path.read_bytes
        def read(file):
            if file.name == ".env":
                raise AssertionError("不得读取忽略配置")
            return original_read(file)
        with patch.object(Path, "read_bytes", read):
            validate_adoption(path, record)
        git(path, "add", "-N", "binary.dat")
        with self.assertRaisesRegex(RuntimeError, "staged"):
            validate_adoption(path, record)

    def test_default_clean_helpers_and_feedback_pool_boundary_stay_strict(self):
        from quality.git import main_versions
        with self.assertRaisesRegex(RuntimeError, "未提交"):
            main_versions(self.state)
        intent = {"branch": "main", "base": git(self.root, "rev-parse", "HEAD"), "allowed_paths": [],
                  "versions": {name: row["head"] for name, row in self.input["repositories"].items()}}
        with self.assertRaisesRegex(RuntimeError, "未提交"):
            flow._pool_boundary(self.state, intent)
        flow._pool_boundary(self.state, intent, adoption=self.input["repositories"])

    def test_pool_only_commits_root_and_selection_preserves_all_dirty_files(self):
        from steps.step_13_select_requirement import step as selection
        self.reach_selection()
        pooled = flow._prior(self.run, self.state, "pool")
        self.assertEqual(pooled["adoption_requirement_id"], "BR-002")
        for name in ("frontend", "backend"):
            path = self.root / name
            self.assertEqual(git(path, "rev-parse", "HEAD"), self.input["repositories"][name]["head"])
            self.assertEqual(git(path, "branch", "--show-current"), "main")
            self.assertEqual(git(path, "status", "--porcelain"), "M fix.py")
        selection.run(self.run, self.state)
        for name, path in flow.repositories(self.state):
            self.assertEqual(git(path, "branch", "--show-current"), "req/br-002")
            if name != "root":
                self.assertEqual((path / "fix.py").read_text(), "fixed\n")
        self.assertEqual(self.state["requirement_cycle"]["repositories"]["root"]["base_sha"], pooled["tip"])
        evidence = flow.requirement_evidence(self.run, self.state)
        for value in (self.input["implementation"], self.input["validation"][0], self.input["remaining"][0], "fix.py", "S001-C001", "BR-002"):
            self.assertIn(value, evidence)
        # 指纹保护在交接成功后结束，正常需求开发不冻结文件。
        (self.root / "backend/fix.py").write_text("follow-up\n")
        self.assertEqual(selection.run(self.run, self.state)["status"], "success")
        self.assertEqual(flow.requirement_evidence(self.run, self.state), evidence)

    def test_selection_partial_branches_reentry_and_changed_content_rejection(self):
        from steps.step_13_select_requirement import step as selection
        self.reach_selection()
        recover = selection._recover_branch
        def interrupt(repository, branch, base_sha):
            if repository["name"] == "backend":
                raise RuntimeError("模拟建分支中断")
            recover(repository, branch, base_sha)
        with patch.object(selection, "_recover_branch", side_effect=interrupt), self.assertRaises(RuntimeError):
            selection.run(self.run, self.state)
        self.state = read_state(self.run)
        self.assertEqual(git(self.root / "frontend", "branch", "--show-current"), "req/br-002")
        self.assertEqual(git(self.root / "backend", "branch", "--show-current"), "main")
        (self.root / "backend/fix.py").write_text("drift\n")
        with self.assertRaisesRegex(RuntimeError, "SHA256"):
            selection.run(self.run, self.state)
        self.assertEqual(git(self.root / "backend", "branch", "--show-current"), "main")
        (self.root / "backend/fix.py").write_text("fixed\n")
        # 已创建目标分支、当前回到 main 的恢复也必须保存修改。
        git(self.root / "frontend", "switch", "main")
        self.assertEqual(selection.run(self.run, self.state)["status"], "success")
        for name in ("frontend", "backend"):
            self.assertEqual((self.root / name / "fix.py").read_text(), "fixed\n")

    def test_selection_preflight_checks_every_repo_before_saving_cycle(self):
        from steps.step_13_select_requirement import step as selection
        self.reach_selection()
        before = copy.deepcopy(self.state)
        (self.root / "backend/fix.py").write_text("drift\n")
        with self.assertRaises(RuntimeError):
            selection.run(self.run, self.state)
        self.assertEqual(self.state, before)
        for _, path in flow.repositories(self.state):
            self.assertEqual(git(path, "branch", "--show-current"), "main")

    def test_input_pool_register_crash_replay_and_different_input_rejection(self):
        history = {p: p.read_bytes() for p in (self.run / "quality").rglob("*.json")}
        with patch.object(flow, "_replace_state", side_effect=RuntimeError("输入落盘后中断")), self.assertRaises(RuntimeError):
            self.begin()
        self.begin()
        self.configure_supplement_tasks()
        self.execute()
        for node in ("quality:pool", "quality:register"):
            self.assertEqual(self.state["current_node"], node)
            with patch.object(flow, "_advance", side_effect=RuntimeError("成功产物落盘后中断")), self.assertRaises(RuntimeError):
                self.execute()
            saved_path = flow.node_result_path(self.run, self.state)
            saved = saved_path.read_bytes()
            calls = self.calls.copy()
            with patch.object(flow, "_pool", side_effect=AssertionError("不重复入池")), patch.object(flow, "_register", side_effect=AssertionError("不重复登记")):
                self.execute()
            self.assertEqual(saved_path.read_bytes(), saved)
            self.assertEqual(self.calls, calls)
        self.assertEqual([row["status"] for row in self.state["requirement_registry"]["requirements"]], ["completed", "pending"])
        for path, content in history.items():
            self.assertEqual(path.read_bytes(), content)
        self.input["implementation"] = "不同输入"
        write_json(self.input_file, self.input)
        with self.assertRaisesRegex(RuntimeError, "不同输入"):
            self.begin()

    def test_current_session_anchor_new_evidence_and_local_only_resume(self):
        self.state["quality"]["local_only"] = True
        self.merge_supplement()
        original = {p: p.read_bytes() for p in (self.run / "quality/rounds").rglob("*.json")}
        calls = []
        anchor = flow.agent_conversation_report(self.run, self.state, flow.AgentDecisionLoopSpec(
            key=self.key, state_key=self.key, skill_name=None, max_decision_rounds=32, max_turns=1,
            task="quality_audit", decision_system_prompt="fixture"))
        async def complete(run_dir, state, key, task, prompt, responsibility, **kwargs):
            calls.append((key, kwargs["continue_from_report"]))
            return anchor, None
        flow._task.side_effect = complete
        with self.assertRaisesRegex(RuntimeError, "新会话补证"):
            self.execute()
        self.assertEqual(calls, [(self.key, anchor)])
        self.assertFalse((self.run / "quality/supplements/0001/coverage.json").exists())
        async def fresh(*args, **kwargs):
            return json.dumps(json.loads(anchor) + [
                {"role": "assistant", "content": args[4]},
                {"role": "user", "content": "当前合并版本已补证"}], ensure_ascii=False), None
        flow._task.side_effect = fresh
        with patch.object(flow, "_complete", side_effect=RuntimeError("补证落盘后中断")), self.assertRaises(RuntimeError):
            self.execute()
        with patch.object(flow, "_task", side_effect=AssertionError("不重开补证")), patch.object(flow, "sync_repositories", side_effect=AssertionError("local_only 不同步")), patch.object(flow, "remote_sync_enabled", return_value=True):
            self.execute()
        self.assertTrue(flow.is_completed(self.state))
        self.assertEqual(self.state["claude_sessions"][self.key], "original-session")
        self.assertEqual(self.state["quality"]["batch_requirement_ids"], [])
        for path, data in original.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertFalse((self.run / "quality/complete.json").exists())
        self.assertTrue((self.run / "quality/supplements/0001/complete.json").is_file())
        # 同输入完成后重复调用仍只复用，不接管已合并后的 clean 工作树。
        self.begin()

    def test_completion_rejects_missing_merge_unknown_head_and_old_evidence(self):
        self.merge_supplement()
        result_path = self.run / "steps/requirements/BR-002/18.json"
        saved = result_path.read_bytes()
        result_path.unlink()
        with self.assertRaisesRegex(RuntimeError, "交接文件"):
            flow._local_completion(self.run, self.state, coverage_report="fixture")
        result_path.write_bytes(saved)
        with self.assertRaisesRegex(RuntimeError, "当前版本补证"):
            flow._local_completion(self.run, self.state, coverage_report="fixture")
        git(self.root / "backend", "commit", "--allow-empty", "-m", "fix: 未知后续提交")
        with self.assertRaisesRegex(RuntimeError, "合并结果"):
            flow._local_completion(self.run, self.state, coverage_report="fixture")

    def test_original_and_supplement_batches_both_require_merge_results(self):
        # 历史结果 fixture 引用真实 Git 提交；补充需求仍运行真实选择/合并。
        from quality.models import PoolPlan
        audit = flow._prior(self.run, self.state, "audit")
        audit["candidates"] = [{"id": "Q001-C001", **audit_report(True).findings[0].model_dump()}]
        route = fixtures.route_report(True).model_dump()
        plan = PoolPlan.model_validate({"summary": "原批已修复", "requirements": [{"requirement_id": "BR-001", "candidate_ids": ["Q001-C001"]}],
                                       "regression_owners": [{"candidate_id": "Q001-C001", "requirement_id": "BR-001"}]})
        self.state["quality"].update(baseline_requirement_ids=[], batch_requirement_ids=["BR-001"])
        for name, data in (("audit", audit), ("route", route),
                           ("pool", {"plan": plan.model_dump(), "tip": self.input["repositories"]["root"]["head"]}),
                           ("register", {"new_ids": ["BR-001"], "registry": copy.deepcopy(self.state["requirement_registry"])})):
            flow._write(self.run / f"quality/rounds/0001/{name}.json", {"status": "success", "node": f"quality:{name}", "round": 1, "data": data})
        old_merge = self.run / "steps/requirements/BR-001/18.json"
        flow._write(old_merge, {"status": "success", "requirement_id": "BR-001", "repositories": [
            {"name": name, "tip_sha": record["head"]} for name, record in self.input["repositories"].items()]})
        historical = {path: path.read_bytes() for path in (self.run / "quality/rounds").rglob("*.json")}
        historical[old_merge] = old_merge.read_bytes()
        self.merge_supplement()
        old_merge.unlink()
        with self.assertRaisesRegex(RuntimeError, "交接文件"):
            flow._local_completion(self.run, self.state, coverage_report="fixture")
        old_merge.write_bytes(historical[old_merge])
        async def fresh(*args, **kwargs):
            return json.dumps(json.loads(kwargs["continue_from_report"]) + [
                {"role": "assistant", "content": args[4]},
                {"role": "user", "content": "当前版本已补齐原缺口"}], ensure_ascii=False), None
        flow._task.side_effect = fresh
        self.execute()
        completed = flow._read(self.run / "quality/supplements/0001/complete.json")
        self.assertEqual(completed["data"]["completed_requirement_ids"], ["BR-001", "BR-002"])
        self.assertEqual(self.state["quality"]["batch_requirement_ids"], ["BR-001"])
        for path, data in historical.items():
            self.assertEqual(path.read_bytes(), data)
        child = flow.new_state(self.state, self.run.name, "next-quality")
        history = flow._history(self.run.parent / "next-quality", child)
        self.assertEqual([row.get("supplement") for row in history], [None, "0001"])

    def test_pool_drift_and_multiple_adoption_owners_are_rejected(self):
        self.begin()
        self.configure_supplement_tasks()
        self.execute()
        (self.root / "backend/fix.py").write_text("drift\n")
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assertEqual(git(self.root, "branch", "--show-current"), "main")
        self.assertFalse((self.run / "quality/supplements/0001/pool-intent.json").exists())
        (self.root / "backend/fix.py").write_text("fixed\n")
        from quality.models import PoolPlan
        async def multiple(run_dir, state, key, task, prompt, responsibility, **kwargs):
            report = PoolPlan.model_validate({"summary": "错误拆分", "requirements": [
                {"requirement_id": identifier, "candidate_ids": ["S001-C001"]} for identifier in ("BR-002", "BR-003")],
                "regression_owners": [{"candidate_id": "S001-C001", "requirement_id": "BR-003"}]})
            await kwargs["validate"](report)
        flow._task.side_effect = multiple
        with self.assertRaisesRegex(ValueError, "唯一接管"):
            self.execute()
        self.assertFalse((self.run / "quality/supplements/0001/pool-plan.json").exists())
        self.assertEqual((self.root / "backend/fix.py").read_text(), "fixed\n")

    def test_successful_original_completion_cannot_be_reopened(self):
        for name, result in (("complete", {"status": "success"}), ("local-completion", {"data": {"versions": {}}})):
            path = self.run / f"quality/{name}.json"
            flow._write(path, result)
            before = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "成功收口"):
                self.begin()
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse((self.run / "quality/supplements").exists())
            path.unlink()

    def test_finish_rejects_unknown_head_before_intent_and_recovers_after_correction(self):
        self.merge_supplement()
        path = self.root / "backend"
        approved = git(path, "rev-parse", "HEAD")
        git(path, "commit", "--allow-empty", "-m", "fix: 未知后续提交")
        with patch.object(flow, "_task", side_effect=AssertionError("非法版本不调用 Agent")):
            with self.assertRaisesRegex(RuntimeError, "合并结果"):
                self.execute()
        self.assertFalse((self.run / "quality/supplements/0001/coverage-intent.json").exists())
        # 只恢复本测试创建的空提交；真实产品入口不执行 reset。
        git(path, "reset", "--soft", approved)
        self.drive_real_supplement_exchange()
        self.assertTrue(flow.is_completed(self.state))

    def drive_real_supplement_exchange(self, *, events=None, fail_new_decision=False, resume_message=None):
        from common import agent_decision_loop as loop
        from common.claude_agent import ClaudeRunResult
        from common.decision import AgentDecision
        from model_policy import AgentProfile
        events = [] if events is None else events
        decision = AgentDecision(verdict="completed", answer="", reason="完成当前交接", required_inputs=[])

        async def agent(prompt, **kwargs):
            events.append(("agent", prompt))
            self.assertEqual(kwargs["resume_session_id"], "original-session")
            return ClaudeRunResult(
                init={"cwd": str(self.root), "skills": ["product-experience-audit"], "slash_commands": ["product-experience-audit"]},
                text="当前合并版本的新补证回复", result_subtype="success", is_error=False,
                session_id="original-session", stop_reason=None, num_turns=1, total_cost_usd=0, exception=None,
            )

        async def decide(messages, *args, **kwargs):
            events.append(("decision", messages[-1]["content"]))
            if fail_new_decision and messages[-1]["content"] == "当前合并版本的新补证回复":
                raise RuntimeError("模拟新回复落盘后裁决失败")
            return decision.model_dump(), 1, decision.model_dump_json()

        async def real_loop(*args, **kwargs):
            return await loop.run_agent_decision_loop(*args, **kwargs, agent_runner=agent,
                                                      decision_runner=decide, config_loader=lambda: object())

        with patch.object(flow, "_task", side_effect=run_quality_task), \
             patch.object(flow, "run_agent_decision_loop", side_effect=real_loop), \
             patch.object(loop, "get_agent_profile", return_value=AgentProfile("planning", "test-model", "high")):
            asyncio.run(flow.run_node(self.run, self.state, resume_message=resume_message))
        return events

    def test_finish_old_pending_reply_decision_cannot_count_as_new_version_evidence(self):
        self.merge_supplement()
        # 真实循环入口：旧回复已落盘，但旧负责人裁决尚未落盘。
        before = flow._read(self.run / f"conversations/{self.key}.json")["messages"]
        self.assertEqual(before[-1]["role"], "user")
        events = self.drive_real_supplement_exchange()
        self.assertEqual([event[0] for event in events], ["decision", "agent", "decision"])
        after = flow._read(self.run / f"conversations/{self.key}.json")["messages"]
        self.assertEqual(after[:len(before)], before)
        intent = flow._read(self.run / "quality/supplements/0001/coverage-intent.json")
        self.assertEqual(events[1][1], intent["prompt"])
        self.assertEqual(events[-1][1], "当前合并版本的新补证回复")
        self.assertTrue(flow.is_completed(self.state))

    def test_finish_does_not_replay_old_one_time_approval(self):
        self.merge_supplement()
        path = self.run / f"conversations/{self.key}.json"
        messages = flow._read(path)["messages"]
        old_prompt = "只批准执行一次第3次检查；已消费，不得重做"
        messages.append({"role": "assistant", "content": old_prompt})
        flow._write(path, {"messages": messages})
        # SDK 无最终正文的断流现场，保留失败结果而不改写旧消息。
        self.state[self.key] = {"last_agent_result": {"subtype": None, "session_id": "original-session"}}
        events = self.drive_real_supplement_exchange()
        self.assertEqual([event[0] for event in events], ["agent", "decision"])
        intent = flow._read(self.run / "quality/supplements/0001/coverage-intent.json")
        self.assertEqual(events[0][1], intent["prompt"])
        self.assertNotEqual(events[0][1], old_prompt)
        self.assertEqual(flow._read(path)["messages"][:len(messages)], messages)
        self.assertTrue(flow.is_completed(self.state))

    def test_finish_new_reply_pending_decision_reuses_exchange_without_sdk_call(self):
        self.merge_supplement()
        events = []
        with self.assertRaises(RuntimeError):
            self.drive_real_supplement_exchange(events=events, fail_new_decision=True)
        self.assertEqual([event[0] for event in events], ["decision", "agent", "decision"])
        intent_path = self.run / "quality/supplements/0001/coverage-intent.json"
        intent_bytes = intent_path.read_bytes()
        self.assertFalse((self.run / "quality/supplements/0001/coverage.json").exists())
        self.state = read_state(self.run)
        events = self.drive_real_supplement_exchange()
        self.assertEqual([event[0] for event in events], ["decision"])
        self.assertEqual(intent_path.read_bytes(), intent_bytes)
        self.assertTrue(flow.is_completed(self.state))

    def test_finish_delivers_owner_message_with_current_version_instruction(self):
        self.merge_supplement()
        message = flow.ResumeMessage(self.key, "只补剩余证据，保留已有结果")
        events = self.drive_real_supplement_exchange(resume_message=message)
        self.assertTrue(message.consumed)
        prompts = [content for kind, content in events if kind == "agent"]
        self.assertEqual(len(prompts), 1)
        intent = flow._read(self.run / "quality/supplements/0001/coverage-intent.json")
        self.assertEqual(prompts[0], intent["prompt"] + "\n\n负责人补充：\n" + message.content)
        self.assertTrue(flow.is_completed(self.state))

    def test_supplement_cli_entry(self):
        from run_quality import parse_args
        args = parse_args(["--resume", "quality", "--supplement-file", str(self.input_file)])
        self.assertEqual(args.supplement_file, self.input_file)
        invalid = [
            ["--source-run", "source", "--run-id", "new"],
            ["--resume", "quality", "--node", "quality:complete"],
            ["--resume", "quality", "--resume-message-file", "message.md"],
        ]
        with redirect_stderr(io.StringIO()):
            for arguments in invalid:
                with self.assertRaises(SystemExit):
                    parse_args([*arguments, "--supplement-file", str(self.input_file)])


if __name__ == "__main__":
    unittest.main()
