from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import BaseModel, SecretStr

DEMO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DEMO_ROOT))

from common.error_diagnostics import write_diagnostic
from common.files import resolve_workspace_output, write_json
from common.openai_responses import ResponsesAccessError, ResponsesFailure, parse_response
from config import (
    CAPABILITY_REPOSITORY_ROOT,
    LLMConfig,
    load_agent_workspace_env_file,
    load_template_repository,
    load_workspace_root,
)
from steps.step_01_create_workspace.project_identity import SYSTEM_PROMPT, validate_identity
from steps.step_01_create_workspace.workspace import (
    copy_initial_resources,
    initial_resources_are_ignored,
    initialize_root_repository,
    inspect_clone,
    inspect_repository,
    inspect_root_repository,
    parse_default_branch,
    prepare_staging,
    reject_nested_workspace,
    validate_initial_resources,
    verify_clone,
    verify_prepared,
    verify_workspace_env,
    workspace_env_is_ignored,
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

    def test_agent_workspace_env_file_environment_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file_source = root / "from-file.env"
            file_source.write_bytes(b"FILE=value\n")
            environment_source = root / "from-environment.env"
            environment_source.write_bytes(b"ENVIRONMENT=value\n")
            env_file = root / "settings.env"
            env_file.write_text(
                f"PCM_AGENT_WORKSPACE_ENV_FILE={file_source}\n", encoding="utf-8"
            )
            with patch.dict(
                os.environ,
                {"PCM_AGENT_WORKSPACE_ENV_FILE": str(environment_source)},
            ):
                value, source = load_agent_workspace_env_file(env_file)
            self.assertEqual(value, environment_source.resolve())
            self.assertEqual(source, "environment")
            with patch.dict(os.environ, {"PCM_AGENT_WORKSPACE_ENV_FILE": ""}):
                value, source = load_agent_workspace_env_file(env_file)
            self.assertEqual(value, file_source.resolve())
            self.assertEqual(source, "env_file")

    def test_agent_workspace_env_file_rejects_invalid_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / "settings.env"
            with patch.dict(os.environ, {"PCM_AGENT_WORKSPACE_ENV_FILE": ""}):
                with self.assertRaisesRegex(ValueError, "缺少配置"):
                    load_agent_workspace_env_file(env_file)

                env_file.write_text(
                    "PCM_AGENT_WORKSPACE_ENV_FILE=relative.env\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "绝对路径"):
                    load_agent_workspace_env_file(env_file)

                empty = root / "empty.env"
                empty.touch()
                env_file.write_text(
                    f"PCM_AGENT_WORKSPACE_ENV_FILE={empty}\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "不能为空"):
                    load_agent_workspace_env_file(env_file)

                target = root / "target.env"
                target.write_bytes(b"KEY=value\n")
                link = root / "link.env"
                link.symlink_to(target)
                env_file.write_text(
                    f"PCM_AGENT_WORKSPACE_ENV_FILE={link}\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "符号链接"):
                    load_agent_workspace_env_file(env_file)

                env_file.write_text(
                    f"PCM_AGENT_WORKSPACE_ENV_FILE={root}\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "普通文件"):
                    load_agent_workspace_env_file(env_file)

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

    def test_root_git_ignore_contract_ignores_global_excludes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True)
            global_excludes = Path(directory) / "global-excludes"
            global_excludes.write_text(".env\n", encoding="utf-8")
            global_config = Path(directory) / "global-config"
            global_config.write_text(
                f"[core]\n\texcludesFile = {global_excludes}\n", encoding="utf-8"
            )
            with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(global_config)}):
                self.assertFalse(workspace_env_is_ignored(root))
                (root / ".gitignore").write_text(".env*\n!.env.example\n", encoding="utf-8")
                self.assertTrue(workspace_env_is_ignored(root))

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

    def test_responses_parse_reports_safe_access_diagnostic(self) -> None:
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
                            "type": "permission_error",
                            "message": '{"authorization":"Bearer leak","api_key":"should-not-appear"}',
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
        self.assertEqual(
            raised.exception.diagnostic,
            {
                "kind": "http",
                "http_status": 403,
                "request_id": "body-request-id",
                "provider_code": "PERMISSION_DENIED",
                "provider_type": "permission_error",
                "provider_message": '{"authorization":"[REDACTED]","api_key":"[REDACTED]"}',
            },
        )
        self.assertIn("HTTP 403", message)
        self.assertIn("PERMISSION_DENIED", message)
        self.assertNotIn("Bearer leak", message)
        self.assertNotIn("should-not-appear", message)
        self.assertIn("[REDACTED]", message)

    def test_response_failure_logs_do_not_traverse_raw_provider_causes(self) -> None:
        import httpx
        import openai

        class InputModel(BaseModel):
            text: str

        class OutputModel(BaseModel):
            value: str

        secret = "known-llm-api-key"
        request = httpx.Request("POST", "https://example.invalid/responses")
        response = httpx.Response(500, request=request)
        cases = {
            "status": lambda: openai.APIStatusError("server error", response=response, body={}),
            "connection": lambda: openai.APIConnectionError(request=request),
            "timeout": lambda: openai.APITimeoutError(request),
            "validation": lambda: openai.APIResponseValidationError(response=response, body={}),
            "internal": lambda: RuntimeError("local parser error"),
        }

        for label, factory in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                source_error = factory()

                class Responses:
                    async def parse(self, **_kwargs: object) -> object:
                        raise source_error from RuntimeError(f"upstream echo {secret}")

                class Client:
                    responses = Responses()

                    async def close(self) -> None:
                        return None

                config = LLMConfig("https://example.invalid", SecretStr(secret), "test-model")
                with patch("common.openai_responses.AsyncOpenAI", return_value=Client()):
                    with self.assertRaises(ResponsesFailure) as raised:
                        asyncio.run(
                            parse_response(
                                config,
                                system_prompt="Extract the value.",
                                input_model=InputModel(text="input"),
                                output_model=OutputModel,
                            )
                        )
                run_dir = Path(directory) / "run"
                run_dir.mkdir()
                path = write_diagnostic(
                    run_dir,
                    f"responses-{label}.json",
                    source="test",
                    error=raised.exception,
                )
                serialized = (run_dir / path).read_text(encoding="utf-8")
                self.assertNotIn(secret, serialized)
                self.assertNotIn(f"upstream echo {secret}", serialized)

    def test_response_close_failure_is_redacted_internal_diagnostic(self) -> None:
        class InputModel(BaseModel):
            text: str

        class OutputModel(BaseModel):
            value: str

        secret = "known-llm-api-key"

        class Responses:
            async def parse(self, **_kwargs: object) -> object:
                return SimpleNamespace(status="completed", output_parsed=OutputModel(value="ok"))

        class Client:
            responses = Responses()

            async def close(self) -> None:
                try:
                    raise RuntimeError(f"close echoed {secret}")
                except RuntimeError as cause:
                    raise OSError(f"close failed {secret}") from cause

        config = LLMConfig("https://example.invalid", SecretStr(secret), "test-model")
        with patch("common.openai_responses.AsyncOpenAI", return_value=Client()):
            with self.assertRaises(ResponsesFailure) as raised:
                asyncio.run(
                    parse_response(
                        config,
                        system_prompt="Extract the value.",
                        input_model=InputModel(text="input"),
                        output_model=OutputModel,
                    )
                )
        self.assertEqual(raised.exception.diagnostic["kind"], "internal")
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            path = write_diagnostic(
                run_dir, "responses-close.json", source="test", error=raised.exception
            )
            serialized = (run_dir / path).read_text(encoding="utf-8")
        self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_request_failure_is_not_overwritten_by_close_failure(self) -> None:
        import httpx
        import openai

        class InputModel(BaseModel):
            text: str

        class OutputModel(BaseModel):
            value: str

        request = httpx.Request("POST", "https://example.invalid/responses")

        class Responses:
            async def parse(self, **_kwargs: object) -> object:
                raise openai.APIConnectionError(request=request)

        class Client:
            responses = Responses()

            async def close(self) -> None:
                raise OSError("close failed")

        config = LLMConfig("https://example.invalid", SecretStr("secret"), "test-model")
        with patch("common.openai_responses.AsyncOpenAI", return_value=Client()):
            with self.assertRaises(ResponsesFailure) as raised:
                asyncio.run(
                    parse_response(
                        config,
                        system_prompt="Extract the value.",
                        input_model=InputModel(text="input"),
                        output_model=OutputModel,
                    )
                )
        self.assertEqual(raised.exception.diagnostic["kind"], "transport")
        self.assertNotIn("close failed", str(raised.exception))

    def test_default_branch_parser(self) -> None:
        output = "ref: refs/heads/main\tHEAD\nabc\tHEAD"
        self.assertEqual(parse_default_branch(output), "main")

    def test_clone_requires_absent_and_ignored_workspace_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"
            for path in (
                staging / ".claude/skills/project-intake",
                staging / "frontend",
                staging / "backend",
            ):
                path.mkdir(parents=True, exist_ok=True)
            (staging / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
            (staging / "AGENTS.md").write_text("rules\n", encoding="utf-8")
            (staging / ".claude/skills/project-intake/SKILL.md").write_text(
                "skill\n", encoding="utf-8"
            )
            (staging / ".gitignore").write_text(
                ".env*\n!.env.example\n", encoding="utf-8"
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=staging, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "ssh://template"],
                cwd=staging,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=staging, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=PCM Test",
                    "-c",
                    "user.email=pcm@example.invalid",
                    "commit",
                    "-m",
                    "template",
                ],
                cwd=staging,
                check=True,
                capture_output=True,
            )
            template = {
                "remote_url": "ssh://template",
                "actual_branch": "main",
                "commit_sha": subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=staging,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
            }
            self.assertTrue(verify_clone(staging, template))
            (staging / ".env").write_bytes(b"KEY=value\n")
            self.assertFalse(verify_clone(staging, template))
            (staging / ".env").unlink()
            (staging / ".gitignore").write_text("", encoding="utf-8")
            self.assertFalse(verify_clone(staging, template))

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
            self.assertFalse(verify_prepared(final, "unused", b"KEY=value\n"))

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
            workspace_env = b"KEY=\x00value"
            resources = Path(directory) / "source-materials"
            (resources / "nested").mkdir(parents=True)
            (resources / "nested/sample.txt").write_text("sample", encoding="utf-8")
            prepare_staging(
                staging, draft, draft_hash, workspace_env, resources
            )
            self.assertTrue(
                verify_prepared(
                    staging,
                    draft_hash,
                    workspace_env,
                    "initial-resources/source-materials",
                )
            )
            self.assertEqual(
                (staging / "initial-resources/source-materials/nested/sample.txt").read_text(
                    encoding="utf-8"
                ),
                "sample",
            )
            self.assertTrue(verify_workspace_env(staging, workspace_env))
            self.assertEqual((staging / ".env").read_bytes(), workspace_env)
            self.assertEqual((staging / ".env").stat().st_mode & 0o777, 0o600)
            (staging / ".env").chmod(0o644)
            self.assertFalse(verify_prepared(staging, draft_hash, workspace_env))
            (staging / ".env").chmod(0o600)
            (staging / ".env").write_bytes(b"changed")
            self.assertFalse(verify_prepared(staging, draft_hash, workspace_env))
            self.assertEqual(
                [path.name for path in (staging / "docs").iterdir()], ["产品初稿.md"]
            )
            self.assertFalse((staging / ".git").exists())
    def test_initial_resources_copy_file_and_directory_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_file = root / "sample.txt"
            source_file.write_bytes(b"")
            staging_file = root / "staging-file"
            staging_file.mkdir()
            self.assertEqual(
                copy_initial_resources(staging_file, validate_initial_resources(source_file)),
                "initial-resources/sample.txt",
            )
            self.assertTrue(source_file.exists())
            self.assertEqual((staging_file / "initial-resources/sample.txt").read_bytes(), b"")

            source_dir = root / "samples"
            (source_dir / "nested").mkdir(parents=True)
            (source_dir / "nested/data.bin").write_bytes(b"data")
            staging_dir = root / "staging-dir"
            staging_dir.mkdir()
            copy_initial_resources(staging_dir, validate_initial_resources(source_dir))
            self.assertEqual(
                (staging_dir / "initial-resources/samples/nested/data.bin").read_bytes(),
                b"data",
            )
            self.assertTrue((source_dir / "nested/data.bin").exists())

    def test_initial_resources_reject_symlink_special_file_and_nested_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.txt"
            target.write_text("target", encoding="utf-8")
            link = root / "link.txt"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "符号链接"):
                validate_initial_resources(link)

            source = root / "source"
            source.mkdir()
            (source / "nested-link").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "符号链接或特殊文件"):
                validate_initial_resources(source)
            (source / "nested-link").unlink()
            fifo = source / "pipe"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "符号链接或特殊文件"):
                validate_initial_resources(source)
            fifo.unlink()
            target_workspace = source / "products/project"
            with self.assertRaisesRegex(RuntimeError, "递归包含"):
                reject_nested_workspace(source.resolve(), target_workspace)

    def test_half_copy_is_preserved_and_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "data.txt").write_text("data", encoding="utf-8")
            staging = root / "staging"
            staging.mkdir()
            with patch("shutil.copytree", side_effect=OSError("interrupted")):
                with self.assertRaisesRegex(RuntimeError, "保留半复制现场"):
                    copy_initial_resources(staging, source)
            self.assertTrue((staging / "initial-resources").is_dir())
            with self.assertRaisesRegex(RuntimeError, "拒绝覆盖"):
                copy_initial_resources(staging, source)

    def test_initial_resources_ignore_check_uses_repository_rules_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            (root / "initial-resources").mkdir()
            (root / "initial-resources/sample.txt").write_text("sample", encoding="utf-8")
            self.assertFalse(
                initial_resources_are_ignored(root)
            )
            (root / ".gitignore").write_text("initial-resources/\n", encoding="utf-8")
            self.assertTrue(
                initial_resources_are_ignored(root)
            )


if __name__ == "__main__":
    unittest.main()
