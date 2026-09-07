from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr

from config import AgentConfig, LLMConfig


class ConfigTest(unittest.TestCase):
    def write_env(self, directory: str, content: str) -> Path:
        path = Path(directory) / ".env"
        path.write_text(content, encoding="utf-8")
        return path

    def test_loads_agent_gateway_secret_without_model_tiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://localhost:8317/",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                        "PCM_AGENT_MODEL_LOW=ignored-low-model",
                    ]
                ),
            )
            config = AgentConfig.load(env_file)

        self.assertEqual(config.base_url, "http://localhost:8317")
        self.assertEqual(config.auth_token.get_secret_value(), "agent-secret")
        self.assertFalse(hasattr(config, "models"))
        self.assertFalse(hasattr(config, "resolve_model"))
        self.assertNotIn("agent-secret", repr(config))

    def test_process_environment_overrides_agent_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://from-file",
                        "PCM_AGENT_AUTH_TOKEN=file-secret",
                    ]
                ),
            )
            with patch.dict(
                os.environ,
                {"PCM_AGENT_AUTH_TOKEN": "environment-secret"},
                clear=False,
            ):
                config = AgentConfig.load(env_file)

        self.assertEqual(config.auth_token.get_secret_value(), "environment-secret")

    def test_legacy_api_key_does_not_replace_required_auth_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://localhost:8317",
                        "PCM_AGENT_API_KEY=legacy-secret",
                    ]
                ),
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "PCM_AGENT_AUTH_TOKEN"):
                    AgentConfig.load(env_file)

    def test_reports_all_missing_agent_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(directory, "UNRELATED=value\n")
            with patch.dict(
                os.environ,
                {"PCM_AGENT_BASE_URL": "", "PCM_AGENT_AUTH_TOKEN": ""},
                clear=False,
            ):
                with self.assertRaisesRegex(ValueError, "PCM_AGENT_BASE_URL") as raised:
                    AgentConfig.load(env_file)

        self.assertIn("PCM_AGENT_AUTH_TOKEN", str(raised.exception))

    def test_rejects_agent_base_url_with_v1_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://localhost:8317/v1",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                    ]
                ),
            )
            with self.assertRaisesRegex(ValueError, "不得包含 /v1"):
                AgentConfig.load(env_file)

    def test_llm_effort_is_optional_and_stripped_without_provider_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "LLM_BASE_URL=https://llm.example.invalid",
                        "LLM_API_KEY=llm-secret",
                        "LLM_MODEL=provider-model",
                        "LLM_MODEL_EFFORT=  provider-specific  ",
                    ]
                ),
            )
            config = LLMConfig.load(env_file)

        self.assertEqual(config.effort, "provider-specific")
        self.assertNotIn("llm-secret", repr(config))
        self.assertIn("effort='provider-specific'", repr(config))

    def test_blank_llm_effort_is_none(self) -> None:
        config = LLMConfig(
            "https://llm.example.invalid",
            SecretStr("secret"),
            "provider-model",
            "   ",
        )
        self.assertIsNone(config.effort)


if __name__ == "__main__":
    unittest.main()
