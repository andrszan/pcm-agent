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
        (self.run / "conversations").mkdir(exist_ok=True)
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
        # 现场三仓是这份审计的已知基线，非补充入口吞入的未知 HEAD。
        path = self.run / "quality/rounds/0001/audit.json"
        audit = flow._read(path)
        audit["data"]["versions"] = {name: row["head"] for name, row in self.input["repositories"].items()}
        flow._write(path, audit)
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
            return fixtures.final_report(args[0], args[1], args[4], kwargs["phase_intent"])
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
            return fixtures.final_report(args[0], args[1], args[4], kwargs["phase_intent"])
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

    def drive_real_supplement_exchange(self, *, events=None, fail_new_decision=False, resume_message=None, phase_allowed=True):
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
            if messages[-1]["content"] == "当前合并版本的新补证回复":
                from common.decision import PhaseCompletionDecision
                self.assertIs(kwargs.get("output_model"), PhaseCompletionDecision)
                self.assertNotEqual(kwargs["system_prompt"], messages[0]["content"])
                self.assertIn("phase_completion_allowed", kwargs["output_model"].model_fields)
            else:
                self.assertNotIn("output_model", kwargs)
                self.assertEqual(kwargs["system_prompt"], messages[0]["content"])
            if fail_new_decision and messages[-1]["content"] == "当前合并版本的新补证回复":
                raise RuntimeError("模拟新回复落盘后裁决失败")
            result = decision
            if "output_model" in kwargs and phase_allowed != "legacy":
                from common.decision import PhaseCompletionDecision
                result = PhaseCompletionDecision(**decision.model_dump(), phase_completion_allowed=phase_allowed)
            return result.model_dump(), 1, result.model_dump_json()

        async def real_loop(*args, **kwargs):
            return await loop.run_agent_decision_loop(*args, **kwargs, agent_runner=agent,
                                                      decision_runner=decide, config_loader=lambda: object())

        with patch.object(flow, "_task", side_effect=run_quality_task), \
             patch.object(flow, "run_agent_decision_loop", side_effect=real_loop), \
             patch.object(loop, "get_agent_profile", return_value=AgentProfile("planning", "test-model", "high")), \
             patch.object(flow, "parse_response", return_value=audit_report()):
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

    def test_legacy_completed_cannot_approve_phase_completion(self):
        self.merge_supplement()
        with self.assertRaisesRegex(RuntimeError, "阶段"):
            self.drive_real_supplement_exchange(phase_allowed="legacy")
        self.assertFalse((self.run / "quality/supplements/0001/coverage.json").exists())
        self.assertFalse(flow.is_completed(self.state))

    def assert_legacy_intent_recovers(self, stage, *, with_message=False, interrupt_decision=False):
        from common.decision import AgentDecision
        self.merge_supplement()
        path = self.run / f"conversations/{self.key}.json"
        before = flow._read(path)["messages"]
        old_prompt = "旧版本只批准执行一次的补证指令"
        versions = flow.main_versions(self.state)
        old_intent_path = flow._completion_path(self.run, self.state, "coverage-intent")
        old_intent = {"versions": versions, "session_id": "original-session",
                      "anchor": json.dumps(before, ensure_ascii=False), "prompt": old_prompt}
        flow._write(old_intent_path, old_intent)
        messages = before + [{"role": "assistant", "content": old_prompt}]
        if stage != "sdk":
            messages.append({"role": "user", "content": "旧版本补证的已保存回复"})
        if stage in {"decided", "coverage"}:
            decision = AgentDecision(verdict="completed", answer="", reason="旧调查交接完成", required_inputs=[])
            messages.append({"role": "assistant", "content": decision.model_dump_json()})
        flow._write(path, {"messages": messages})
        old_files = {old_intent_path: old_intent_path.read_bytes()}
        if stage == "coverage":
            old_coverage_path = flow._completion_path(self.run, self.state, "coverage")
            flow._write(old_coverage_path, {"versions": versions, "session_id": "original-session",
                "report": json.dumps(messages, ensure_ascii=False), "input": flow.batch_metadata(self.state)["input"],
                "anchor_sha256": hashlib.sha256(old_intent["anchor"].encode()).hexdigest()})
            old_files[old_coverage_path] = old_coverage_path.read_bytes()
            local_path = flow._completion_path(self.run, self.state, "local-completion")
            flow._write(local_path, {"data": {"versions": versions}, "summary": "旧本地交接"})
            old_files[local_path] = local_path.read_bytes()
            self.state["remote_sync"] = {"enabled": True, "project_name": "fixture", "repositories": {}}
        self.state.update(status="running", error=None, blocked=None)
        write_json(self.run / "state.json", self.state)
        message = None
        if with_message:
            from common.agent_decision_loop import prepare_node_resume_message
            message_file = self.base / "phase-resume.txt"
            message_file.write_text("只补本次批准范围内尚未通过的证据")
            message = prepare_node_resume_message(self.run, self.state, "quality:complete", (self.key,), message_file)
        events = []
        with patch.object(flow, "sync_repositories") as sync:
            if interrupt_decision:
                with self.assertRaises(RuntimeError):
                    self.drive_real_supplement_exchange(events=events, resume_message=message, fail_new_decision=True)
                self.assertEqual([event[0] for event in events], ["decision", "agent", "decision"])
                self.state = read_state(self.run)
                events = self.drive_real_supplement_exchange()
                self.assertEqual([event[0] for event in events], ["decision"])
            else:
                self.drive_real_supplement_exchange(events=events, resume_message=message)
                expected = ["decision", "agent", "decision"] if stage == "pending" else ["agent", "decision"]
                self.assertEqual([event[0] for event in events], expected)
                prompts = [content for kind, content in events if kind == "agent"]
                self.assertNotIn(old_prompt, prompts)
            if stage == "coverage":
                sync.assert_called_once()
        if message:
            self.assertTrue(message.consumed)
        self.assertTrue(flow.is_completed(self.state))
        after = flow._read(path)["messages"]
        self.assertEqual(after[:len(messages)], messages)
        for saved, data in old_files.items():
            self.assertEqual(saved.read_bytes(), data)
        complete = flow._read(flow._completion_path(self.run, self.state, "complete"))
        self.assertEqual(complete["data"]["coverage"], "quality/supplements/0001/phase-coverage.json")
        self.assertEqual(complete["data"]["coverage_intent"], "quality/supplements/0001/phase-coverage-intent.json")
        self.assertTrue(complete["data"]["phase_completion_allowed"])

    def test_legacy_sdk_interruption_resumes_with_new_contract_and_owner_message(self):
        self.assert_legacy_intent_recovers("sdk", with_message=True)

    def test_legacy_pending_reply_uses_old_decision_then_recovers_new_pending_decision(self):
        self.assert_legacy_intent_recovers("pending", interrupt_decision=True)

    def test_legacy_completed_decision_does_not_approve_new_phase(self):
        self.assert_legacy_intent_recovers("decided")

    def test_legacy_saved_coverage_and_local_completion_are_preserved_on_resume(self):
        self.assert_legacy_intent_recovers("coverage")

    def test_migrated_correction_requires_exact_current_phase_coverage(self):
        self.assert_legacy_intent_recovers("coverage")
        supplied = self.clean_input(correction=True, count=1)
        self.assertEqual(supplied["correction"]["coverage"]["path"], "quality/supplements/0001/phase-coverage.json")
        before = {path: path.read_bytes() for path in self.run.rglob("*.json")}
        wrong = copy.deepcopy(supplied)
        old_path = flow._completion_path(self.run, self.state, "coverage")
        wrong["correction"]["coverage"] = {"path": old_path.relative_to(self.run).as_posix(),
                                           "sha256": hashlib.sha256(old_path.read_bytes()).hexdigest()}
        write_json(self.input_file, wrong)
        with self.assertRaisesRegex(RuntimeError, "路径"):
            self.begin()
        self.assertEqual({path: path.read_bytes() for path in self.run.rglob("*.json")}, before)
        write_json(self.input_file, supplied)
        self.begin()
        self.assertEqual(flow._batch_id(self.state), "0002")
        for path, data in before.items():
            if path.name != "state.json":
                self.assertEqual(path.read_bytes(), data)

    def test_unregistered_next_batch_cannot_adopt_unknown_downstream_artifacts(self):
        self.merge_supplement()
        supplied = self.clean_input(count=1)
        write_json(self.input_file, supplied)
        directory = self.run / "quality/supplements/0002"
        flow._write(directory / "route.json", {"status": "success", "node": "quality:route", "round": 1,
                                               "data": {"decisions": [], "ready_to_complete": True}})
        for with_input in (False, True):
            if with_input:
                flow._write(directory / "input.json", supplied)
            before = {path: path.read_bytes() for path in self.run.rglob("*.json")}
            state = copy.deepcopy(self.state)
            with self.assertRaisesRegex(RuntimeError, "无归属"):
                self.begin()
            self.assertEqual(self.state, state)
            self.assertEqual({path: path.read_bytes() for path in self.run.rglob("*.json")}, before)
        # 仅移除本测试创建的未知产物；同输入前置落盘仍允许安全重入。
        (directory / "route.json").unlink()
        self.begin()
        self.assertEqual(flow._batch_id(self.state), "0002")
        self.assertEqual(self.state["current_node"], "quality:route")

    def test_clean_input_rejects_unknown_head_even_when_manifest_matches(self):
        for _, path in flow.repositories(self.state)[1:]:
            git(path, "restore", "--", "fix.py")
        supplied = self.clean_input(count=1)
        tip = git(self.root, "rev-parse", "HEAD")
        git(self.root, "commit", "--allow-empty", "-m", "docs: 未知后续版本")
        supplied["repositories"]["root"]["head"] = git(self.root, "rev-parse", "HEAD")
        write_json(self.input_file, supplied)
        with self.assertRaisesRegex(RuntimeError, "当前版本"):
            self.begin()
        self.assertFalse((self.run / "quality/supplements").exists())
        git(self.root, "reset", "--soft", tip)
        supplied["repositories"]["root"]["head"] = tip
        supplied.pop("implementation")
        supplied.pop("validation")
        write_json(self.input_file, supplied)
        self.begin()
        self.assertEqual(flow._supplement_input(self.run, self.state), supplied)
        self.assertIsNone(flow.requirement_adoption(self.run, self.state, "BR-002"))

    def test_final_decision_saved_before_coverage_does_not_repeat_sdk(self):
        self.merge_supplement()
        write = flow._write
        def interrupt(path, value):
            if path.name == "coverage.json":
                raise OSError("阶段裁决已存、证据文件未写")
            return write(path, value)
        with patch.object(flow, "_write", side_effect=interrupt), self.assertRaises(OSError):
            self.drive_real_supplement_exchange()
        events = self.drive_real_supplement_exchange()
        self.assertEqual(events, [])
        self.assertTrue(flow.is_completed(self.state))

    def test_phase_false_null_and_legacy_coverage_never_complete(self):
        self.merge_supplement()
        for allowed in (False, None, "legacy"):
            with self.subTest(allowed=allowed), self.assertRaisesRegex(RuntimeError, "阶段"):
                self.drive_real_supplement_exchange(phase_allowed=allowed)
            self.assertFalse(flow.is_completed(self.state))
            self.assertFalse(flow._completion_path(self.run, self.state, "coverage").exists())
            # 仅隔离 fixture 恢复到该次已保存的新回复，重新测试裁决，不重发 SDK。
            path = self.run / f"conversations/{self.key}.json"
            value = flow._read(path)
            value["messages"].pop()
            flow._write(path, value)
        self.drive_real_supplement_exchange()
        coverage_path = flow._completion_path(self.run, self.state, "coverage")
        coverage = flow._read(coverage_path)
        coverage.pop("phase_completion_allowed")
        flow._write(coverage_path, coverage)
        with self.assertRaisesRegex(RuntimeError, "阶段"):
            flow._local_completion(self.run, self.state)

    def clean_input(self, *, correction=False, count=3):
        supplied = copy.deepcopy(self.input)
        supplied.update(mode="clean", implementation="", validation=[], findings=[
            {**self.input["findings"][0], "title": f"新增真实发现 {index}"} for index in range(count)])
        supplied["repositories"] = {name: {"head": git(path, "rev-parse", "HEAD"), "changes": []}
                                    for name, path in flow.repositories(self.state)}
        messages = flow._read(self.run / f"conversations/{self.key}.json")["messages"]
        index = max(i for i, row in enumerate(messages) if row["role"] == "user")
        content = messages[index]["content"]
        supplied["finding_source"] = {"message_index": index, "sha256": hashlib.sha256(content.encode()).hexdigest(), "quote": content}
        if correction:
            complete_path = flow._completion_path(self.run, self.state, "complete")
            coverage_path = self.run / flow._read(complete_path)["data"]["coverage"]
            supplied["correction"] = {
                name: {"path": path.relative_to(self.run).as_posix(),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for name, path in (("complete", complete_path), ("coverage", coverage_path))}
            supplied["correction"].update(
                versions={name: row["head"] for name, row in supplied["repositories"].items()},
                last_reply=copy.deepcopy(supplied["finding_source"]), approval_source=copy.deepcopy(supplied["owner_decision"]),
                included_findings=list(range(count)), reason="旧负责人只认可调查交接，用户批准更正误收口并纳入这些发现")
        return supplied

    def configure_clean_batch(self):
        from quality.models import PoolPlan, RoutingReport
        audit = flow._batch_audit(self.run, self.state)
        self.routing.side_effect = None
        self.routing.return_value = RoutingReport.model_validate({
            "summary": "按依赖正式纳入", "decisions": [
                {"candidate_id": row["id"], "action": "include", "reason": "用户明确纳入", "covered_by": None}
                for row in audit["candidates"]], "document_changes": [], "ready_to_complete": False})
        prior = [{key: row[key] for key in ("id", "title", "order", "depends_on")}
                 for row in self.state["requirement_registry"]["requirements"]]
        added = []
        for index, row in enumerate(audit["candidates"]):
            order = len(prior) + index + 1
            added.append({"id": f"BR-{order:03d}", "title": row["title"], "order": order,
                          "depends_on": [added[-1]["id"] if added else prior[-1]["id"]]})
        self.catalog_override = prior + added
        plan = PoolPlan.model_validate({"summary": "依赖拆分", "requirements": [
            {"requirement_id": row["id"], "candidate_ids": [candidate["id"]]}
            for row, candidate in zip(added, audit["candidates"])], "regression_owners": [
            {"candidate_id": candidate["id"], "requirement_id": row["id"]}
            for row, candidate in zip(added, audit["candidates"])]})
        async def task(run_dir, state, key, task, prompt, responsibility, **kwargs):
            self.calls.append(key)
            if key == f"quality_pool_s{flow._batch_id(state)}":
                self.backlog.write_text(self.backlog.read_text() + "\n".join(row["id"] + " " + row["title"] for row in added))
                await kwargs["validate"](plan)
                return "已拆分真实依赖", plan
            if key.startswith("quality_pool_commit_"):
                git(self.root, "add", "docs/backlog/backlog.md")
                git(self.root, "commit", "-m", "docs: 正式追加需求")
                return "已提交", None
            if kwargs.get("phase_intent"):
                return fixtures.final_report(run_dir, state, prompt, kwargs["phase_intent"])
            raise AssertionError(key)
        flow._task.side_effect = task
        return [row["id"] for row in added]

    def merge_clean_requirement(self, identifier):
        from common.state import write_requirement_step_result
        from steps.step_13_select_requirement import step as selection
        from steps.step_17_commit import step as commit
        from steps.step_18_merge import step as merge
        self.execute()
        baseline = flow.requirement_baseline(self.run, self.state, identifier)
        selection.run(self.run, self.state)
        self.assertEqual(self.state["active_requirement"], identifier)
        self.assertNotIn("adoption_input", self.state["requirement_cycle"])
        supplied = flow._supplement_input(self.run, self.state)
        evidence = flow.requirement_evidence(self.run, self.state)
        for source in ("owner_decision", "handoff_source"):
            self.assertIn(supplied[source]["path"], evidence)
            self.assertIn(supplied[source]["quote"], evidence)
        for remaining in supplied["remaining"]:
            self.assertIn(remaining, evidence)
        self.assertEqual({name: row["base_sha"] for name, row in self.state["requirement_cycle"]["repositories"].items()}, baseline)
        trd = f"docs/trd/{identifier}.md"
        (self.root / trd).write_text("真实临时 Git 开发交接\n")
        results = []
        for name, path in flow.repositories(self.state):
            relative = trd if name == "root" else f"{identifier}.py"
            if name != "root":
                (path / relative).write_text("实现当前需求\n")
            git(path, "add", relative)
            git(path, "commit", "-m", "fix: 当前正式需求")
            tip = git(path, "rev-parse", "HEAD")
            record = self.state["requirement_cycle"]["repositories"][name]
            record.update(tip_sha=tip, merged=False)
            results.append({"name": name, "path": "." if name == "root" else name,
                            "base_sha": record["base_sha"], "tip_sha": tip})
        self.state["requirement_cycle"].update(trd_path=trd, development_session_id="fixture-development")
        self.state.update(step=18, current_step=18, current_node="requirement:18_merge")
        write_requirement_step_result(self.run, identifier, 17, commit.result(
            "success", "隔离开发交接", requirement_id=identifier, branch=f"req/{identifier.lower()}", repositories=results))
        self.assertEqual(merge.run(self.run, self.state)["status"], "success")

    def test_correction_sources_drift_and_interrupt_are_fail_closed(self):
        self.merge_supplement()
        self.drive_real_supplement_exchange()
        supplied = self.clean_input(correction=True)
        before = {path: path.read_bytes() for path in self.run.rglob("*.json")}
        baseline = copy.deepcopy(self.state)
        mutations = [
            lambda value: value.pop("correction"),
            lambda value: value["correction"]["complete"].update(path="quality/complete.json"),
            lambda value: value["correction"]["coverage"].update(sha256="0" * 64),
            lambda value: value["correction"]["versions"].update(root="0" * 40),
            lambda value: value["correction"]["last_reply"].update(sha256="0" * 64),
            lambda value: value["correction"]["approval_source"].update(quote="不存在的用户批准"),
            lambda value: value["correction"]["included_findings"].pop(),
            lambda value: value["correction"]["approval_source"].update(path=str(self.input_file)),
        ]
        for mutate in mutations:
            invalid = copy.deepcopy(supplied)
            mutate(invalid)
            write_json(self.input_file, invalid)
            with self.assertRaises((RuntimeError, ValueError)):
                self.begin()
            self.assertEqual(self.state, baseline)
            self.assertEqual({path: path.read_bytes() for path in self.run.rglob("*.json")}, before)
        write_json(self.input_file, supplied)
        repo = self.root / "backend"
        tip = git(repo, "rev-parse", "HEAD")
        git(repo, "commit", "--allow-empty", "-m", "fix: 未知漂移")
        with self.assertRaises(RuntimeError):
            self.begin()
        self.assertFalse((self.run / "quality/supplements/0002").exists())
        git(repo, "reset", "--soft", tip)  # 仅本测试创建的临时空提交。
        with patch.object(flow, "_replace_state", side_effect=RuntimeError("输入落盘后中断")), self.assertRaises(RuntimeError):
            self.begin()
        saved = (self.run / "quality/supplements/0002/input.json").read_bytes()
        self.begin()
        self.assertEqual(saved, (self.run / "quality/supplements/0002/input.json").read_bytes())
        self.assertEqual(self.state["current_node"], "quality:route")
        for path, data in before.items():
            if path.name != "state.json":
                self.assertEqual(path.read_bytes(), data)
        self.assertEqual((self.run / "quality/supplements/0002/original-conversation.json").read_bytes(),
                         before[self.run / f"conversations/{self.key}.json"])

    def test_multiple_clean_batches_use_distinct_ids_history_and_real_git_cycles(self):
        self.state["quality"]["local_only"] = True
        self.merge_supplement()
        first_input = (self.run / "quality/supplements/0001/input.json").read_bytes()
        first_sha = flow.batch_metadata(self.state)["input_sha256"]
        self.drive_real_supplement_exchange()
        # 旧单对象没有 id 字段；下一批仍须从状态确定为 0002。
        self.state["quality"]["supplement"].pop("id")
        write_json(self.run / "state.json", self.state)
        flow._write(self.run / "quality/supplements/0099/unregistered.json", {"fixture": True})
        # 模拟旧版本只批准调查交接的历史产物；更正允许读取但不修改这些旧文件。
        path = self.run / f"conversations/{self.key}.json"
        messages = flow._read(path)["messages"]
        decision = json.loads(messages[-1]["content"])
        decision.pop("phase_completion_allowed")
        messages[-1]["content"] = json.dumps(decision)
        flow._write(path, {"messages": messages})
        coverage_path = flow._completion_path(self.run, self.state, "coverage")
        coverage = flow._read(coverage_path)
        coverage["report"] = json.dumps(messages, ensure_ascii=False)
        for field in ("decision", "facts", "phase_completion_allowed"):
            coverage.pop(field)
        flow._write(coverage_path, coverage)
        historical = {path: path.read_bytes() for path in (self.run / "quality/supplements/0001").glob("*.json")}
        for number in (2, 3):
            supplied = self.clean_input(correction=True, count=3 if number == 2 else 1)
            write_json(self.input_file, supplied)
            self.begin()
            self.assertEqual(flow._batch_id(self.state), f"{number:04d}")
            history = flow._history(self.run, self.state)
            self.assertEqual([row.get("supplement") for row in history], [None] + [f"{i:04d}" for i in range(1, number)])
            identifiers = self.configure_clean_batch()
            self.reach("quality:select_requirement")
            self.assertIn(f"quality_pool_s{number:04d}", self.calls)
            pooled = flow._prior(self.run, self.state, "pool")
            self.assertNotIn("adoption_input", pooled)
            for identifier in identifiers:
                self.merge_clean_requirement(identifier)
            self.execute()
            self.assertEqual(self.state["current_node"], "quality:complete")
            with patch.object(flow, "sync_repositories", side_effect=AssertionError("local_only 不同步")):
                self.execute()
            self.assertTrue(flow.is_completed(self.state))
            completed = flow._read(flow._completion_path(self.run, self.state, "complete"))
            self.assertEqual(completed["data"]["completed_requirement_ids"], [row["id"] for row in self.state["requirement_registry"]["requirements"]][1:])
            self.assertTrue(completed["data"]["phase_completion_allowed"])
            self.assertEqual(len(completed["data"]["corrections"]), number - 1)
            for previous in ("BR-002", identifiers[0]):
                path = self.run / f"steps/requirements/{previous}/18.json"
                saved = path.read_bytes()
                path.unlink()
                with self.assertRaises(RuntimeError):
                    flow._local_completion(self.run, self.state)
                path.write_bytes(saved)
            old_state = {**self.state, "active_requirement": "BR-002"}
            self.assertIn("S001-C001", flow.requirement_evidence(self.run, old_state))
        for path, data in historical.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual((self.run / "quality/supplements/0001/input.json").read_bytes(), first_input)
        self.assertEqual(flow._supplements(self.state)[0]["input_sha256"], first_sha)
        # 同一个旧 dirty 输入仅定位，不用最终 clean 现场重新验其 dirty 指纹。
        write_json(self.input_file, self.input)
        before = copy.deepcopy(self.state)
        self.begin()
        self.assertEqual(self.state, before)

    def test_clean_batch_rejects_unknown_first_and_later_baseline(self):
        self.merge_supplement()
        supplied = self.clean_input(count=2)
        write_json(self.input_file, supplied)
        self.begin()
        identifiers = self.configure_clean_batch()
        self.reach("quality:select_requirement")
        from steps.step_13_select_requirement import step as selection
        for identifier in identifiers:
            self.execute()
            before = copy.deepcopy(self.state)
            tip = git(self.root, "rev-parse", "HEAD")
            git(self.root, "commit", "--allow-empty", "-m", "docs: 未知 clean 提交")
            with self.assertRaisesRegex(RuntimeError, "基线"):
                selection.run(self.run, self.state)
            self.assertEqual(self.state, before)
            git(self.root, "reset", "--soft", tip)
            # helper 从非数值选择节点开始；仅恢复该临时测试的调度位置。
            self.state.update(step=None, current_step=None)
            self.merge_clean_requirement(identifier)

    def test_explicit_findings_cannot_be_excluded(self):
        self.begin()
        self.configure_supplement_tasks()
        report = self.routing.return_value
        report.decisions[0].action = "exclude"
        report.ready_to_complete = True
        with self.assertRaisesRegex(ValueError, "明确纳入"):
            self.execute()
        self.assertFalse((self.run / "quality/supplements/0001/route.json").exists())

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
