from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import BaseModel, SecretStr

DEMO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DEMO_ROOT))

from common.files import resolve_workspace_output, write_json
from common.openai_responses import ResponsesAccessError, parse_response
from config import (
    CAPABILITY_REPOSITORY_ROOT,
    LLMConfig,
    load_template_repository,
    load_workspace_root,
)
from steps.step_01_create_workspace.project_identity import SYSTEM_PROMPT, validate_identity
from steps.step_01_create_workspace.workspace import (
    initialize_root_repository,
    inspect_clone,
    inspect_repository,
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

    def test_workspace_output_path_must_stay_relative_to_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            self.assertEqual(
                resolve_workspace_output(workspace, "docs/产品初稿.md"),
                workspace.resolve() / "docs/产品初稿.md",
            )
            with self.assertRaisesRegex(ValueError, "相对于产品工作区"):
                resolve_workspace_output(workspace, "/tmp/产品初稿.md")
            with self.assertRaisesRegex(ValueError, "超出产品工作区"):
                resolve_workspace_output(workspace, "../产品初稿.md")

    def test_identity_contract(self) -> None:
        identity = validate_identity(
            {
                "status": "success",
                "topic_name": "修迹维修协作系统",
                "project_directory_name": "mendmark",
                "directory_name_source": "source",
                "reason": "初稿已明确仓库名",
                "blocked_reason": None,
            }
        )
        self.assertEqual(identity["project_directory_name"], "mendmark")
        self.assertEqual(
            validate_identity(
                {
                    "status": "blocked",
                    "topic_name": None,
                    "project_directory_name": None,
                    "directory_name_source": None,
                    "reason": None,
                    "blocked_reason": "初稿没有明确产品选题",
                }
            )["blocked_reason"],
            "初稿没有明确产品选题",
        )
        self.assertIn("<task>", SYSTEM_PROMPT)
        self.assertIn("<output>", SYSTEM_PROMPT)
        self.assertIn("严格 JSON", SYSTEM_PROMPT)
        self.assertIn("代码围栏", SYSTEM_PROMPT)
        for field in (
            "status",
            "topic_name",
            "project_directory_name",
            "directory_name_source",
            "reason",
            "blocked_reason",
        ):
            self.assertIn(field, SYSTEM_PROMPT)
        self.assertIn("禁止增加其它字段", SYSTEM_PROMPT)
        with self.assertRaises(ValueError):
            validate_identity({**identity, "project_directory_name": "Mend Mark"})
        with self.assertRaises(ValueError):
            validate_identity({**identity, "status": "blocked"})
        with self.assertRaises(ValueError):
            validate_identity(
                {
                    "status": "success",
                    "topic_name": "修迹维修协作系统",
                    "project_directory_name": "mendmark",
                    "directory_name_source": "source",
                    "reason": "初稿已明确仓库名",
                    "blocked_reason": "不应同时阻塞",
                }
            )

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
            with self.assertRaisesRegex(RuntimeError, "不得暂存文件"):
                inspect_root_repository(root)
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
            self.assertEqual(
                inspect_repository(root, expected_head="present"),
                {
                    "path": str(root.resolve()),
                    "branch": "main",
                    "head": subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=root,
                        text=True,
                        capture_output=True,
                        check=True,
                    ).stdout.strip(),
                },
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

    def test_responses_parse_uses_pydantic_models(self) -> None:
        calls: list[dict[str, object]] = []

        class InputModel(BaseModel):
            text: str

        class OutputModel(BaseModel):
            value: str

        class Responses:
            async def parse(self, **kwargs: object) -> object:
                calls.append(kwargs)
                return SimpleNamespace(
                    status="completed",
                    output_parsed=OutputModel(value="ok"),
                )

        class Client:
            responses = Responses()

            async def close(self) -> None:
                return None

        config = LLMConfig("https://example.invalid", SecretStr("secret"), "test-model")
        with patch("common.openai_responses.AsyncOpenAI", return_value=Client()):
            result = asyncio.run(
                parse_response(
                    config,
                    system_prompt="Extract the value.",
                    input_model=InputModel(text="input"),
                    output_model=OutputModel,
                    max_retries=0,
                )
            )
        self.assertEqual(result, OutputModel(value="ok"))
        self.assertIs(calls[0]["text_format"], OutputModel)
        self.assertEqual(calls[0]["input"][0]["role"], "system")
        self.assertIn('"text":"input"', calls[0]["input"][1]["content"])

    def test_responses_parse_reports_access_error_details(self) -> None:
        import httpx
        import openai

        class InputModel(BaseModel):
            text: str

        class OutputModel(BaseModel):
            value: str

        class Responses:
            async def parse(self, **kwargs: object) -> object:
                response = httpx.Response(
                    403,
                    headers={"x-request-id": "header-request-id"},
                    request=httpx.Request("POST", "https://example.invalid/responses"),
                )
                raise openai.APIStatusError(
                    "Forbidden",
                    response=response,
                    body={
                        "request_id": "body-request-id",
                        "error": {
                            "code": "PERMISSION_DENIED",
                            "message": "quota exhausted; api_key=should-not-appear",
                        },
                    },
                )

        class Client:
            responses = Responses()

            async def close(self) -> None:
                return None

        config = LLMConfig("https://example.invalid", SecretStr("secret"), "test-model")
        with patch("common.openai_responses.AsyncOpenAI", return_value=Client()):
            with self.assertRaisesRegex(ResponsesAccessError, "HTTP 403") as raised:
                asyncio.run(
                    parse_response(
                        config,
                        system_prompt="Extract the value.",
                        input_model=InputModel(text="input"),
                        output_model=OutputModel,
                    )
                )
        message = str(raised.exception)
        self.assertIn("PERMISSION_DENIED", message)
        self.assertIn("body-request-id", message)
        self.assertIn("quota exhausted", message)
        self.assertIn("api_key=[REDACTED]", message)
        self.assertNotIn("should-not-appear", message)

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
