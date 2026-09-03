from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.coordination import (
    acquire_execution_locks,
    acquire_product_lock,
    adopt_execution_locks,
    claim_product,
    ensure_runtime,
    get_product,
    inherited_lock_argument,
    product_key,
    release_product,
)


class CoordinationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "coordination"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_capacity_allows_limit_and_releases_on_close(self) -> None:
        first = acquire_execution_locks(self.root, "run-a", 2)
        second = acquire_execution_locks(self.root, "run-b", 2)
        with self.assertRaisesRegex(RuntimeError, "并发执行名额已满"):
            acquire_execution_locks(self.root, "run-c", 2)
        first.close()
        replacement = acquire_execution_locks(self.root, "run-c", 2)
        replacement.close()
        second.close()

    def test_same_run_is_exclusive(self) -> None:
        first = acquire_execution_locks(self.root, "run-a", 2)
        with self.assertRaisesRegex(RuntimeError, "运行锁已被占用"):
            acquire_execution_locks(self.root, "run-a", 2)
        first.close()

    def test_inherited_locks_keep_parent_ownership(self) -> None:
        parent = acquire_execution_locks(self.root, "run-a", 2)
        adopted = adopt_execution_locks(
            self.root, "run-a", inherited_lock_argument(parent), 2
        )
        adopted.close()
        with self.assertRaisesRegex(RuntimeError, "运行锁已被占用"):
            acquire_execution_locks(self.root, "run-a", 2)
        parent.close()
        replacement = acquire_execution_locks(self.root, "run-a", 2)
        replacement.close()

    def test_lock_descriptors_are_adopted_by_child_process(self) -> None:
        parent = acquire_execution_locks(self.root, "run-a", 2)
        script = """
import sys
from pathlib import Path
from common.coordination import adopt_execution_locks
locks = adopt_execution_locks(Path(sys.argv[1]), 'run-a', sys.argv[2], 2)
print(','.join(sorted(locks.descriptors())))
locks.close()
"""
        try:
            child = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(self.root),
                    inherited_lock_argument(parent),
                ],
                cwd=Path(__file__).resolve().parent.parent,
                pass_fds=parent.file_descriptors(),
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stdout.strip(), "capacity,run")
            with self.assertRaisesRegex(RuntimeError, "运行锁已被占用"):
                acquire_execution_locks(self.root, "run-a", 2)
        finally:
            parent.close()

    def test_product_lock_is_exclusive_across_processes(self) -> None:
        product = Path(self.temporary_directory.name) / "products" / "alpha"
        script = f"""
from pathlib import Path
from common.coordination import acquire_execution_locks, acquire_product_lock, product_key
root = Path({str(self.root)!r})
product = Path({str(product)!r})
locks = acquire_execution_locks(root, 'run-a', 2)
key, canonical = product_key(product)
locks.product = locks.stack.enter_context(acquire_product_lock(root, 'run-a', key, canonical))
print('READY', flush=True)
input()
locks.close()
"""
        child = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parent.parent,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "READY")
            contender = acquire_execution_locks(self.root, "run-b", 2)
            key, canonical = product_key(product)
            with self.assertRaisesRegex(RuntimeError, "产品锁已被占用"):
                acquire_product_lock(self.root, "run-b", key, canonical)
            other_key, other_path = product_key(
                Path(self.temporary_directory.name) / "products" / "beta"
            )
            other = acquire_product_lock(
                self.root, "run-b", other_key, other_path
            )
            other.close()
            contender.close()
        finally:
            stdout, stderr = child.communicate("\n", timeout=10)
            self.assertEqual(child.returncode, 0, stdout + stderr)

    def test_product_claim_is_stable_and_exclusive(self) -> None:
        product = Path(self.temporary_directory.name) / "products" / "alpha"
        key, canonical = product_key(product)
        with acquire_product_lock(self.root, "run-a", key, canonical):
            record = claim_product(self.root, "run-a", key, canonical)
            self.assertEqual(record["ports"], {"frontend": 3100, "backend": 8100})
            self.assertEqual(claim_product(self.root, "run-a", key, canonical), record)
        with acquire_product_lock(self.root, "run-b", key, canonical):
            with self.assertRaisesRegex(RuntimeError, "其他运行认领"):
                claim_product(self.root, "run-b", key, canonical)

    def test_different_products_receive_paired_ports(self) -> None:
        records = []
        for run_id, name in (("run-a", "alpha"), ("run-b", "beta")):
            product = Path(self.temporary_directory.name) / "products" / name
            key, canonical = product_key(product)
            with acquire_product_lock(self.root, run_id, key, canonical):
                records.append(claim_product(self.root, run_id, key, canonical))
        self.assertEqual([record["port_slot"] for record in records], [100, 101])
        self.assertEqual(records[1]["ports"], {"frontend": 3101, "backend": 8101})

    def test_runtime_is_created_and_conflicts_are_rejected(self) -> None:
        product = Path(self.temporary_directory.name) / "products" / "alpha"
        product.mkdir(parents=True)
        key, canonical = product_key(product)
        with acquire_product_lock(self.root, "run-a", key, canonical):
            record = claim_product(self.root, "run-a", key, canonical)
        runtime = ensure_runtime(product, key, "run-a", record)
        self.assertTrue(runtime.is_file())
        self.assertIn("/.pcm/", (product / ".gitignore").read_text(encoding="utf-8"))
        (product / ".gitignore").write_text("", encoding="utf-8")
        ensure_runtime(product, key, "run-a", record)
        self.assertIn("/.pcm/", (product / ".gitignore").read_text(encoding="utf-8"))
        runtime.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            ensure_runtime(product, key, "run-a", record)

    def test_existing_repository_uses_local_git_exclude_for_runtime(self) -> None:
        product = Path(self.temporary_directory.name) / "products" / "alpha"
        (product / ".git/info").mkdir(parents=True)
        (product / ".gitignore").write_text(".env\n", encoding="utf-8")
        key, canonical = product_key(product)
        with acquire_product_lock(self.root, "run-a", key, canonical):
            record = claim_product(self.root, "run-a", key, canonical)
        ensure_runtime(product, key, "run-a", record)
        self.assertEqual((product / ".gitignore").read_text(encoding="utf-8"), ".env\n")
        self.assertIn(
            "/.pcm/",
            (product / ".git/info/exclude").read_text(encoding="utf-8"),
        )

    def test_release_keeps_record_and_reuses_slot(self) -> None:
        product = Path(self.temporary_directory.name) / "products" / "alpha"
        key, canonical = product_key(product)
        with acquire_product_lock(self.root, "run-a", key, canonical):
            claim_product(self.root, "run-a", key, canonical)
        released = release_product(self.root, canonical)
        self.assertEqual(released["lifecycle"], "released")
        self.assertEqual(get_product(self.root, key)["lifecycle"], "released")

        next_product = Path(self.temporary_directory.name) / "products" / "beta"
        next_key, next_path = product_key(next_product)
        with acquire_product_lock(self.root, "run-b", next_key, next_path):
            next_record = claim_product(self.root, "run-b", next_key, next_path)
        self.assertEqual(next_record["port_slot"], 100)

    def test_release_is_rejected_while_owner_run_is_active(self) -> None:
        product = Path(self.temporary_directory.name) / "products" / "alpha"
        key, canonical = product_key(product)
        locks = acquire_execution_locks(self.root, "run-a", 1)
        product_lock = acquire_product_lock(self.root, "run-a", key, canonical)
        locks.stack.enter_context(product_lock)
        claim_product(self.root, "run-a", key, canonical)
        with self.assertRaisesRegex(RuntimeError, "运行锁已被占用"):
            release_product(self.root, canonical)
        locks.close()

    def test_registry_is_valid_json_after_updates(self) -> None:
        product = Path(self.temporary_directory.name) / "products" / "alpha"
        key, canonical = product_key(product)
        with acquire_product_lock(self.root, "run-a", key, canonical):
            claim_product(self.root, "run-a", key, canonical)
        registry = json.loads((self.root / "products.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
