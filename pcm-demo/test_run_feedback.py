from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_all
import run_feedback
import run_step
from common.coordination import (
    acquire_execution_locks, acquire_product_lock, claim_product, ensure_runtime,
    inherited_lock_argument, lock_status, product_key, release_product, run_lock_path,
)
from common.files import write_json
from common.state import create_run_dir, read_state, write_state
from common.timing import _read_timings, StepTiming
from feedback import workflow


class FeedbackCLITests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.runs = self.root / "runs"
        self.coordination = self.runs / ".coordination"
        self.product = self.root / "product"
        self.product.mkdir()
        self.stack.enter_context(patch("common.coordination._ports_bindable", return_value=True))
        self.key, self.product = product_key(self.product)
        record = claim_product(self.coordination, "owner", self.key, self.product)
        ensure_runtime(self.product, self.key, "owner", record)
        for command in (("init", "-b", "main"), ("config", "user.name", "Test"),
                        ("config", "user.email", "test@example.com"), ("add", "."),
                        ("commit", "--allow-empty", "-m", "fixture")):
            subprocess.run(["git", *command], cwd=self.product, check=True, capture_output=True)
        self.source = {
            "run_id": "source", "status": "success", "workflow": "product_quality",
            "phase": "product_quality_iteration", "current_node": "quality:completed",
            "step": None, "current_step": None, "active_requirement": None,
            "requirement_cycle": None, "blocked": None, "error": None,
            "workspace": {"root": str(self.root), "final_path": str(self.product)},
            "applicable_repositories": ["root"],
            "repositories": [{"name": "root", "path": str(self.product)}],
            "requirement_registry": {"schema_version": 1, "requirements": [
                {"id": "BR-001", "title": "历史需求", "order": 1, "depends_on": [],
                 "status": "completed", "completion": {"step": 18}},
            ]},
            "quality": {"round": 1, "batch_requirement_ids": []},
            "coordination": {"schema_version": 1, "execution_run_id": "source", "claim_phase": "attached",
                             "owner_run_id": "owner", "product_key": self.key, "product_path": str(self.product),
                             "port_slot": record["port_slot"], "ports": record["ports"],
                             "runtime_path": ".pcm/runtime.json"},
        }
        write_state(create_run_dir(self.runs, "source"), self.source)
        self.feedback = self.root / "feedback.txt"
        self.original = "  保存原反馈\r\n表单失败后恢复任务\n"
        self.feedback.write_bytes(self.original.encode())
        self.before = self.snapshot()
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        for item in (
            patch.object(run_all, "RUNS_DIR", self.runs),
            patch.object(run_all, "COORDINATION_ROOT", self.coordination),
            patch.object(run_step, "DEMO_ROOT", self.root),
            patch.object(run_feedback, "load_settings", return_value=SimpleNamespace(pcm_max_concurrent_projects=2)),
            patch.object(run_step, "load_settings", return_value=SimpleNamespace(pcm_max_concurrent_projects=2)),
            patch.object(run_feedback, "load_model_policy", return_value=SimpleNamespace(steps={
                task: "test" for task in ("feedback_prepare", "feedback_triage", "feedback_route", "feedback_pool")
            })),
            patch.object(run_feedback, "_model_policy_snapshot", return_value="snapshot"),
            patch.object(run_feedback, "_model_policy_table", return_value="policy"),
            redirect_stdout(self.stdout), redirect_stderr(self.stderr),
        ):
            self.stack.enter_context(item)

    def snapshot(self):
        paths = list((self.runs / "source").rglob("*"))
        paths += [self.coordination / "products.json", self.product / ".pcm/runtime.json", self.product / ".gitignore"]
        return {str(path): path.read_bytes() for path in paths if path.is_file()}

    def arguments(self, run_id="feedback"):
        return ["--source-run", "source", "--run-id", run_id, "--feedback-file", str(self.feedback)]

    def create(self, extra=()):
        with patch.object(run_feedback, "_drive", return_value=0):
            self.assertEqual(run_feedback.main(self.arguments() + list(extra)), 0, self.stderr.getvalue())
        return self.runs / "feedback"

    async def complete(self, path, state, **kwargs):
        state.update(status="success", current_node="feedback:completed", blocked=None, error=None)
        write_state(path, state)
        return {"status": "success"}

    def test_input_is_saved_once_and_resume_uses_saved_text_not_changed_originals(self):
        attachment = self.root / "screenshot.png"
        attachment.write_bytes(b"image fixture")
        intent = self.root / "intent.txt"
        intent.write_bytes("授权\r\n 本批意图\n".encode())
        path = self.create(["--attachment", str(attachment), "--intent-file", str(intent)])
        expected = {"source": str(self.feedback), "content": self.original,
                    "attachments": [str(attachment)], "intent": "授权\r\n 本批意图\n", "intent_source": str(intent)}
        self.assertEqual(run_feedback._saved_input(path), expected)
        saved = (path / "feedback/input.json").read_bytes()
        state = read_state(path)
        self.assertNotIn("content", state)
        self.assertNotIn(self.original, json.dumps(state, ensure_ascii=False))
        self.assertEqual(state["coordination"]["owner_run_id"], "owner")
        self.assertNotIn("round", state["feedback"])
        self.assertEqual(state["feedback"]["baseline_requirement_ids"], ["BR-001"])
        self.assertEqual(attachment.read_bytes(), b"image fixture")
        self.feedback.write_text("下一批诉求")
        intent.unlink()
        attachment.unlink()
        async def check_input(path, state, **kwargs):
            self.assertEqual(run_feedback._saved_input(path), expected)
            return await self.complete(path, state)
        with patch.object(workflow, "run_node", side_effect=check_input):
            self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:prepare"]), 0)
            self.assertEqual(run_feedback.main(["--resume", "feedback"]), 0)
        self.assertEqual((path / "feedback/input.json").read_bytes(), saved)
        self.assertEqual(self.snapshot(), self.before)
        self.assertNotIn(self.original, self.stdout.getvalue() + self.stderr.getvalue())
        timing = _read_timings(path)["steps"][0]
        self.assertEqual((timing["node"], timing["round"], timing["step"]), ("feedback:prepare", None, None))
        self.assertEqual(timing["status"], "success")

    def test_saved_input_accepts_legacy_intent_and_rejects_invalid_source_paths(self):
        path = self.create()
        saved = run_feedback._saved_input(path)
        self.assertIsNone(saved["intent_source"])
        legacy = {key: value for key, value in saved.items() if key != "intent_source"}
        write_json(path / "feedback/input.json", legacy)
        before = (path / "feedback/input.json").read_bytes()
        with patch.object(run_feedback, "_drive", return_value=0):
            self.assertEqual(run_feedback.main(["--resume", "feedback"]), 0)
        self.assertEqual(run_feedback._saved_input(path), legacy)
        self.assertEqual((path / "feedback/input.json").read_bytes(), before)
        for value in ("relative.md", "", 3, [], {}):
            with self.subTest(value=value):
                write_json(path / "feedback/input.json", {**legacy, "intent_source": value})
                with self.assertRaises(ValueError):
                    run_feedback._saved_input(path)
                with patch.object(run_feedback, "_drive") as drive:
                    self.assertEqual(run_feedback.main(["--resume", "feedback"]), 2)
                    drive.assert_not_called()

    def test_stopped_unfinished_batch_cannot_be_bypassed_with_a_fresh_run(self):
        path = self.create()
        for error, status in ((workflow.FeedbackBlocked("等待授权", ["授权"]), "blocked"),
                              (RuntimeError("执行失败"), "failed")):
            with self.subTest(status=status):
                with patch.object(workflow, "run_node", side_effect=error):
                    self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:prepare"]), 1)
                self.assertEqual(read_state(path)["status"], status)
                self.assertFalse(lock_status(run_lock_path(self.coordination, "feedback"))[0])
                previous = (path / "state.json").read_bytes()
                with patch.object(run_feedback, "_drive") as drive:
                    self.assertEqual(run_feedback.main(self.arguments("next")), 2)
                    drive.assert_not_called()
                self.assertFalse((self.runs / "next").exists())
                self.assertEqual((path / "state.json").read_bytes(), previous)
                self.assertEqual(self.snapshot(), self.before)
                self.assertIn("--resume feedback", self.stderr.getvalue())
        # 模拟节点子进程在保存 running 后被中断，执行锁已释放。
        state = read_state(path)
        state.update(status="running", blocked=None, error=None)
        write_state(path, state)
        self.assertEqual(run_feedback.main(self.arguments("next")), 2)
        self.assertFalse((self.runs / "next").exists())
        with patch.object(workflow, "run_node", side_effect=self.complete):
            self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:prepare"]), 0)
        self.assertTrue(workflow.is_completed(read_state(path)))
        with patch.object(run_feedback, "_drive", return_value=0):
            self.assertEqual(run_feedback.main(self.arguments("next")), 0)
        self.assertEqual(self.snapshot(), self.before)

    def test_unfinished_scan_holds_product_lock_and_ignores_other_products_and_workflows(self):
        other_product = self.root / "other-product"
        other_product.mkdir()
        other_key, _ = product_key(other_product)
        for run_id, product, kind in (("other-feedback", other_key, "product_feedback"),
                                      ("same-quality", self.key, "product_quality"),
                                      ("same-phase-one", self.key, None)):
            state = copy.deepcopy(self.source)
            state.update(run_id=run_id, status="running", workflow=kind, current_node="feedback:prepare")
            state["coordination"]["product_key"] = product
            write_state(create_run_dir(self.runs, run_id), state)
        scan = run_feedback._reject_unfinished_feedback
        def inspect(key):
            self.assertEqual(key, self.key)
            self.assertFalse((self.runs / "feedback").exists())
            with self.assertRaises(RuntimeError):
                release_product(self.coordination, self.product)
            scan(key)
        with patch.object(run_feedback, "_reject_unfinished_feedback", side_effect=inspect) as checked:
            self.create()
        checked.assert_called_once_with(self.key)
        self.assertEqual(self.snapshot(), self.before)

    def test_invalid_inputs_do_not_create_run_or_call_source_factory(self):
        directory = self.root / "directory"
        directory.mkdir()
        invalid = self.root / "invalid.txt"
        invalid.write_bytes(b"secret text\xff")
        empty = self.root / "empty.txt"
        empty.write_text(" \r\n")
        absent = self.root / "absent"
        cases = [self.arguments()[:-1] + [str(path)] for path in (directory, invalid, empty, absent)]
        cases += [self.arguments() + [flag, str(path)] for flag, path in (
            ("--attachment", directory), ("--attachment", absent), ("--intent-file", invalid),
        )]
        for argv in cases:
            with self.subTest(argv=argv), patch.object(workflow, "new_state") as factory:
                self.assertEqual(run_feedback.main(argv), 2)
                factory.assert_not_called()
                self.assertFalse((self.runs / "feedback").exists())
        self.assertNotIn("secret text", self.stderr.getvalue())

    def test_invalid_cli_rejects_resume_input_and_foreign_nodes(self):
        cases = (["--source-run", "source", "--run-id", "feedback"],
                 ["--source-run", "source", "--feedback-file", str(self.feedback)],
                 ["--resume", "feedback", "--node", "quality:prepare"],
                 self.arguments() + ["--node", "feedback:prepare"],
                 self.arguments() + ["--resume-message-file", str(self.feedback)])
        for flag in ("--run-id", "--feedback-file", "--attachment", "--intent-file"):
            cases += (["--resume", "feedback", flag, str(self.feedback)],)
        for argv in cases:
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                run_feedback.parse_args(argv)

    def test_rejects_invalid_source_before_creating_run(self):
        for changes in ({"run_id": "different"}, {"status": "blocked"},
                        {"workflow": "phase_1"}, {"current_node": "quality:prepare"},
                        {"active_requirement": "BR-001"}, {"requirement_cycle": {}},
                        {"requirement_registry": {"requirements": [{"id": "BR-001", "status": "pending"}]}},
                        {"coordination": None}):
            with self.subTest(changes=changes):
                source = copy.deepcopy(self.source)
                source.update(changes)
                write_state(self.runs / "source", source)
                self.assertEqual(run_feedback.main(self.arguments()), 2)
                self.assertFalse((self.runs / "feedback").exists())

    def test_completed_feedback_source_preserves_identity(self):
        source = copy.deepcopy(self.source)
        source.update(workflow="product_feedback", phase="product_feedback_iteration", current_node="feedback:completed")
        source["feedback"] = {"entry_versions": {}, "baseline_requirement_ids": ["BR-001"], "batch_requirement_ids": []}
        write_state(self.runs / "source", source)
        before = self.snapshot()
        path = self.create()
        self.assertEqual(read_state(path)["source_run_id"], "source")
        self.assertEqual(self.snapshot(), before)

    def test_existing_run_wrong_node_and_missing_saved_input_never_overwrite(self):
        path = self.create()
        before = (path / "state.json").read_bytes()
        self.assertEqual(run_feedback.main(self.arguments()), 2)
        self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:triage"]), 2)
        self.assertEqual((path / "state.json").read_bytes(), before)
        (path / "feedback/input.json").unlink()
        with patch.object(workflow, "run_node") as execute:
            self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:prepare"]), 2)
            execute.assert_not_called()
        self.assertEqual((path / "state.json").read_bytes(), before)

    def test_attachment_failure_creates_no_run(self):
        with patch.object(run_feedback, "attach_product", side_effect=OSError("本地读写错误")):
            self.assertEqual(run_feedback.main(self.arguments()), 2)
        self.assertFalse((self.runs / "feedback").exists())
        self.assertEqual(self.snapshot(), self.before)

    def assert_rebuild_after_initialization_failure(self, operation):
        with patch.object(run_feedback, operation, side_effect=OSError("初始化读写失败")), \
             patch.object(workflow, "record_failure") as failure:
            self.assertEqual(run_feedback.main(self.arguments()), 1)
            failure.assert_not_called()
        path = self.runs / "feedback"
        self.assertTrue(path.is_dir())
        self.assertFalse((path / "state.json").exists())
        self.assertEqual((path / "feedback/input.json").is_file(), operation == "write_state")
        self.assertNotIn("--resume feedback", self.stderr.getvalue())
        self.assertIn("--run-id", self.stderr.getvalue())
        leftovers = {str(item): item.read_bytes() for item in path.rglob("*") if item.is_file()}
        self.assertEqual(run_feedback.main(self.arguments()), 2)
        with patch.object(run_feedback, "_drive", return_value=0):
            self.assertEqual(run_feedback.main(self.arguments("rebuilt")), 0)
        self.assertEqual(run_feedback._saved_input(self.runs / "rebuilt")["content"], self.original)
        self.assertEqual({str(item): item.read_bytes() for item in path.rglob("*") if item.is_file()}, leftovers)
        self.assertEqual(self.snapshot(), self.before)

    def test_input_write_failure_can_rebuild_under_new_id(self):
        self.assert_rebuild_after_initialization_failure("write_json")

    def test_state_publication_failure_can_rebuild_under_new_id(self):
        self.assert_rebuild_after_initialization_failure("write_state")

    def test_interruption_after_input_before_state_allows_new_id_without_cleanup(self):
        with patch.object(run_feedback, "write_state", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            run_feedback.main(self.arguments())
        path = self.runs / "feedback"
        self.assertFalse((path / "state.json").exists())
        saved_input = (path / "feedback/input.json").read_bytes()
        with patch.object(run_feedback, "_drive", return_value=0):
            self.assertEqual(run_feedback.main(self.arguments("rebuilt")), 0)
        self.assertEqual((path / "feedback/input.json").read_bytes(), saved_input)
        self.assertEqual(self.snapshot(), self.before)

    def test_numeric_steps_attach_without_claiming_and_product_lock_is_exclusive(self):
        self.create()
        with patch.object(run_step, "claim_product", side_effect=AssertionError), patch.object(run_step, "ensure_runtime", side_effect=AssertionError):
            for step in range(13, 19):
                with self.subTest(step=step), run_step._prepare_execution_locks(SimpleNamespace(run_id="feedback", step=step)):
                    with self.assertRaises(RuntimeError):
                        release_product(self.coordination, self.product)
        with self.assertRaises(RuntimeError):
            run_step._prepare_execution_locks(SimpleNamespace(run_id="feedback", step=12))
        with acquire_execution_locks(self.coordination, "feedback", 2):
            self.assertEqual(run_feedback.main(["--resume", "feedback"]), 2)
        with acquire_product_lock(self.coordination, "owner", self.key, self.product):
            self.assertEqual(run_feedback.main(["--resume", "feedback"]), 2)
        self.assertEqual(self.snapshot(), self.before)

    def test_real_child_adopts_all_locks_and_releases_only_its_handles(self):
        self.create()
        script = '''
import sys
from pathlib import Path
from common.coordination import adopt_execution_locks, lock_status, release_product
with adopt_execution_locks(Path(sys.argv[1]), 'feedback', sys.argv[3], 2) as locks:
    assert all(lock_status(item.path)[0] for item in (locks.run, locks.capacity, locks.product))
    try:
        release_product(Path(sys.argv[1]), Path(sys.argv[2]))
    except RuntimeError:
        pass
    else:
        raise AssertionError('release')
'''
        with run_step._prepare_execution_locks(SimpleNamespace(run_id="feedback", step=14)) as locks:
            child = subprocess.run([sys.executable, "-c", script, str(self.coordination), str(self.product), inherited_lock_argument(locks)],
                                   cwd=Path(run_feedback.__file__).parent, pass_fds=locks.file_descriptors(),
                                   capture_output=True, text=True, timeout=15)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertTrue(lock_status(locks.run.path)[0])
            self.assertTrue(lock_status(locks.product.path)[0])
        self.assertFalse(lock_status(run_lock_path(self.coordination, "feedback"))[0])
        self.assertEqual(self.snapshot(), self.before)

    def test_child_failure_and_no_progress_stop_without_faking_success(self):
        path = self.create()
        before = (path / "state.json").read_bytes()
        for code, expected in ((143, 143), (1, 1), (0, 2)):
            with self.subTest(code=code), patch.object(run_all, "run_child", return_value=code) as child:
                self.assertEqual(run_feedback.main(["--resume", "feedback"]), expected)
                self.assertIn("feedback:prepare", child.call_args.args[0])
                self.assertEqual(child.call_args.args[2][run_all._MODEL_POLICY_SNAPSHOT_ENV], "snapshot")
                self.assertEqual((path / "state.json").read_bytes(), before)

    def test_drive_dispatches_numeric_steps_then_returns_to_feedback(self):
        path = self.create()
        state = read_state(path)
        state.update(current_node="feedback:select_requirement", step=13, current_step=13)
        write_state(path, state)
        seen = []
        nodes = {14: "trd_design", 15: "development", 16: "rule_retrospective", 17: "commit", 18: "merge"}
        def child(command, *unused):
            current = read_state(path)
            if "--step" in command:
                step = int(command[command.index("--step") + 1])
                seen.append(step)
                if step == 18:
                    current.update(current_node="feedback:select_requirement", step=None, current_step=None)
                else:
                    following = step + 1
                    current.update(current_node=f"requirement:{following}_{nodes[following]}", step=following, current_step=following)
            else:
                seen.append(command[command.index("--node") + 1])
                current.update(status="success", current_node="feedback:completed")
            write_state(path, current)
            return 0
        with patch.object(run_all, "run_child", side_effect=child):
            self.assertEqual(run_feedback.main(["--resume", "feedback"]), 0)
        self.assertEqual(seen, [13, 14, 15, 16, 17, 18, "feedback:select_requirement"])

    def test_only_requested_channel_errors_retry_under_same_lock(self):
        path = self.create()
        calls = []
        async def attempt(path, state, **kwargs):
            calls.append(lock_status(run_lock_path(self.coordination, "feedback"))[0])
            if len(calls) == 1:
                raise run_step.AgentExecutionFailure("通道错误", "logs/failure.json", retry_requested=True)
            return await self.complete(path, state)
        with patch.object(workflow, "run_node", side_effect=attempt), patch.object(run_step.time, "sleep") as sleep:
            self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:prepare"]), 0)
        self.assertEqual(calls, [True, True])
        sleep.assert_called_once_with(30)
        self.assertTrue((path / "logs/feedback-prepare-error.json").is_file())

    def test_remote_completion_uses_same_node_for_full_and_named_resume_without_sdk_retry(self):
        path = self.create()
        state = read_state(path)
        state.update(current_node="feedback:complete", remote_sync={"enabled": True, "project_name": "product", "repositories": {}})
        write_state(path, state)
        local = {"data": {"versions": {"root": "a" * 40}}, "summary": "反馈文档已提交"}
        registry = copy.deepcopy(state["requirement_registry"])
        seen = []
        def child(command, *unused):
            node = command[command.index("--node") + 1]
            seen.append(node)
            return run_feedback._execute_node(SimpleNamespace(resume="feedback", node=node), None, StepTiming())
        with patch.object(workflow, "_local_completion", return_value=local) as prepare, \
             patch.object(workflow, "sync_repositories", side_effect=[RuntimeError("root 网络失败"), workflow.RemoteBlocked("root 缺少 SSH 权限"), []]) as sync, \
             patch.object(run_step.time, "sleep") as sleep, \
             patch.object(run_all, "run_child", side_effect=child):
            self.assertEqual(run_feedback.main(["--resume", "feedback"]), 1)
            self.assertEqual(read_state(path)["status"], "failed")
            self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:complete"]), 1)
            self.assertEqual(read_state(path)["status"], "blocked")
            self.assertEqual(read_state(path)["requirement_registry"], registry)
            self.assertEqual(run_feedback.main(["--resume", "feedback"]), 0)
            self.assertTrue(workflow.is_completed(read_state(path)))
            self.assertEqual(sync.call_count, 3)
            prepare.assert_called_once()
            sleep.assert_not_called()
        self.assertEqual(seen, ["feedback:complete", "feedback:complete"])

    def test_generic_error_does_not_retry_and_blocked_keeps_three_state_contract(self):
        path = self.create()
        for error, status in ((RuntimeError("本地错误"), "failed"),
                              (workflow.FeedbackBlocked("需要外部输入", ["授权"]), "blocked")):
            with self.subTest(status=status), patch.object(workflow, "run_node", side_effect=error), patch.object(run_step.time, "sleep") as sleep:
                self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:prepare"]), 1)
                self.assertEqual(read_state(path)["status"], status)
                sleep.assert_not_called()

    def test_resume_message_requires_original_session_and_preserves_bytes(self):
        path = self.create()
        message_file = self.root / "message.txt"
        message_file.write_bytes("补证\r\n  保留正文\n".encode())
        argv = ["--resume", "feedback", "--node", "feedback:prepare", "--resume-message-file", str(message_file)]
        before = (path / "state.json").read_bytes()
        with patch.object(workflow, "run_node") as execute:
            self.assertEqual(run_feedback.main(argv), 2)
            execute.assert_not_called()
        self.assertEqual((path / "state.json").read_bytes(), before)
        state = read_state(path)
        state.update(status="running", claude_sessions={"feedback_prepare": "session-original"},
                     decision_conversations={"feedback_prepare": {"path": "conversations/feedback_prepare.json"}})
        write_state(path, state)
        (path / "conversations").mkdir()
        write_json(path / "conversations/feedback_prepare.json", {"messages": [
            {"role": "system", "content": "system"}, {"role": "assistant", "content": "原始任务"},
        ]})
        async def consume(path, state, *, resume_message):
            self.assertEqual(state["claude_sessions"][resume_message.target_key], "session-original")
            self.assertEqual(resume_message.content, "补证\r\n  保留正文\n")
            resume_message.consumed = True
            return await self.complete(path, state)
        with patch.object(workflow, "run_node", side_effect=consume):
            self.assertEqual(run_feedback.main(argv), 0, self.stderr.getvalue())

    def test_saved_success_is_protected_when_state_advance_fails(self):
        path = self.create()
        result_path = path / "feedback/prepare.json"
        write_json(result_path, {"phase": workflow.PHASE, "node": "feedback:prepare", "status": "success",
                                 "data": {"registry": self.source["requirement_registry"], "versions": {}}})
        before = result_path.read_bytes()
        with patch.object(workflow, "_replace_state", side_effect=OSError("状态落盘中断")):
            self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:prepare"]), 1)
        self.assertEqual(result_path.read_bytes(), before)
        self.assertEqual(read_state(path)["current_node"], "feedback:prepare")
        self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:prepare"]), 0)
        self.assertEqual(read_state(path)["current_node"], "feedback:triage")
        self.assertEqual(result_path.read_bytes(), before)

    def test_missing_feedback_model_tasks_reject_before_run_creation(self):
        with patch.object(run_feedback, "load_model_policy", return_value=SimpleNamespace(steps={"15": "building"})):
            self.assertEqual(run_feedback.main(self.arguments()), 2)
        self.assertFalse((self.runs / "feedback").exists())

    def test_selection_position_must_match_saved_numeric_handoff(self):
        state = {"current_node": "feedback:select_requirement", "step": None, "current_step": None}
        self.assertIsNone(run_feedback._numeric_step(state))
        state.update(step=13, current_step=13)
        self.assertEqual(run_feedback._numeric_step(state), 13)
        state["current_step"] = 14
        with self.assertRaises(RuntimeError):
            run_feedback._numeric_step(state)
        for node in ("quality:prepare", "unknown", "requirement:13_select_requirement"):
            with self.subTest(node=node), self.assertRaises(RuntimeError):
                run_feedback._numeric_step({"current_node": node})

    def test_numeric_failure_keeps_feedback_phase_and_scoped_result(self):
        path = self.create()
        definitions = (
            (14, "fourteen", "trd_design", "trd_design", "requirement:14_trd_design"),
            (15, "fifteen", "development", "development", "requirement:15_development"),
            (16, "sixteen", "rule_retrospective", "rule_retrospective", "requirement:16_rule_retrospective"),
            (17, "seventeen", "requirement_commit", "requirement_commit", "requirement:17_commit"),
            (18, "eighteen", "requirement_merge", "requirement_merge", "requirement:18_merge"),
        )
        scope = {"requirement_id": "BR-002", "branch": "requirement/BR-002", "trd_path": "trd.md",
                 "development_session_id": "session", "trd_session_id": "trd-session"}
        for step, name, failure, success, node in definitions:
            with self.subTest(step=step):
                state = read_state(path)
                state.update(step=step, current_step=step, current_node=node, status="running")
                write_state(path, state)
                args = SimpleNamespace(step=step, run_id="feedback")
                with (
                    patch.object(run_step, f"run_step_{name}", side_effect=RuntimeError("局部失败")),
                    patch.object(run_step, f"{failure}_failure_scope", return_value=scope),
                    patch.object(run_step, f"has_{success}_success", return_value=False),
                    run_step._prepare_execution_locks(args) as locks,
                ):
                    self.assertEqual(run_step._execute(args, locks), 1)
                saved = read_state(path)
                self.assertEqual((saved["phase"], saved["current_node"], saved["status"]),
                                 ("product_feedback_iteration", node, "failed"))
                self.assertTrue((path / "steps/requirements/BR-002" / f"{step}.json").is_file())

    def test_drive_forwards_resume_message_only_to_first_child(self):
        path = self.create()
        state = read_state(path)
        state.update(status="running", claude_sessions={"feedback_prepare": "session-original"},
                     decision_conversations={"feedback_prepare": {"path": "conversations/feedback_prepare.json"}})
        write_state(path, state)
        (path / "conversations").mkdir()
        write_json(path / "conversations/feedback_prepare.json", {"messages": [
            {"role": "system", "content": "system"}, {"role": "assistant", "content": "原始任务"},
        ]})
        message = self.root / "message.txt"
        message.write_text("补证")
        commands = []
        def child(command, *unused):
            commands.append(command)
            current = read_state(path)
            current.update(status="success", current_node="feedback:triage" if len(commands) == 1 else "feedback:completed")
            write_state(path, current)
            return 0
        with patch.object(run_all, "run_child", side_effect=child):
            self.assertEqual(run_feedback.main(["--resume", "feedback", "--resume-message-file", str(message)]), 0)
        self.assertIn("--resume-message-file", commands[0])
        self.assertNotIn("--resume-message-file", commands[1])

    def test_unconsumed_resume_message_is_execution_failure(self):
        path = self.create()
        state = read_state(path)
        state.update(status="running", claude_sessions={"feedback_prepare": "original"},
                     decision_conversations={"feedback_prepare": {"path": "conversations/feedback_prepare.json"}})
        write_state(path, state)
        (path / "conversations").mkdir()
        write_json(path / "conversations/feedback_prepare.json", {"messages": [
            {"role": "system", "content": "system"}, {"role": "assistant", "content": "原始任务"},
        ]})
        async def unused(path, state, **kwargs):
            return {"status": "success"}
        with patch.object(workflow, "run_node", side_effect=unused):
            self.assertEqual(run_feedback.main(["--resume", "feedback", "--node", "feedback:prepare",
                                                "--resume-message-file", str(self.feedback)]), 1)
        self.assertEqual(read_state(path)["status"], "failed")

    def test_feedback_timing_rejects_rounds_but_quality_timing_keeps_them(self):
        timing = StepTiming()
        with self.assertRaises(ValueError):
            timing.begin_attempt(node="feedback:triage", round_number=1)
        timing.begin_attempt(node="quality:audit", round_number=1)


if __name__ == "__main__":
    unittest.main()
