from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DEMO_ROOT))

from common.files import write_json
from common.openai_responses import request_json
from config import (
    CAPABILITY_REPOSITORY_ROOT,
    load_template_repository,
    load_workspace_root,
)
from steps.step_01_create_workspace.project_identity import validate_identity
from steps.step_01_create_workspace.workspace import (
    initialize_root_repository,
    inspect_clone,
    inspect_root_repository,
    parse_default_branch,
    prepare_staging,
    verify_prepared,
)


class WorkspaceStepTests(unittest.TestCase):
    """第 1 步工作区发布测试。"""

    def test_json_write_replaces_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('{"old": true}\n', encoding="utf-8")
            write_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"new": True})
            self.assertFalse((path.parent / ".state.json.tmp").exists())

    def test_identity_contract(self) -> None:
        identity = validate_identity(
            {
                "topic_name": "修迹维修协作系统",
                "project_directory_name": "mendmark",
                "directory_name_source": "source",
                "reason": "初稿已明确仓库名",
                "blocked_reason": None,
            }
        )
        self.assertEqual(identity["project_directory_name"], "mendmark")
        with self.assertRaises(ValueError):
            validate_identity({**identity, "project_directory_name": "Mend Mark"})

    def test_workspace_root_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / ".env"
            env_file.write_text("PCM_WORKSPACE_ROOT=/from-file\n", encoding="utf-8")
            previous = os.environ.get("PCM_WORKSPACE_ROOT")
            try:
                os.environ["PCM_WORKSPACE_ROOT"] = "/from-environment"
                value, source = load_workspace_root(root / "from-cli", env_file)
                self.assertEqual(value, (root / "from-cli").resolve())
                self.assertEqual(source, "cli")
                value, source = load_workspace_root(None, env_file)
                self.assertEqual(value, Path("/from-environment"))
                self.assertEqual(source, "environment")
            finally:
                if previous is None:
                    os.environ.pop("PCM_WORKSPACE_ROOT", None)
                else:
                    os.environ["PCM_WORKSPACE_ROOT"] = previous

    def test_workspace_root_rejects_capability_repository(self) -> None:
        with self.assertRaisesRegex(ValueError, "能力仓库之外"):
            load_workspace_root(CAPABILITY_REPOSITORY_ROOT / "pcm-demo/workspace")

    def test_root_repository_is_unborn_main_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            first = initialize_root_repository(root)
            second = initialize_root_repository(root)
            self.assertEqual(first, second)
            self.assertEqual(
                first,
                {"path": str(root.resolve()), "branch": "main", "head": None},
            )
            self.assertEqual(inspect_root_repository(root), first)

    def test_root_repository_with_commit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            initialize_root_repository(root)
            import subprocess

            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=PCM Test",
                    "-c",
                    "user.email=pcm@example.invalid",
                    "commit",
                    "-m",
                    "test",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            with self.assertRaisesRegex(RuntimeError, "尚无 commit"):
                inspect_root_repository(root)

        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            previous = os.environ.pop("PCM_TEMPLATE_REPOSITORY", None)
            try:
                with self.assertRaises(ValueError):
                    load_template_repository(env_file)
            finally:
                if previous is not None:
                    os.environ["PCM_TEMPLATE_REPOSITORY"] = previous

    def test_template_repository_environment_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "PCM_TEMPLATE_REPOSITORY=ssh://from-file\n", encoding="utf-8"
            )
            previous = os.environ.get("PCM_TEMPLATE_REPOSITORY")
            try:
                os.environ["PCM_TEMPLATE_REPOSITORY"] = "ssh://from-environment"
                value, source = load_template_repository(env_file)
                self.assertEqual(value, "ssh://from-environment")
                self.assertEqual(source, "environment")
            finally:
                if previous is None:
                    os.environ.pop("PCM_TEMPLATE_REPOSITORY", None)
                else:
                    os.environ["PCM_TEMPLATE_REPOSITORY"] = previous

    def test_responses_request_uses_output_text(self) -> None:
        calls: list[dict[str, object]] = []

        class Responses:
            async def create(self, **kwargs: object) -> object:
                calls.append(kwargs)
                return type("Response", (), {"status": "completed", "output_text": "{}"})()

        class Client:
            responses = Responses()

        content = __import__("asyncio").run(
            request_json(
                Client(),
                model="test-model",
                instructions="system",
                input_text="input",
                schema_name="test_schema",
                schema={"type": "object", "additionalProperties": False},
            )
        )
        self.assertEqual(content, "{}")
        self.assertEqual(calls[0]["instructions"], "system")
        self.assertEqual(calls[0]["input"], "input")
        self.assertEqual(calls[0]["max_output_tokens"], 512)
        self.assertEqual(calls[0]["text"]["format"]["type"], "json_schema")

    def test_default_branch_parser(self) -> None:
        output = "ref: refs/heads/main\tHEAD\nabc\tHEAD"
        self.assertEqual(parse_default_branch(output), "main")

    def test_incomplete_staging_fails_and_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"
            staging.mkdir()
            marker = staging / "partial"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                inspect_clone(staging, "ssh://template")
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_symlink_staging_fails_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            marker = target / "keep"
            marker.write_text("keep", encoding="utf-8")
            staging = root / "staging"
            staging.symlink_to(target, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                inspect_clone(staging, "ssh://template")
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_symlink_final_is_not_accepted_as_prepared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            final = root / "final"
            final.symlink_to(target, target_is_directory=True)
            self.assertFalse(verify_prepared(final, "unused"))

    def test_prepare_staging_resets_docs_and_preserves_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"
            for path in (
                staging / ".git",
                staging / ".claude/skills/project-intake",
                staging / "frontend",
                staging / "backend",
                staging / "docs",
            ):
                path.mkdir(parents=True, exist_ok=True)
            (staging / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
            (staging / "AGENTS.md").write_text("rules\n", encoding="utf-8")
            (staging / ".claude/skills/project-intake/SKILL.md").write_text(
                "skill\n", encoding="utf-8"
            )
            (staging / "docs/old.md").write_text("old\n", encoding="utf-8")
            draft = "初稿\n".encode()
            import hashlib

            draft_hash = hashlib.sha256(draft).hexdigest()
            prepare_staging(staging, draft, draft_hash)
            self.assertTrue(verify_prepared(staging, draft_hash))
            self.assertEqual(
                [path.name for path in (staging / "docs").iterdir()], ["产品初稿.md"]
            )
            self.assertFalse((staging / ".git").exists())


if __name__ == "__main__":
    unittest.main()
