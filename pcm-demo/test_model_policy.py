from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock, patch

import model_policy
import provider
import run_step


VALID_POLICY = """\
[profiles]
planning = { model = "planning-model", effort = "high" }
building = { model = "building-model", effort = "high" }
routine = { model = "routine-model", effort = "medium" }

[steps]
"2" = "planning"
"5" = "planning"
"6.bootstrap" = "building"
"6.theme" = "building"
"6.brand" = "building"
"7" = "planning"
"8" = "routine"
"9" = "planning"
"10" = "planning"
"11" = "planning"
"14" = "building"
"15" = "building"
"16" = "routine"
"17" = "routine"
"""


class ModelPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.policy_path = Path(self.temporary_directory.name) / "model-policy.toml"
        self.policy_path.write_text(VALID_POLICY, encoding="utf-8")
        self.path_patcher = patch.object(
            model_policy, "_MODEL_POLICY_PATH", self.policy_path
        )
        self.path_patcher.start()
        # 清空进程环境并隔离真实 .env，避免测试依赖本机提供商选择。
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()
        self.default_env_patcher = patch.object(
            provider, "DEFAULT_ENV_FILE", self.policy_path.parent / ".env"
        )
        self.default_env_patcher.start()
        model_policy._cached_policy = None

    def tearDown(self) -> None:
        model_policy._cached_policy = None
        self.default_env_patcher.stop()
        self.env_patcher.stop()
        self.path_patcher.stop()
        self.temporary_directory.cleanup()

    def test_resolves_all_stable_tasks_and_returns_frozen_profile(self) -> None:
        expected = {
            "project_intake": ("planning", "planning-model", "high"),
            "project_readiness": ("planning", "planning-model", "high"),
            "project_bootstrap": ("building", "building-model", "high"),
            "tailwind_theme": ("building", "building-model", "high"),
            "brand_assets": ("building", "building-model", "high"),
            "solution_design": ("planning", "planning-model", "high"),
            "initialize_repositories": ("routine", "routine-model", "medium"),
            "engineering_architecture": ("planning", "planning-model", "high"),
            "ui_ux_framework": ("planning", "planning-model", "high"),
            "requirement_breakdown": ("planning", "planning-model", "high"),
            "trd_design": ("building", "building-model", "high"),
            "development": ("building", "building-model", "high"),
            "rule_retrospective": ("routine", "routine-model", "medium"),
            "requirement_commit": ("routine", "routine-model", "medium"),
        }
        with patch.dict(os.environ, {"PCM_MODEL_POLICY_SNAPSHOT": ""}):
            for task, values in expected.items():
                with self.subTest(task=task):
                    profile = model_policy.get_agent_profile(task)
                    self.assertEqual(
                        (profile.profile, profile.model, profile.effort), values
                    )

        with self.assertRaises(FrozenInstanceError):
            profile.model = "changed"  # type: ignore[misc]
        with self.assertRaisesRegex(ValueError, "未知 Agent 任务"):
            model_policy.get_agent_profile("unknown")

    def test_loaded_policy_does_not_change_when_file_changes(self) -> None:
        with patch.dict(os.environ, {"PCM_MODEL_POLICY_SNAPSHOT": ""}):
            first = model_policy.get_agent_profile("project_intake")
            self.policy_path.write_text(
                VALID_POLICY.replace("planning-model", "changed-model"),
                encoding="utf-8",
            )
            second = model_policy.get_agent_profile("project_intake")

        self.assertEqual(first, second)
        self.assertEqual(second.model, "planning-model")

    def test_new_process_reads_changed_file(self) -> None:
        directory = Path(self.temporary_directory.name)
        shutil.copy(Path(model_policy.__file__), directory / "model_policy.py")
        shutil.copy(Path(provider.__file__), directory / "provider.py")
        command = [
            sys.executable,
            "-c",
            (
                "from model_policy import get_agent_profile; "
                "print(get_agent_profile('project_intake').model)"
            ),
        ]
        env = dict(os.environ)
        env.pop(model_policy._MODEL_POLICY_SNAPSHOT_ENV, None)

        first = subprocess.run(
            command,
            cwd=directory,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        self.policy_path.write_text(
            VALID_POLICY.replace("planning-model", "changed-model"),
            encoding="utf-8",
        )
        second = subprocess.run(
            command,
            cwd=directory,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(first.stdout.strip(), "planning-model")
        self.assertEqual(second.stdout.strip(), "changed-model")

    def test_internal_snapshot_takes_precedence_for_standalone_entry(self) -> None:
        policy = model_policy._read_model_policy_file()
        snapshot = model_policy._model_policy_snapshot(policy)
        self.policy_path.write_text(
            VALID_POLICY.replace("planning-model", "disk-model"), encoding="utf-8"
        )
        model_policy._cached_policy = None

        with patch.dict(
            os.environ,
            {model_policy._MODEL_POLICY_SNAPSHOT_ENV: snapshot},
            clear=False,
        ):
            profile = model_policy.get_agent_profile("project_intake")

        self.assertEqual(profile.model, "planning-model")

    def test_provider_selects_dedicated_policy_file(self) -> None:
        provider_policy_path = (
            Path(self.temporary_directory.name) / "model-policy.other.toml"
        )
        provider_policy_path.write_text(
            VALID_POLICY.replace("planning-model", "provider-model"), encoding="utf-8"
        )
        model_policy._cached_policy = None

        with patch.dict(os.environ, {"PCM_PROVIDER": "other"}):
            profile = model_policy.get_agent_profile("project_intake")

        self.assertEqual(profile.model, "provider-model")

    def test_missing_provider_policy_file_is_rejected(self) -> None:
        model_policy._cached_policy = None

        with patch.dict(os.environ, {"PCM_PROVIDER": "absent"}):
            with self.assertRaisesRegex(ValueError, "PCM_PROVIDER=absent"):
                model_policy.load_model_policy()

    def test_run_step_entry_loads_policy_once_before_execution(self) -> None:
        args = Mock()
        locks = Mock()
        with (
            patch.object(run_step, "parse_args", return_value=args),
            patch.object(run_step, "load_model_policy") as load_policy,
            patch.object(
                run_step,
                "_prepare_execution_locks",
                return_value=contextlib.nullcontext(locks),
            ),
            patch.object(run_step, "_execute", return_value=0) as execute,
        ):
            self.assertEqual(run_step.main(), 0)

        load_policy.assert_called_once_with()
        execute.assert_called_once_with(args, locks)

    def test_rejects_invalid_configuration_without_fallback(self) -> None:
        cases = {
            "unknown top-level key": "unknown = true\n" + VALID_POLICY,
            "missing task": VALID_POLICY.replace('"17" = "routine"\n', ""),
            "unknown step": VALID_POLICY + '\n"18" = "routine"\n',
            "invalid profile": VALID_POLICY.replace(
                '"14" = "building"', '"14" = "missing"'
            ),
            "invalid effort": VALID_POLICY.replace(
                'effort = "medium"', 'effort = "extreme"'
            ),
            "empty model": VALID_POLICY.replace(
                'model = "building-model"', 'model = "   "'
            ),
            "unknown profile key": VALID_POLICY.replace(
                'effort = "high" }', 'effort = "high", extra = true }', 1
            ),
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                self.policy_path.write_text(content, encoding="utf-8")
                model_policy._cached_policy = None
                with patch.dict(os.environ, {"PCM_MODEL_POLICY_SNAPSHOT": ""}):
                    with self.assertRaises(ValueError):
                        model_policy.load_model_policy()


if __name__ == "__main__":
    unittest.main()
