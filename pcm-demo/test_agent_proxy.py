from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr

from common.claude_agent import _anthropic_secrets, filtered_env
from config import AgentConfig


class AgentProxyTest(unittest.TestCase):
    def load(self, content: str = "", environment: dict[str, str] | None = None):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, environment or {}, clear=True
        ):
            path = Path(directory) / ".env"
            path.write_text(
                "PCM_AGENT_BASE_URL=http://localhost:8317\n"
                "PCM_AGENT_AUTH_TOKEN=test-token\n" + content,
                encoding="utf-8",
            )
            config = AgentConfig.load(path)
            return config, filtered_env(config, "test-model")

    def test_file_proxy_reaches_sdk_without_parent_proxy(self):
        _, env = self.load(
            "HTTP_PROXY=http://proxy.invalid:7890\n"
            "HTTPS_PROXY=http://proxy.invalid:7890\n"
            "NO_PROXY=localhost,127.0.0.1,::1,.internal.invalid\n"
        )
        for key in ("HTTP_PROXY", "HTTPS_PROXY"):
            self.assertEqual(env[key], "http://proxy.invalid:7890")
            self.assertEqual(env[key.lower()], env[key])
        self.assertEqual(env["NO_PROXY"], "localhost,127.0.0.1,::1,.internal.invalid")
        self.assertEqual(env["no_proxy"], env["NO_PROXY"])

    def test_lowercase_file_proxy_is_supported(self):
        _, env = self.load("https_proxy=http://lower.invalid:7890\n")
        self.assertEqual(env["HTTPS_PROXY"], "http://lower.invalid:7890")
        self.assertEqual(env["https_proxy"], env["HTTPS_PROXY"])

    def test_environment_overrides_file_across_case(self):
        for file_key, env_key in (("https_proxy", "HTTPS_PROXY"), ("HTTPS_PROXY", "https_proxy")):
            with self.subTest(file_key=file_key):
                _, env = self.load(
                    f"{file_key}=http://file.invalid:7890\n",
                    {env_key: "http://process.invalid:7890"},
                )
                self.assertEqual(env["HTTPS_PROXY"], "http://process.invalid:7890")
                self.assertEqual(env["https_proxy"], env["HTTPS_PROXY"])

    def test_lowercase_wins_conflict_in_each_source(self):
        for content in (
            "https_proxy=http://lower.invalid\nHTTPS_PROXY=http://upper.invalid\n",
            "HTTPS_PROXY=http://upper.invalid\nhttps_proxy=http://lower.invalid\n",
        ):
            _, env = self.load(content)
            self.assertEqual(env["HTTPS_PROXY"], "http://lower.invalid")
        for environment in (
            {"https_proxy": "http://lower.invalid", "HTTPS_PROXY": "http://upper.invalid"},
            {"HTTPS_PROXY": "http://upper.invalid", "https_proxy": "http://lower.invalid"},
        ):
            _, env = self.load(environment=environment)
            self.assertEqual(env["HTTPS_PROXY"], "http://lower.invalid")
            self.assertEqual(env["https_proxy"], env["HTTPS_PROXY"])

    def test_empty_environment_keeps_existing_empty_value_semantics(self):
        _, env = self.load(
            "HTTPS_PROXY=http://file.invalid\n", {"HTTPS_PROXY": "", "https_proxy": ""}
        )
        self.assertEqual(env["HTTPS_PROXY"], "http://file.invalid")
        self.assertEqual(env["https_proxy"], env["HTTPS_PROXY"])

    def test_no_proxy_config_does_not_force_local_proxy(self):
        _, env = self.load("HTTP_PROXY=\nHTTPS_PROXY=\nNO_PROXY=\n")
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
            self.assertNotIn(key, env)
            self.assertNotIn(key.lower(), env)

    def test_legacy_constructor_preserves_parent_environment(self):
        config = AgentConfig("http://localhost:8317", SecretStr("test-token"))
        with patch.dict(os.environ, {"https_proxy": "http://inherited.invalid"}, clear=True):
            env = filtered_env(config, "test-model")
        self.assertEqual(env["https_proxy"], "http://inherited.invalid")

    def test_all_proxy_is_not_converted_to_http_proxy(self):
        _, env = self.load(environment={"ALL_PROXY": "socks5://socks.invalid:1080"})
        self.assertEqual(env["ALL_PROXY"], "socks5://socks.invalid:1080")
        self.assertNotIn("HTTPS_PROXY", env)

    def test_agent_retry_environment_overrides_parent_values(self):
        _, env = self.load(
            environment={
                "CLAUDE_CODE_MAX_RETRIES": "2",
                "CLAUDE_CODE_RETRY_WATCHDOG": "1",
                "API_TIMEOUT_MS": "98765",
            }
        )
        self.assertEqual(env["CLAUDE_CODE_MAX_RETRIES"], "15")
        self.assertEqual(env["CLAUDE_CODE_RETRY_WATCHDOG"], "0")
        self.assertEqual(env["API_TIMEOUT_MS"], "98765")

    def test_proxy_credentials_are_not_in_repr_and_are_redacted(self):
        config, env = self.load("HTTPS_PROXY=http://user:proxy-secret@proxy.invalid:7890\n")
        self.assertEqual(env["HTTPS_PROXY"], "http://user:proxy-secret@proxy.invalid:7890")
        self.assertNotIn("proxy-secret", repr(config))
        from common.error_diagnostics import redact_text
        text = redact_text(env["HTTPS_PROXY"], known_secrets=_anthropic_secrets(config))
        self.assertNotIn("proxy-secret", text)

    def test_proxy_password_alone_is_redacted_in_errors_and_exceptions(self):
        from common.claude_agent import _sdk_errors
        from common.error_diagnostics import exception_diagnostics

        config, _ = self.load("HTTPS_PROXY=http://user:proxy%2Dsecret@proxy.invalid\n")
        secrets = _anthropic_secrets(config)
        for password in ("proxy%2Dsecret", "proxy-secret"):
            with self.subTest(password=password):
                message = f"proxy authentication rejected credential {password}"
                self.assertNotIn(password, str(_sdk_errors([message], secrets)))
                details = exception_diagnostics(RuntimeError(message), known_secrets=secrets)
                self.assertNotIn(password, str(details))


if __name__ == "__main__":
    unittest.main()
