from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import AgentConfig


class AgentConfigTest(unittest.TestCase):
    def write_env(self, directory: str, content: str) -> Path:
        path = Path(directory) / ".env"
        path.write_text(content, encoding="utf-8")
        return path

    def test_loads_gateway_secret_and_model_tiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://localhost:8317/",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                        "PCM_AGENT_MODEL_LOW=low-model",
                        "PCM_AGENT_MODEL_MEDIUM=medium-model",
                        "PCM_AGENT_MODEL_HIGH=high-model",
                    ]
                ),
            )
            config = AgentConfig.load(env_file)

        self.assertEqual(config.base_url, "http://localhost:8317")
        self.assertEqual(config.auth_token.get_secret_value(), "agent-secret")
        self.assertIn("auth_token=", repr(config))
        self.assertEqual(config.resolve_model("low"), "low-model")
        self.assertEqual(config.resolve_model("medium"), "medium-model")
        self.assertEqual(config.resolve_model("high"), "high-model")
        self.assertNotIn("agent-secret", repr(config))

    def test_process_environment_overrides_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://from-file",
                        "PCM_AGENT_AUTH_TOKEN=file-secret",
                        "PCM_AGENT_MODEL_LOW=file-low",
                        "PCM_AGENT_MODEL_MEDIUM=file-medium",
                        "PCM_AGENT_MODEL_HIGH=file-high",
                    ]
                ),
            )
            with patch.dict(
                os.environ,
                {"PCM_AGENT_MODEL_MEDIUM": "environment-medium", "PCM_AGENT_AUTH_TOKEN": "environment-secret"},
                clear=False,
            ):
                config = AgentConfig.load(env_file)

        self.assertEqual(config.resolve_model("medium"), "environment-medium")
        self.assertEqual(config.auth_token.get_secret_value(), "environment-secret")

    def test_legacy_api_key_does_not_replace_required_auth_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(directory, "\n".join([
                "PCM_AGENT_BASE_URL=http://localhost:8317",
                "PCM_AGENT_API_KEY=legacy-secret",
                "PCM_AGENT_MODEL_LOW=low-model",
                "PCM_AGENT_MODEL_MEDIUM=medium-model",
                "PCM_AGENT_MODEL_HIGH=high-model",
            ]))
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "PCM_AGENT_AUTH_TOKEN"):
                    AgentConfig.load(env_file)

    def test_reports_all_missing_agent_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(directory, "UNRELATED=value\n")
            with patch.dict(
                os.environ,
                {
                    "PCM_AGENT_BASE_URL": "",
                    "PCM_AGENT_AUTH_TOKEN": "",
                    "PCM_AGENT_MODEL_LOW": "",
                    "PCM_AGENT_MODEL_MEDIUM": "",
                    "PCM_AGENT_MODEL_HIGH": "",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(ValueError, "PCM_AGENT_BASE_URL") as raised:
                    AgentConfig.load(env_file)

        self.assertIn("PCM_AGENT_AUTH_TOKEN", str(raised.exception))
        self.assertIn("PCM_AGENT_MODEL_HIGH", str(raised.exception))

    def test_rejects_base_url_with_v1_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://localhost:8317/v1",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                        "PCM_AGENT_MODEL_LOW=low-model",
                        "PCM_AGENT_MODEL_MEDIUM=medium-model",
                        "PCM_AGENT_MODEL_HIGH=high-model",
                    ]
                ),
            )
            with self.assertRaisesRegex(ValueError, "不得包含 /v1"):
                AgentConfig.load(env_file)


if __name__ == "__main__":
    unittest.main()
