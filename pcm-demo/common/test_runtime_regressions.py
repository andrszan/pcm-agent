from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import run_step
from common import coordination
from common.files import write_json
from steps.step_12_initialize_requirement_registry.step import CURRENT_NODE as REGISTRY_NODE


NODES = {
    5: run_step.PROJECT_READINESS_NODE,
    6: run_step.PROJECT_BOOTSTRAP_NODE,
    7: run_step.SOLUTION_DESIGN_NODE,
    8: run_step.INITIALIZE_REPOSITORIES_NODE,
    9: run_step.ENGINEERING_ARCHITECTURE_NODE,
    10: run_step.UI_UX_FRAMEWORK_NODE,
    11: run_step.REQUIREMENT_BREAKDOWN_NODE,
    12: REGISTRY_NODE,
}
RUNNERS = dict(zip(range(5, 13), (
    "run_step_five", "run_step_six", "run_step_seven", "run_step_eight",
    "run_step_nine", "run_step_ten", "run_step_eleven", "run_step_twelve",
)))


class RuntimeRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.run_dir = self.root / "runs/run"
        (self.run_dir / "steps").mkdir(parents=True)
        self.args = Namespace(step=7, run_id="run")
        for manager in (
            patch.object(run_step, "DEMO_ROOT", self.root),
            patch.object(run_step, "load_settings", return_value=Namespace(pcm_max_concurrent_projects=2)),
            patch.object(coordination, "_ports_bindable", return_value=True),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            stack.enter_context(manager)

    def state(self, step: int) -> dict:
        return {
            "run_id": "run", "step": step, "current_step": step,
            "current_node": NODES[step], "status": "running",
            "phase": "phase_1_requirement_development" if step == 12 else "project_initialization",
        }

    def test_wrong_steps_preserve_state_and_other_results(self) -> None:
        for step in NODES:
            with self.subTest(step=step):
                self.args.step = step
                current = 6 if step == 5 else 5
                write_json(self.run_dir / "state.json", self.state(current))
                write_json(self.run_dir / f"steps/{current:02d}.json", {"status": "blocked"})
                before = {path: path.read_bytes() for path in self.run_dir.rglob("*.json")}
                # 使用真实步骤入口；错误锚点必须在任何模型调用前拒绝。
                self.assertEqual(run_step._execute(self.args, None), 1)
                self.assertEqual({path: path.read_bytes() for path in self.run_dir.rglob("*.json")}, before)

    def test_current_anchor_failures_are_saved_with_legacy_phase_compatibility(self) -> None:
        for step in NODES:
            for legacy in (False, True) if step != 12 else (False,):
                with self.subTest(step=step, legacy=legacy):
                    self.args.step = step
                    state = self.state(step)
                    if legacy:
                        state.pop("phase")
                    write_json(self.run_dir / "state.json", state)
                    with patch.object(run_step, RUNNERS[step], AsyncMock(side_effect=RuntimeError("本节点失败"))):
                        self.assertEqual(run_step._execute(self.args, None), 1)
                    saved = json.loads((self.run_dir / "state.json").read_bytes())
                    self.assertEqual(saved["status"], "failed")
                    self.assertEqual(saved["current_node"], NODES[step])
                    result = json.loads((self.run_dir / f"steps/{step:02d}.json").read_bytes())
                    self.assertEqual(result["status"], "failed")
                    self.assertIn("本节点失败", result["error"]["message"])

    def test_legacy_registry_anchor_keeps_position_when_failure_is_saved(self) -> None:
        from steps.step_12_initialize_requirement_registry.step import NEXT_NODE

        self.args.step = 12
        state = self.state(12)
        state["current_node"] = NEXT_NODE
        write_json(self.run_dir / "state.json", state)
        for _ in range(2):
            self.assertEqual(run_step._execute(self.args, None), 1)
            saved = json.loads((self.run_dir / "state.json").read_bytes())
            self.assertEqual(saved["status"], "failed")
            self.assertEqual((saved["step"], saved["current_step"], saved["current_node"]), (12, 12, NEXT_NODE))

    def prepare_legacy_product(self) -> tuple[Path, str, Path]:
        product = self.root / "product"
        product.mkdir()
        state = self.state(7)
        state["workspace"] = {"final_path": str(product)}
        write_json(self.run_dir / "state.json", state)
        key, _ = coordination.product_key(product)
        return product, key, coordination.coordination_root(self.root)

    def test_legacy_run_rejects_other_owner_and_released_lease(self) -> None:
        product, key, root = self.prepare_legacy_product()
        record = coordination.claim_product(root, "other", key, product)
        legacy_state = (self.run_dir / "state.json").read_bytes()
        for owner, lifecycle in (("other", "active"), ("run", "released")):
            with self.subTest(owner=owner, lifecycle=lifecycle):
                (self.run_dir / "state.json").write_bytes(legacy_state)
                record.update(owner_run_id=owner, lifecycle=lifecycle)
                write_json(root / "products.json", {"schema_version": 1, "products": {key: record}})
                with self.assertRaises(RuntimeError):
                    with run_step._prepare_execution_locks(self.args):
                        pass
                self.assertFalse((product / ".pcm/runtime.json").exists())
                self.assertFalse(coordination.lock_status(coordination.run_lock_path(root, "run"))[0])

    def test_legacy_run_claim_creates_stable_runtime(self) -> None:
        product, key, root = self.prepare_legacy_product()
        with run_step._prepare_execution_locks(self.args) as locks:
            self.assertIsNotNone(locks.product)
        runtime = product / ".pcm/runtime.json"
        self.assertTrue(runtime.is_file())
        before = runtime.read_bytes()
        record = coordination.get_product(root, key)
        self.assertEqual(record["owner_run_id"], "run")
        with run_step._prepare_execution_locks(self.args):
            self.assertEqual(runtime.read_bytes(), before)
        self.assertEqual(coordination.get_product(root, key), record)

    def test_legacy_run_reuses_same_owner_lease(self) -> None:
        product, key, root = self.prepare_legacy_product()
        record = coordination.claim_product(root, "run", key, product)
        runtime = coordination.ensure_runtime(product, key, "run", record)
        before = runtime.read_bytes()
        with run_step._prepare_execution_locks(self.args):
            saved = json.loads((self.run_dir / "state.json").read_bytes())
            self.assertEqual(saved["coordination"]["ports"], record["ports"])
        self.assertEqual(runtime.read_bytes(), before)
        self.assertEqual(coordination.get_product(root, key), record)


if __name__ == "__main__":
    unittest.main()
