from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import push_project
import run_all
import run_step
from common import gitlab, remote_sync
from common.coordination import acquire_product_lock, product_key
from common.files import write_json
from common.gitlab import RemoteBlocked
from common.state import read_state


TEST_PARENT_PATH = "test-team/pcm-projects"


class RemoteSyncTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(
            pcm_gitlab_token=None,
            pcm_gitlab_group_url=f"https://gitlab.com/{TEST_PARENT_PATH}",
        )
        settings = patch.object(gitlab, "load_settings", return_value=self.settings)
        settings.start()
        self.addCleanup(settings.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.product = self.root / "product"
        self.product.mkdir()
        self.run_dir = self.root / "runs" / "owner"
        (self.run_dir / "steps").mkdir(parents=True)
        self.receipt = self.run_dir / "steps" / "push.json"
        self.sha = "a" * 40
        self.state = {
            "run_id": "owner", "status": "success", "phase": "phase_1_requirement_development",
            "step": 13, "current_step": 13, "current_node": "phase_1:select_requirement",
            "active_requirement": None, "requirement_cycle": None,
            "workspace": {"root": str(self.root), "final_path": str(self.product)},
            "applicable_repositories": ["root"],
            "repositories": [{"name": "root", "path": str(self.product)}],
            "remote_sync": {"enabled": True, "parent_path": TEST_PARENT_PATH, "project_name": "product", "repositories": {
                "root": {"project_id": 1, "url": f"git@gitlab.com:{TEST_PARENT_PATH}/product/product.git"},
            }},
            "requirement_registry": {"schema_version": 1, "source": {}, "requirements": [
                {"id": "BR-001", "title": "需求", "order": 1, "depends_on": [],
                 "status": "completed", "completion": {"step": 18}},
            ]},
        }

    def _push(self, inputs, *, on_update):
        rows = [{**item, "url": item["expected_url"], "branch": "main", "remote_sha": item["target_sha"], "status": "pushed"} for item in inputs]
        on_update(rows)
        return rows

    def test_receipt_preserves_original_targets_after_failure(self):
        class PushError(RuntimeError):
            blocked = False
            def __init__(self, rows):
                super().__init__("网络中断")
                self.results = rows

        def fail(inputs, *, on_update):
            rows = [{**item, "url": item["expected_url"], "branch": "main", "remote_sha": None, "status": "failed"} for item in inputs]
            raise PushError(rows)

        module = SimpleNamespace(PushError=PushError, push_repositories=Mock(side_effect=fail))
        with patch.object(remote_sync, "push_module", return_value=module):
            with self.assertRaises(PushError):
                remote_sync.sync_repositories(self.run_dir, self.state, self.receipt, targets={"root": self.sha})
            saved = json.loads(self.receipt.read_text())
            self.assertEqual(saved["status"], "failed")
            module.push_repositories.side_effect = self._push
            with patch.object(remote_sync, "main_versions", side_effect=AssertionError("不能重选目标")):
                remote_sync.sync_repositories(self.run_dir, self.state, self.receipt)
            self.assertEqual(module.push_repositories.call_args.args[0][0]["target_sha"], self.sha)
            with self.assertRaisesRegex(RuntimeError, "原推送目标"):
                remote_sync.sync_repositories(self.run_dir, self.state, self.receipt, targets={"root": "b" * 40})
            self.assertEqual(json.loads(self.receipt.read_text())["status"], "success")

    def test_old_state_and_invalid_flags_are_distinct(self):
        self.assertFalse(remote_sync.enabled({}))
        for value in (None, {}, False, {"enabled": False}, {"enabled": 1}):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                remote_sync.enabled({"remote_sync": value})

    def test_binding_and_product_identity_must_match(self):
        self.state["remote_sync"]["repositories"]["root"]["url"] = "git@gitlab.com:other/product.git"
        with self.assertRaisesRegex(RuntimeError, "登记地址"):
            remote_sync.push_inputs(self.state)

    def test_push_inputs_keeps_bound_or_legacy_parent_when_configuration_changes(self):
        binding = self.state["remote_sync"]
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                if legacy:
                    del binding["parent_path"]
                    binding["parent_group"] = {"id": 10, "full_path": TEST_PARENT_PATH}
                for configured in ("https://gitlab.com/new-team/products", None):
                    with self.subTest(configured=configured):
                        self.settings.pcm_gitlab_group_url = configured
                        self.assertEqual(remote_sync.push_inputs(self.state), [{
                            "name": "root", "path": str(self.product),
                            "expected_url": f"git@gitlab.com:{TEST_PARENT_PATH}/product/product.git",
                        }])

    def test_push_inputs_rejects_invalid_or_conflicting_parent_binding(self):
        binding = self.state["remote_sync"]
        for value in (None, "", "../team", "other/team"):
            with self.subTest(value=value):
                binding["parent_path"] = value
                with self.assertRaises(RuntimeError):
                    remote_sync.push_inputs(self.state)
        binding["parent_path"] = TEST_PARENT_PATH
        binding["parent_group"] = {"id": 10, "full_path": "other/team"}
        with self.assertRaises(RuntimeError):
            remote_sync.push_inputs(self.state)

    def test_partial_receipt_or_symlink_cannot_be_reused(self):
        write_json(self.receipt, [])
        with self.assertRaisesRegex(RuntimeError, "记录无效"):
            remote_sync.sync_repositories(self.run_dir, self.state, self.receipt)
        self.receipt.unlink()
        self.receipt.symlink_to(self.root / "outside")
        with self.assertRaisesRegex(RuntimeError, "符号链接"):
            remote_sync.sync_repositories(self.run_dir, self.state, self.receipt)

    def test_phase_one_requires_push_and_can_resume_without_redeveloping(self):
        self.assertFalse(run_all.phase_one_completed(self.state))
        old = {key: value for key, value in self.state.items() if key != "remote_sync"}
        self.assertTrue(run_all.phase_one_completed(old))
        with patch.object(run_all, "sync_repositories", side_effect=RemoteBlocked("缺少 SSH 权限")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_all.complete_phase_one(self.run_dir, self.state), 2)
        self.assertEqual(self.state["status"], "blocked")
        self.assertEqual(self.state["current_node"], "phase_1:complete")
        self.assertEqual(self.state["requirement_registry"]["requirements"][0]["status"], "completed")
        self.assertFalse(run_all.phase_one_completed(self.state))
        with patch.object(run_all, "sync_repositories", return_value=[{"status": "unchanged"}]):
            self.assertEqual(run_all.complete_phase_one(self.run_dir, self.state), 0)
        self.assertTrue(run_all.phase_one_completed(read_state(self.run_dir)))

    def test_finalization_does_not_load_model_policy_or_run_numeric_step(self):
        write_json(self.run_dir / "state.json", self.state)
        args = run_all.parse_args(["--resume", "owner"])
        with patch.object(run_all, "RUNS_DIR", self.run_dir.parent), \
             patch.object(run_all, "COORDINATION_ROOT", self.root / "coordination"), \
             patch.object(run_all, "_attach_product_lock"), \
             patch.object(run_all, "load_settings", return_value=SimpleNamespace(pcm_max_concurrent_projects=1)), \
             patch.object(run_all, "_load_model_policy_from_file", side_effect=AssertionError("不能加载模型")), \
             patch.object(run_all, "run_child", side_effect=AssertionError("不能重跑需求")), \
             patch.object(run_all, "sync_repositories", return_value=[]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_all.orchestrate(args), 0)
            self.assertEqual(run_all.orchestrate(args), 0)

    def test_new_run_records_remote_policy_and_blocks_before_model_when_no_auth(self):
        draft = self.root / "draft.md"
        draft.write_text("产品构思")
        args = SimpleNamespace(product_draft=draft, run_id="fresh", initial_resources=None, git_user_name=None, git_user_email=None)
        with patch.object(run_step, "DEMO_ROOT", self.root):
            run_dir, state, source = run_step.load_or_create_step_one_run(args)
        expected = {"enabled": True, "parent_path": TEST_PARENT_PATH}
        self.assertEqual(state["remote_sync"], expected)
        self.assertEqual(read_state(run_dir)["remote_sync"], expected)
        self.settings.pcm_gitlab_group_url = "https://gitlab.com/new-team/new-parent"
        with patch.object(run_step, "DEMO_ROOT", self.root):
            run_dir, state, source = run_step.load_or_create_step_one_run(args)
        self.assertEqual(state["remote_sync"], expected)
        with patch.object(run_step, "remote_preflight", wraps=gitlab.preflight) as preflight, \
             patch.object(run_step, "extract_project_identity", side_effect=AssertionError("不能调用模型")):
            with self.assertRaises(run_step.WorkspaceBlocked):
                run_step.complete_step_one(args, run_dir, state, source)
        preflight.assert_called_once_with(parent_path=TEST_PARENT_PATH)

    def test_new_product_rejects_template_without_push_capability(self):
        draft = self.root / "draft.md"
        draft.write_text("产品构思")
        args = SimpleNamespace(product_draft=draft, run_id="fresh", initial_resources=None,
                               git_user_name=None, git_user_email=None, workspace_root=None)
        with patch.object(run_step, "DEMO_ROOT", self.root):
            run_dir, state, source = run_step.load_or_create_step_one_run(args)
        state["project"] = {"project_directory_name": "fresh-product", "topic_name": "产品"}
        state["coordination"] = {"product_key": "test-product"}

        def clone(path, _repository):
            path.mkdir()
            return {"commit_sha": self.sha}

        with patch.object(run_step, "remote_preflight"), \
             patch.object(run_step, "load_workspace_root", return_value=(self.root, "test")), \
             patch.object(run_step, "load_template_repository", return_value=("test-template", "test")), \
             patch.object(run_step, "load_agent_workspace_env_file", return_value=(self.root / "tools.env", "test")), \
             patch.object(run_step, "read_agent_workspace_env_file", return_value=b"TOOL=test\n"), \
             patch.object(run_step, "_ensure_product_claim", return_value=({}, None)), \
             patch.object(run_step, "clone_and_verify", side_effect=clone), \
             patch.object(run_step, "prepare_staging") as prepare:
            with self.assertRaisesRegex(RuntimeError, "模板尚未包含完整 push-changes"):
                run_step.complete_step_one(args, run_dir, state, source)
            prepare.assert_not_called()
        self.assertEqual(read_state(run_dir)["publication_phase"], "clone_verified")

    def test_manual_push_uses_product_lock_and_does_not_write_owner_state(self):
        write_json(self.run_dir / "state.json", self.state)
        before = (self.run_dir / "state.json").read_bytes()
        coordinator = self.root / "coordination"
        record = {"owner_run_id": "owner", "product_path": str(self.product)}
        module = SimpleNamespace(push_repositories=Mock(return_value=[{"status": "pushed"}]))
        with patch.object(push_project, "RUNS_DIR", self.run_dir.parent), \
             patch.object(push_project, "COORDINATION_ROOT", coordinator), \
             patch.object(push_project, "get_product", return_value=record), \
             patch.object(push_project, "push_module", return_value=module):
            key, path = product_key(self.product)
            with acquire_product_lock(coordinator, "running-dev", key, path):
                with self.assertRaises(RuntimeError):
                    push_project.push_project(self.product)
            module.push_repositories.assert_not_called()
            self.assertEqual(push_project.push_project(self.product), [{"status": "pushed"}])
        self.assertEqual((self.run_dir / "state.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
