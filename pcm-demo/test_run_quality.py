from __future__ import annotations

import copy
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import run_all
import run_quality
import run_step
from common.coordination import (
    acquire_execution_locks, acquire_product_lock, adopt_execution_locks,
    attach_product, claim_product, ensure_runtime, inherited_lock_argument,
    lock_status, product_key, release_product, run_lock_path, share_product_execution_locks,
)
from common.state import create_run_dir, read_state, write_state


class QualityCLITests(unittest.TestCase):
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
        record = claim_product(self.coordination, "source", self.key, self.product)
        ensure_runtime(self.product, self.key, "source", record)
        self.source = {
            "run_id": "source", "status": "success", "workspace": {"final_path": str(self.product)},
            "coordination": {"schema_version": 1, "execution_run_id": "source", "claim_phase": "claimed",
                             "product_key": self.key, "product_path": str(self.product),
                             "port_slot": record["port_slot"], "ports": record["ports"],
                             "runtime_path": ".pcm/runtime.json"},
        }
        source_dir = create_run_dir(self.runs, "source")
        write_state(source_dir, self.source)
        (source_dir / "timings.json").write_text('{"schema_version":2,"steps":[]}')
        self.before = self.snapshot()
        self.workflow = SimpleNamespace(
            new_state=Mock(side_effect=self.new_state),
            is_completed=lambda state: state.get("current_node") == "quality:completed" and state["status"] == "success",
            node_resume_keys=lambda state: ("quality_prepare",),
            node_result_path=lambda path, state: path / "quality" / "prepare.json",
            record_failure=Mock(side_effect=self.fail),
            run_node=self.complete,
        )
        for item in (
            patch.object(run_all, "RUNS_DIR", self.runs),
            patch.object(run_all, "COORDINATION_ROOT", self.coordination),
            patch.object(run_step, "DEMO_ROOT", self.root),
            patch.object(run_quality, "_workflow", return_value=self.workflow),
            patch.object(run_quality, "load_settings", return_value=SimpleNamespace(pcm_max_concurrent_projects=1)),
            patch.object(run_step, "load_settings", return_value=SimpleNamespace(pcm_max_concurrent_projects=1)),
            patch.object(run_quality, "load_model_policy", return_value={}),
            patch.object(run_quality, "_model_policy_snapshot", return_value="snapshot"),
            patch.object(run_quality, "_model_policy_table", return_value="policy"),
            redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()),
        ):
            self.stack.enter_context(item)

    def snapshot(self):
        paths = list((self.runs / "source").rglob("*"))
        paths += [self.coordination / "products.json", self.product / ".pcm/runtime.json", self.product / ".gitignore"]
        return {str(path): path.read_bytes() for path in paths if path.is_file()}

    def new_state(self, source, source_run_id, run_id):
        return {"run_id": run_id, "workflow": "product_quality", "source_run_id": source_run_id,
                "phase": "product_quality_iteration", "current_node": "quality:prepare",
                "step": None, "current_step": None, "status": "running",
                "workspace": copy.deepcopy(source["workspace"]),
                "quality": {"round": 1, "batch_requirement_ids": []}}

    def fail(self, path, state, error):
        state.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
        write_state(path, state)
        return {"status": "failed", "error": state["error"]}

    async def complete(self, path, state, **kwargs):
        state.update(status="success", current_node="quality:completed")
        write_state(path, state)
        return {"status": "success"}

    def create(self):
        with patch.object(run_quality, "_drive", return_value=0):
            self.assertEqual(run_quality.main(["--source-run", "source", "--run-id", "quality"]), 0)
        return self.runs / "quality"

    def test_new_resume_and_single_node_leave_source_and_product_bytes_unchanged(self):
        path = self.create()
        state = read_state(path)
        self.assertEqual(state["coordination"]["owner_run_id"], "source")
        self.assertEqual(state["coordination"]["execution_run_id"], "quality")
        with patch("common.coordination.claim_product", side_effect=AssertionError("不能认领")), patch("common.coordination.ensure_runtime", side_effect=AssertionError("不能补写")):
            self.assertEqual(run_quality.main(["--resume", "quality", "--node", "quality:prepare"]), 0)
            self.assertEqual(run_quality.main(["--resume", "quality"]), 0)
        self.assertEqual(self.snapshot(), self.before)
        self.assertTrue((path / "timings.json").is_file())
        self.workflow.new_state.assert_called_once()

    def test_new_attachment_failure_reports_reason_and_result_path(self):
        stderr = io.StringIO()
        with patch.object(run_quality, "attach_product", side_effect=RuntimeError("产品正在执行")), redirect_stderr(stderr):
            code = run_quality.main(["--source-run", "source", "--run-id", "quality"])
        self.assertEqual(code, 1)
        self.assertIn("产品正在执行", stderr.getvalue())
        self.assertIn("prepare.json", stderr.getvalue())
        self.assertEqual(read_state(self.runs / "quality")["status"], "failed")
        self.assertEqual(self.snapshot(), self.before)

    def test_invalid_cli_and_wrong_node_have_no_state_write(self):
        for argv in (["--source-run", "source"], ["--resume", "q", "--run-id", "q"],
                     ["--source-run", "source", "--run-id", "q", "--node", "quality:audit"],
                     ["--resume", "q", "--max-rounds", "0"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                run_quality.parse_args(argv)
        path = self.create()
        before = (path / "state.json").read_bytes()
        self.assertEqual(run_quality.main(["--resume", "quality", "--node", "quality:audit"]), 2)
        self.assertEqual((path / "state.json").read_bytes(), before)
        self.assertEqual(run_quality.main(["--source-run", "source", "--run-id", "quality"]), 2)

    def test_direct_numeric_steps_attach_without_claim_or_runtime_write(self):
        self.create()
        args = SimpleNamespace(run_id="quality", step=14)
        with patch.object(run_step, "claim_product", side_effect=AssertionError), patch.object(run_step, "ensure_runtime", side_effect=AssertionError):
            with run_step._prepare_execution_locks(args):
                with self.assertRaises(RuntimeError):
                    release_product(self.coordination, self.product)
        self.assertEqual(self.snapshot(), self.before)
        args.step = 12
        with self.assertRaises(RuntimeError):
            run_step._prepare_execution_locks(args)

    def test_runtime_missing_or_conflicting_and_released_lease_are_not_repaired(self):
        path = self.create()
        runtime = self.product / ".pcm/runtime.json"
        original = runtime.read_bytes()
        for data in (b"{}", None):
            if data is None:
                runtime.unlink()
            else:
                runtime.write_bytes(data)
            self.assertEqual(run_quality.main(["--resume", "quality"]), 2)
            self.assertEqual(runtime.read_bytes() if runtime.exists() else None, data)
        runtime.write_bytes(original)
        release_product(self.coordination, self.product)
        with acquire_execution_locks(self.coordination, "quality", 1) as locks:
            with self.assertRaises(RuntimeError):
                attach_product(self.coordination, "quality", read_state(path), locks)

    def test_round_budget_option_is_rejected(self):
        with self.assertRaises(SystemExit):
            run_quality.parse_args(["--resume", "quality", "--max-rounds", "4"])

    def test_same_run_and_product_execution_are_exclusive(self):
        self.create()
        with acquire_execution_locks(self.coordination, "quality", 2):
            self.assertEqual(run_quality.main(["--resume", "quality"]), 2)
        with acquire_product_lock(self.coordination, "source", self.key, self.product):
            self.assertEqual(run_quality.main(["--resume", "quality"]), 2)
        self.assertEqual(self.snapshot(), self.before)

    def test_chain_shares_capacity_product_but_has_own_run_lock_in_real_child(self):
        script = '''
import sys
from pathlib import Path
from common.coordination import adopt_execution_locks, acquire_execution_locks, release_product
root, product = Path(sys.argv[1]), Path(sys.argv[2])
with adopt_execution_locks(root, 'source-quality', sys.argv[3], 1) as locks:
    assert locks.run.path.name == 'source-quality.lock'
    for run in ('source', 'source-quality', 'other'):
        try:
            acquire_execution_locks(root, run, 1)
        except RuntimeError:
            pass
        else:
            raise AssertionError(run)
    try:
        release_product(root, product)
    except RuntimeError:
        pass
    else:
        raise AssertionError('release')
'''
        with acquire_execution_locks(self.coordination, "source", 1) as parent:
            parent.product = parent.stack.enter_context(acquire_product_lock(self.coordination, "source", self.key, self.product))
            with share_product_execution_locks(self.coordination, "source-quality", parent) as shared:
                self.assertEqual(shared.capacity.handle.fileno(), parent.capacity.handle.fileno())
                self.assertEqual(shared.product.handle.fileno(), parent.product.handle.fileno())
                child = subprocess.run([sys.executable, "-c", script, str(self.coordination), str(self.product), inherited_lock_argument(shared)],
                                       cwd=Path(run_quality.__file__).parent, pass_fds=shared.file_descriptors(), capture_output=True, text=True, timeout=15)
                self.assertEqual(child.returncode, 0, child.stderr)
            self.assertTrue(lock_status(parent.product.path)[0])
            self.assertTrue(lock_status(parent.capacity.path)[0])
            self.assertFalse(lock_status(run_lock_path(self.coordination, "source-quality"))[0])
        self.assertEqual(self.snapshot(), self.before)

    def test_run_all_only_chains_quality_when_explicit(self):
        for enabled in (False, True):
            with self.subTest(with_quality=enabled):
                args = run_all.parse_args(["--resume", "source"] + (["--with-quality"] if enabled else []))
                with patch.object(run_all, "phase_one_completed", return_value=True), \
                     patch.object(run_all, "_chain_quality", return_value=0) as chain:
                    self.assertEqual(run_all._run_steps(args, "source", self.runs / "source", None, "{}"), 0)
                self.assertEqual(chain.call_count, int(enabled))
        self.assertEqual(self.snapshot(), self.before)

    def test_chain_reuses_same_run_and_rejects_foreign_source(self):
        commands = []
        def child(command, fds, env):
            commands.append(command)
            with adopt_execution_locks(self.coordination, "source-quality", command[-1], 1) as adopted:
                self.assertTrue(lock_status(adopted.run.path)[0])
            return 0
        with acquire_execution_locks(self.coordination, "source", 1) as locks, patch.object(run_all, "run_child", side_effect=child):
            self.assertEqual(run_all._chain_quality("source", self.source, locks, "policy"), 0)
            path = create_run_dir(self.runs, "source-quality")
            write_state(path, {"workflow": "product_quality", "source_run_id": "source"})
            self.assertEqual(run_all._chain_quality("source", self.source, locks, "policy"), 0)
            write_state(path, {"workflow": "product_quality", "source_run_id": "other"})
            with self.assertRaises(RuntimeError):
                run_all._chain_quality("source", self.source, locks, "policy")
        self.assertIn("--source-run", commands[0])
        self.assertIn("--resume", commands[1])
        self.assertEqual(self.snapshot(), self.before)

    def test_child_failure_stops_without_advancing(self):
        path = self.create()
        args = run_quality.parse_args(["--resume", "quality"])
        before = (path / "state.json").read_bytes()
        with patch.object(run_all, "run_child", return_value=143) as child:
            self.assertEqual(run_quality.orchestrate(args), 143)
        self.assertIn("quality:prepare", child.call_args.args[0])
        self.assertEqual(child.call_args.args[2][run_all._MODEL_POLICY_SNAPSHOT_ENV], "snapshot")
        self.assertEqual((path / "state.json").read_bytes(), before)

    def test_numeric_failure_keeps_quality_phase_and_scoped_result(self):
        path = self.create()
        definitions = (
            (15, "fifteen", "development", "development", "requirement:15_development"),
            (16, "sixteen", "rule_retrospective", "rule_retrospective", "requirement:16_rule_retrospective"),
            (17, "seventeen", "requirement_commit", "requirement_commit", "requirement:17_commit"),
            (18, "eighteen", "requirement_merge", "requirement_merge", "requirement:18_merge"),
        )
        scope = {"requirement_id": "BR-002", "branch": "requirement/BR-002", "trd_path": "trd.md", "development_session_id": "session"}
        for step, name, failure, success, node in definitions:
            with self.subTest(step=step):
                state = read_state(path)
                state.update(step=step, current_step=step, current_node=node, status="running")
                write_state(path, state)
                args = SimpleNamespace(step=step, run_id="quality")
                with (
                    patch.object(run_step, f"run_step_{name}", side_effect=RuntimeError("局部失败")),
                    patch.object(run_step, f"{failure}_failure_scope", return_value=scope),
                    patch.object(run_step, f"has_{success}_success", return_value=False),
                    run_step._prepare_execution_locks(args) as locks,
                ):
                    self.assertEqual(run_step._execute(args, locks), 1)
                saved = read_state(path)
                self.assertEqual(saved["phase"], "product_quality_iteration")
                self.assertEqual(saved["current_node"], node)
                self.assertEqual(saved["status"], "failed")
                self.assertTrue((path / "steps/requirements/BR-002" / f"{step}.json").is_file())

    def test_selection_handoff_uses_only_saved_numeric_position(self):
        state = {"current_node": "quality:select_requirement", "step": None, "current_step": None}
        self.assertIsNone(run_quality._numeric_step(state))
        state.update(step=13, current_step=13)
        self.assertEqual(run_quality._numeric_step(state), 13)
        state["current_step"] = 14
        with self.assertRaises(RuntimeError):
            run_quality._numeric_step(state)

    def test_generic_failure_does_not_retry_and_invalid_message_does_not_execute(self):
        path = self.create()
        message = self.root / "message.txt"
        message.write_text("补充验证资料", encoding="utf-8")
        before = (path / "state.json").read_bytes()
        self.assertEqual(run_quality.main(["--resume", "quality", "--node", "quality:prepare", "--resume-message-file", str(message)]), 2)
        self.assertEqual((path / "state.json").read_bytes(), before)
        async def fail(path, state, **kwargs):
            raise RuntimeError("本地错误")
        self.workflow.run_node = fail
        with patch.object(run_step.time, "sleep") as sleep:
            self.assertEqual(run_quality.main(["--resume", "quality", "--node", "quality:prepare"]), 1)
        sleep.assert_not_called()
        self.assertEqual(read_state(path)["status"], "failed")

    def test_real_workflow_new_state_has_no_round_budget(self):
        from quality import workflow
        source = copy.deepcopy(self.source)
        source.update(phase="phase_1_requirement_development", step=13, current_step=13,
                      current_node="phase_1:select_requirement", active_requirement=None, requirement_cycle=None,
                      applicable_repositories=["root"], repositories=[{"name": "root", "path": str(self.product)}],
                      requirement_registry={"schema_version": 1, "requirements": [
                          {"id": "BR-001", "title": "原需求", "order": 1, "depends_on": [],
                           "status": "completed", "completion": {"step": 18}}]})
        source["workspace"]["root"] = str(self.root)
        write_state(self.runs / "source", source)
        before = self.snapshot()
        with patch.object(run_quality, "_workflow", return_value=workflow), patch.object(run_quality, "_drive", return_value=0):
            self.assertEqual(run_quality.main(["--source-run", "source", "--run-id", "quality"]), 0)
            path = self.runs / "quality"
            state = read_state(path)
            self.assertEqual(state["quality"]["baseline_requirement_ids"], ["BR-001"])
            self.assertNotIn("max_rounds", state["quality"])
        self.assertEqual(self.snapshot(), before)

    def test_real_workflow_protects_saved_success_but_cli_reports_advance_failure(self):
        from common.files import write_json
        from quality import workflow
        path = self.create()
        result_path = workflow.node_result_path(path, read_state(path))
        result_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(result_path, {"node": "quality:prepare", "round": 1, "status": "success",
                                 "data": {"registry": {}, "versions": {}}})
        before = result_path.read_bytes()
        with patch.object(run_quality, "_workflow", return_value=workflow):
            with patch.object(workflow, "_replace_state", side_effect=OSError("状态写入中断")):
                self.assertEqual(run_quality.main(["--resume", "quality", "--node", "quality:prepare"]), 1)
            self.assertEqual(result_path.read_bytes(), before)
            self.assertEqual(read_state(path)["current_node"], "quality:prepare")
            self.assertTrue(list((path / "logs").glob("quality-prepare-*-error.json")))
            self.assertEqual(run_quality.main(["--resume", "quality", "--node", "quality:prepare"]), 0)
        self.assertEqual(read_state(path)["current_node"], "quality:audit")
        self.assertEqual(result_path.read_bytes(), before)

    def test_attachment_failure_of_new_run_is_saved_without_repair(self):
        runtime = self.product / ".pcm/runtime.json"
        runtime.unlink()
        self.assertEqual(run_quality.main(["--source-run", "source", "--run-id", "quality"]), 1)
        self.assertEqual(read_state(self.runs / "quality")["status"], "failed")
        self.assertFalse(runtime.exists())
        self.assertEqual((self.runs / "source/state.json").read_bytes(), self.before[str(self.runs / "source/state.json")])

    def test_only_requested_channel_failure_retries_under_same_lock(self):
        self.create()
        calls = []
        async def attempt(path, state, **kwargs):
            calls.append(lock_status(run_lock_path(self.coordination, "quality"))[0])
            if len(calls) == 1:
                raise run_step.AgentExecutionFailure("失败", "logs/failure.json", retry_requested=True)
            return await self.complete(path, state)
        self.workflow.run_node = attempt
        with patch.object(run_step.time, "sleep") as sleep:
            self.assertEqual(run_quality.main(["--resume", "quality", "--node", "quality:prepare"]), 0)
        self.assertEqual(calls, [True, True])
        sleep.assert_called_once_with(30)
        self.workflow.record_failure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
