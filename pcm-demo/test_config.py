from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr

from config import AgentConfig, LLMConfig


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        # 清空进程环境，避免测试依赖本机导出或真实 .env 的提供商选择。
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()

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

    def test_loads_positive_native_auto_compact_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://localhost:8317",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                        "CLAUDE_CODE_AUTO_COMPACT_WINDOW=400001",
                    ]
                ),
            )
            config = AgentConfig.load(env_file)

        self.assertEqual(config.auto_compact_window, 400001)

    def test_rejects_non_positive_native_auto_compact_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://localhost:8317",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                        "CLAUDE_CODE_AUTO_COMPACT_WINDOW=0",
                    ]
                ),
            )
            with self.assertRaisesRegex(ValueError, "CLAUDE_CODE_AUTO_COMPACT_WINDOW"):
                AgentConfig.load(env_file)

    def test_agent_config_constructor_keeps_default_compatibility(self) -> None:
        config = AgentConfig("http://localhost:8317", SecretStr("agent-secret"))

        self.assertEqual(config.auto_compact_window, 500000)
        self.assertEqual(config.max_retries, 10)

    def test_loads_configured_native_max_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://localhost:8317",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                        "CLAUDE_CODE_MAX_RETRIES=15",
                    ]
                ),
            )
            config = AgentConfig.load(env_file)

        self.assertEqual(config.max_retries, 15)

    def test_allows_zero_native_max_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://localhost:8317",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                        "CLAUDE_CODE_MAX_RETRIES=0",
                    ]
                ),
            )
            config = AgentConfig.load(env_file)

        self.assertEqual(config.max_retries, 0)

    def test_rejects_invalid_native_max_retries(self) -> None:
        for value in ("-1", "not-an-integer"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {}, clear=True
            ):
                env_file = self.write_env(
                    directory,
                    "\n".join(
                        [
                            "PCM_AGENT_BASE_URL=http://localhost:8317",
                            "PCM_AGENT_AUTH_TOKEN=agent-secret",
                            f"CLAUDE_CODE_MAX_RETRIES={value}",
                        ]
                    ),
                )
                with self.assertRaisesRegex(ValueError, "CLAUDE_CODE_MAX_RETRIES"):
                    AgentConfig.load(env_file)

    def test_process_environment_overrides_agent_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_AGENT_BASE_URL=http://from-file",
                        "PCM_AGENT_AUTH_TOKEN=file-secret",
                        "CLAUDE_CODE_AUTO_COMPACT_WINDOW=400001",
                        "CLAUDE_CODE_MAX_RETRIES=6",
                    ]
                ),
            )
            with patch.dict(
                os.environ,
                {
                    "PCM_AGENT_AUTH_TOKEN": "environment-secret",
                    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "500001",
                    "CLAUDE_CODE_MAX_RETRIES": "12",
                },
                clear=True,
            ):
                config = AgentConfig.load(env_file)

        self.assertEqual(config.auth_token.get_secret_value(), "environment-secret")
        self.assertEqual(config.auto_compact_window, 500001)
        self.assertEqual(config.max_retries, 12)

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

    def write_provider_env(self, directory: str, name: str, content: str) -> None:
        providers = Path(directory) / ".env.d"
        providers.mkdir(exist_ok=True)
        (providers / f"{name}.env").write_text(content, encoding="utf-8")

    def test_provider_env_file_overrides_base_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_PROVIDER=other",
                        "LLM_BASE_URL=http://llm-base.example.invalid",
                        "LLM_API_KEY=llm-base-secret",
                        "LLM_MODEL=base-model",
                        "PCM_AGENT_BASE_URL=http://agent-base.example.invalid",
                        "PCM_AGENT_AUTH_TOKEN=agent-base-secret",
                        "CLAUDE_CODE_MAX_RETRIES=6",
                    ]
                ),
            )
            self.write_provider_env(
                directory,
                "other",
                "\n".join(
                    [
                        "LLM_BASE_URL=http://llm-other.example.invalid",
                        "LLM_API_KEY=llm-other-secret",
                        "LLM_MODEL=other-model",
                        "PCM_AGENT_BASE_URL=http://agent-other.example.invalid",
                        "PCM_AGENT_AUTH_TOKEN=agent-other-secret",
                    ]
                ),
            )
            agent_config = AgentConfig.load(env_file)
            llm_config = LLMConfig.load(env_file)

        self.assertEqual(agent_config.base_url, "http://agent-other.example.invalid")
        self.assertEqual(
            agent_config.auth_token.get_secret_value(), "agent-other-secret"
        )
        self.assertEqual(agent_config.max_retries, 6)
        self.assertEqual(llm_config.base_url, "http://llm-other.example.invalid")
        self.assertEqual(llm_config.model, "other-model")
        self.assertNotIn("llm-other-secret", repr(llm_config))
        self.assertNotIn("agent-other-secret", repr(agent_config))

    def test_process_environment_provider_overrides_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_PROVIDER=other",
                        "LLM_BASE_URL=http://llm-base.example.invalid",
                        "LLM_API_KEY=llm-secret",
                        "LLM_MODEL=base-model",
                        "PCM_AGENT_BASE_URL=http://agent-base.example.invalid",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                    ]
                ),
            )
            self.write_provider_env(
                directory,
                "other",
                "PCM_AGENT_BASE_URL=http://agent-other.example.invalid\n"
                "PCM_AGENT_AUTH_TOKEN=agent-other-secret\n",
            )
            self.write_provider_env(
                directory,
                "picked",
                "PCM_AGENT_BASE_URL=http://agent-picked.example.invalid\n"
                "PCM_AGENT_AUTH_TOKEN=agent-picked-secret\n",
            )
            with patch.dict(os.environ, {"PCM_PROVIDER": "picked"}):
                config = AgentConfig.load(env_file)

        self.assertEqual(config.base_url, "http://agent-picked.example.invalid")

    def test_missing_provider_env_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = self.write_env(
                directory,
                "\n".join(
                    [
                        "PCM_PROVIDER=absent",
                        "PCM_AGENT_BASE_URL=http://localhost:8317",
                        "PCM_AGENT_AUTH_TOKEN=agent-secret",
                    ]
                ),
            )
            with self.assertRaisesRegex(ValueError, "PCM_PROVIDER=absent"):
                AgentConfig.load(env_file)

    def test_rejects_invalid_provider_name(self) -> None:
        for value in ("../escape", "with/slash", ".", ".."):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                env_file = self.write_env(
                    directory,
                    "\n".join(
                        [
                            f"PCM_PROVIDER={value}",
                            "PCM_AGENT_BASE_URL=http://localhost:8317",
                            "PCM_AGENT_AUTH_TOKEN=agent-secret",
                        ]
                    ),
                )
                with self.assertRaisesRegex(ValueError, "名称无效"):
                    AgentConfig.load(env_file)


if __name__ == "__main__":
    unittest.main()
