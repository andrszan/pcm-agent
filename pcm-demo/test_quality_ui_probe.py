from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

from common.files import write_json
from probes.probe_quality_ui import FIXTURE, digest, git, improve_fixture, prepare_fixture, probe, serve


class QualityUIProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name).resolve() / "quality-ui-test"
        self.run.mkdir()

    def make_site(self):
        root = self.run / "site"
        (root / "public").mkdir(parents=True)
        (root / "public/index.html").write_text("<h1>本地完整页面</h1>", encoding="utf-8")
        return root

    def test_fixture_is_clean_and_records_actual_audit_skill(self):
        state = prepare_fixture(self.run)
        root = Path(state["workspace"]["final_path"])
        fixture = json.loads((self.run / "fixture.json").read_text())
        self.assertEqual(git(root, "branch", "--show-current"), "main")
        self.assertEqual(git(root, "status", "--porcelain"), "")
        self.assertEqual(fixture["audit_skill_sha256"], digest(root / ".claude/skills/product-experience-audit/SKILL.md"))
        self.assertEqual((root / "public/index.html").read_bytes(), (FIXTURE / "index.html").read_bytes())
        self.assertEqual(state["source_run_id"], f"synthetic-{self.run.name}-source")
        source = self.run.parent / state["source_run_id"] / "state.json"
        self.assertEqual(json.loads(source.read_text())["workspace"]["final_path"], str(root))
        from quality.workflow import _history
        self.assertEqual(_history(self.run, state), [])
        self.assertEqual(state["current_node"], "quality:prepare")

    def test_server_uses_and_reuses_recorded_endpoint(self):
        root = self.make_site()
        with serve(root) as first:
            runtime = json.loads((root / ".pcm/runtime.json").read_text())
            self.assertEqual(runtime["endpoint"], first)
            with urlopen(first, timeout=5) as response:
                self.assertEqual(response.read(), (root / "public/index.html").read_bytes())
        with serve(root) as second:
            self.assertEqual(second, first)

    def test_busy_assigned_port_is_not_silently_changed(self):
        root = self.make_site()
        (root / ".pcm").mkdir()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            runtime = root / ".pcm/runtime.json"
            write_json(runtime, {"port": occupied.getsockname()[1], "endpoint": "unchanged"})
            before = runtime.read_bytes()
            with self.assertRaises(OSError):
                with serve(root):
                    self.fail("不应换端口启动")
            self.assertEqual(runtime.read_bytes(), before)

    def test_foreign_resume_is_rejected_before_execution(self):
        write_json(self.run / "state.json", {"workspace": {"final_path": str(self.run / "other")}})
        write_json(self.run / "fixture.json", {"kind": "other"})
        with self.assertRaisesRegex(ValueError, "只能恢复"):
            asyncio.run(probe(self.run, resume=True))
        self.assertFalse((self.run / "render-check").exists())

    def test_unrelated_source_cannot_be_repaired(self):
        with self.assertRaisesRegex(ValueError, "不匹配"):
            improve_fixture("<h1>另一个产品</h1>")


if __name__ == "__main__":
    unittest.main()
