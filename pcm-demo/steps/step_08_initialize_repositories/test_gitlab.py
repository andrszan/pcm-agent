from __future__ import annotations

import asyncio
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import unquote

from pydantic import SecretStr

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common import gitlab
from common.error_diagnostics import exception_diagnostics
from common.state import read_state, write_state
from steps.step_08_initialize_repositories import step
from steps.step_08_initialize_repositories import test_step as step_tests
from steps.step_08_initialize_repositories.test_step import (
    command, commit_all, isolated_git_environment,
)


TEST_PARENT_PATH = "test-team/pcm-projects"


class FakeGitLab:
    """仅模拟 API 协议；本地仓库、origin 与 push 使用真实 Git。"""
    def __init__(self, parent_path=TEST_PARENT_PATH, parent_id=10):
        self.parent = {"id": parent_id, "full_path": parent_path}
        self.group = None
        self.projects = {}
        self.calls = []
        self.fail_project = None

    def request(self, method, path, data=None, *, missing_ok=False):
        path = unquote(path)
        self.calls.append((method, path, data))
        if path == "user":
            return {"id": 7, "state": "active"}
        if method == "GET" and path == f"groups/{self.parent['full_path']}":
            return self.parent.copy()
        if method == "GET" and path.startswith("groups/"):
            return copy.deepcopy(self.group)
        if method == "POST" and path == "groups":
            assert data["visibility"] == "private" and data["parent_id"] == self.parent["id"]
            self.group = {"id": 20, "full_path": f"{self.parent['full_path']}/{data['path']}",
                          "parent_id": self.parent["id"], "visibility": "private"}
            return self.group.copy()
        if method == "POST" and path == "projects":
            if data["path"] == self.fail_project:
                raise RuntimeError("模拟建仓中断")
            assert data["visibility"] == "private" and data["initialize_with_readme"] is False
            assert data["namespace_id"] == 20
            full_path = f"{self.group['full_path']}/{data['path']}"
            project = {"id": 30 + len(self.projects), "path_with_namespace": full_path,
                       "ssh_url_to_repo": f"git@gitlab.com:{full_path}.git", "visibility": "private",
                       "namespace": {"id": 20, "full_path": self.group["full_path"]},
                       "empty_repo": True, "default_branch": None}
            self.projects[project["id"]] = project
            return copy.deepcopy(project)
        if path.startswith("projects/"):
            value = path.removeprefix("projects/")
            project = next((p for p in self.projects.values() if value in {str(p["id"]), p["path_with_namespace"]}), None)
            if project is not None and method == "PUT":
                assert data == {"default_branch": "main"}
                project.update(data)
            return copy.deepcopy(project)
        raise AssertionError((method, path, data))


class GitLabTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(
            pcm_gitlab_token=SecretStr("test-token"),
            pcm_gitlab_group_url=f"https://gitlab.com/{TEST_PARENT_PATH}",
        )
        settings = patch.object(gitlab, "load_settings", return_value=self.settings)
        settings.start()
        self.addCleanup(settings.stop)

    def make_run(self, root: Path, outputs: list[str] | None = None):
        run_dir, workspace, state = step_tests.InitializeRepositoriesTests().make_run(root, outputs or [])
        names = ["root", *(outputs or [])]
        for name in names:
            repository = workspace if name == "root" else workspace / name
            (repository / "README.md").write_text("测试\n")
            commit_all(repository)
        state.update(remote_sync={"enabled": True, "project_name": "project"},
                     applicable_repositories=names,
                     repositories=step._repository_facts(workspace, names))
        write_state(run_dir, state)
        return run_dir, workspace, state

    def test_token_settings_are_secret_and_independent_of_model_configuration(self):
        from config import Settings
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None, pcm_gitlab_token="private-test-token")
        self.assertEqual(settings.pcm_gitlab_token.get_secret_value(), "private-test-token")
        self.assertIsNone(settings.llm_model)
        self.assertNotIn("private-test-token", repr(settings))
        self.assertNotIn("private-test-token", settings.model_dump_json())

    def test_preflight_needs_no_model_and_missing_token_is_blocked(self):
        with patch.object(self.settings, "pcm_gitlab_token", None):
            with self.assertRaises(gitlab.RemoteBlocked):
                gitlab.preflight()
        api = FakeGitLab()
        with patch.object(gitlab, "_Client", return_value=api):
            self.assertEqual(gitlab.preflight(), api.parent)
        self.assertEqual([call[0] for call in api.calls], ["GET", "GET"])

    def test_configured_parent_url_accepts_group_pages_and_rejects_unsafe_urls(self):
        for url in (
            "https://gitlab.com/team/nested-group",
            "https://gitlab.com/team/nested-group/",
            "https://gitlab.com/groups/team/nested-group/",
        ):
            with self.subTest(url=url):
                self.settings.pcm_gitlab_group_url = url
                self.assertEqual(gitlab.configured_parent_path(), "team/nested-group")
        for url in (
            None, "", "team/group", "http://gitlab.com/team/group",
            "https://other.invalid/team/group", "https://gitlab.com.evil.invalid/team/group",
            "https://user@gitlab.com/team/group", "https://user:password@gitlab.com/team/group",
            "https://gitlab.com:443/team/group", "https://gitlab.com/team/group?tab=projects",
            "https://gitlab.com/team/group#projects", "https://gitlab.com/", "https://gitlab.com/groups/",
            "https://gitlab.com/team/../group", "https://gitlab.com/team/./group",
            "https://gitlab.com/team//group", "https://gitlab.com/team/%2e%2e/group",
            "https://gitlab.com/team%2fgroup", "https://gitlab.com/%74eam/group",
        ):
            with self.subTest(url=url), patch.object(gitlab, "_Client") as client:
                self.settings.pcm_gitlab_group_url = url
                with self.assertRaises(RuntimeError):
                    gitlab.preflight()
                client.assert_not_called()

    def test_preflight_explicit_parent_does_not_consult_current_configuration(self):
        api = FakeGitLab("historical/team", parent_id=42)
        self.settings.pcm_gitlab_group_url = None
        with patch.object(gitlab, "_Client", return_value=api):
            self.assertEqual(gitlab.preflight("historical/team"), api.parent)
        self.assertEqual(api.calls, [("GET", "user", None), ("GET", "groups/historical/team", None)])

    def test_changed_configuration_controls_parent_id_subgroup_and_real_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root, ["frontend"])
                parent_path = "another-team/platform/products"
                self.settings.pcm_gitlab_group_url = f"https://gitlab.com/groups/{parent_path}/"
                api = FakeGitLab(parent_path, parent_id=42)
                with patch.object(gitlab, "_Client", return_value=api):
                    gitlab.prepare_repositories(run_dir, state)
                saved = read_state(run_dir)["remote_sync"]
                self.assertEqual(saved["parent_path"], parent_path)
                self.assertEqual(saved["parent_group"], {"id": 42, "full_path": parent_path})
                self.assertEqual(saved["subgroup"]["full_path"], f"{parent_path}/project")
                self.assertIn(("POST", "groups", {
                    "name": "project", "path": "project", "parent_id": 42, "visibility": "private",
                }), api.calls)
                for name in ("root", "frontend"):
                    project = "project" if name == "root" else "project-frontend"
                    expected = f"git@gitlab.com:{parent_path}/project/{project}.git"
                    self.assertEqual(saved["repositories"][name]["url"], expected)
                    local = workspace if name == "root" else workspace / name
                    self.assertEqual(command("remote", "get-url", "origin", cwd=local), expected)

    def test_parent_is_saved_before_api_failure_and_configuration_change_on_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root)
                api = FakeGitLab()

                def fail_api(*args, **kwargs):
                    saved = read_state(run_dir)["remote_sync"]
                    self.assertEqual(saved["parent_path"], TEST_PARENT_PATH)
                    self.assertNotIn("parent_group", saved)
                    raise RuntimeError("模拟首次 API 中断")

                with patch.object(gitlab, "_Client", return_value=api), patch.object(api, "request", side_effect=fail_api):
                    with self.assertRaisesRegex(RuntimeError, "首次 API 中断"):
                        gitlab.prepare_repositories(run_dir, state)
                self.settings.pcm_gitlab_group_url = "https://gitlab.com/new-team/new-parent"
                with patch.object(gitlab, "_Client", return_value=api):
                    gitlab.prepare_repositories(run_dir, read_state(run_dir))
                self.assertEqual(read_state(run_dir)["remote_sync"]["parent_path"], TEST_PARENT_PATH)
                self.assertEqual(command("remote", "get-url", "origin", cwd=workspace),
                                 f"git@gitlab.com:{TEST_PARENT_PATH}/project/project.git")

    def test_legacy_registered_parent_is_preserved_after_configuration_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root)
                api = FakeGitLab()
                with patch.object(gitlab, "_Client", return_value=api):
                    gitlab.prepare_repositories(run_dir, state)
                    del state["remote_sync"]["parent_path"]
                    write_state(run_dir, state)
                    self.settings.pcm_gitlab_group_url = "https://gitlab.com/new-team/new-parent"
                    api.calls.clear()
                    recovered = read_state(run_dir)
                    gitlab.prepare_repositories(run_dir, recovered)
                    gitlab.finalize_repositories(recovered, verified_versions={
                        "root": command("rev-parse", "HEAD", cwd=workspace),
                    })
                saved = read_state(run_dir)["remote_sync"]
                self.assertEqual(saved["parent_group"], api.parent)
                self.assertEqual(gitlab.remote_parent_path({"remote_sync": saved}), TEST_PARENT_PATH)
                self.assertFalse(any(method == "POST" for method, _, _ in api.calls))
                self.assertEqual(command("remote", "get-url", "origin", cwd=workspace),
                                 f"git@gitlab.com:{TEST_PARENT_PATH}/project/project.git")

    def test_invalid_or_conflicting_saved_parent_never_falls_back_to_configuration(self):
        cases = (
            {"parent_path": None}, {"parent_path": ""}, {"parent_path": "../team"},
            {"parent_path": "https://gitlab.com/team/group"}, {"parent_path": "team%2fgroup"},
            {"parent_group": None}, {"parent_group": {}},
            {"parent_group": {"id": 10, "full_path": "../team"}},
            {"parent_path": TEST_PARENT_PATH, "parent_group": {"id": 10, "full_path": "other/team"}},
            {"parent_path": TEST_PARENT_PATH, "parent_group": None},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, _, state = self.make_run(root)
                for fields in cases:
                    with self.subTest(fields=fields), patch.object(gitlab, "_Client") as client:
                        invalid = copy.deepcopy(state)
                        invalid["remote_sync"].update(fields)
                        with self.assertRaises(RuntimeError):
                            gitlab.remote_parent_path(invalid)
                        with self.assertRaises(RuntimeError):
                            gitlab.prepare_repositories(run_dir, invalid)
                        client.assert_not_called()

    def test_api_timeout_auth_classification_and_exact_secret_redaction(self):
        token = "test-secret-unique"
        cases = [
            (HTTPError("https://gitlab.com", 403, token, {}, io.BytesIO(token.encode())), gitlab.RemoteBlocked),
            (HTTPError("https://gitlab.com", 500, token, {}, io.BytesIO(token.encode())), RuntimeError),
            (URLError(token), RuntimeError),
        ]
        for failure, kind in cases:
            with self.subTest(kind=kind, failure=type(failure).__name__), patch.object(
                gitlab, "load_settings", return_value=SimpleNamespace(pcm_gitlab_token=SecretStr(token)),
            ):
                client = gitlab._Client()
                with patch.object(client.opener, "open", side_effect=failure) as opened:
                    with self.assertRaises(kind) as caught:
                        client.request("GET", "user")
                self.assertNotIn(token, json.dumps(exception_diagnostics(caught.exception)))
                self.assertIsNone(caught.exception.__context__)
                self.assertEqual(opened.call_args.kwargs["timeout"], gitlab.API_TIMEOUT)
                self.assertEqual(opened.call_args.args[0].get_header("Private-token"), token)
                self.assertNotIn(token, opened.call_args.args[0].full_url)
        handler = gitlab._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "https://other.invalid"))

    def test_empty_project_accepts_preconfigured_default_branch(self):
        for default_branch in (None, "main", "master"):
            with self.subTest(default_branch=default_branch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with isolated_git_environment(root):
                    run_dir, workspace, state = self.make_run(root)
                    api = FakeGitLab()
                    original_request = api.request

                    def request(method, path, data=None, **kwargs):
                        value = original_request(method, path, data, **kwargs)
                        if method == "POST" and path == "projects":
                            value["default_branch"] = default_branch
                            api.projects[value["id"]]["default_branch"] = default_branch
                        return value

                    api.request = request
                    with patch.object(gitlab, "_Client", return_value=api):
                        gitlab.prepare_repositories(run_dir, state)
                    binding = read_state(run_dir)["remote_sync"]["repositories"]["root"]
                    self.assertEqual(binding["project_id"], 30)
                    self.assertEqual(command("remote", "get-url", "origin", cwd=workspace), binding["url"])

    def test_new_project_requires_explicit_empty_repository(self):
        for empty_repo in (False, None):
            with self.subTest(empty_repo=empty_repo), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with isolated_git_environment(root):
                    run_dir, workspace, state = self.make_run(root)
                    api = FakeGitLab()
                    original_request = api.request

                    def request(method, path, data=None, **kwargs):
                        value = original_request(method, path, data, **kwargs)
                        if method == "POST" and path == "projects":
                            value["empty_repo"] = empty_repo
                        return value

                    api.request = request
                    with patch.object(gitlab, "_Client", return_value=api), self.assertRaisesRegex(RuntimeError, "不是空仓库"):
                        gitlab.prepare_repositories(run_dir, state)
                    self.assertEqual(command("remote", cwd=workspace), "")
                    self.assertNotIn("root", read_state(run_dir)["remote_sync"]["repositories"])

    def test_create_only_applicable_private_projects_and_resume_without_post(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root, ["frontend"])
                api = FakeGitLab()
                with patch.object(gitlab, "_Client", return_value=api), patch.dict(os.environ, {"PCM_GITLAB_TOKEN": "never-in-child"}):
                    with patch.object(gitlab.subprocess, "run", wraps=subprocess.run) as commands:
                        gitlab.prepare_repositories(run_dir, state)
                    for call in commands.call_args_list:
                        self.assertNotIn("PCM_GITLAB_TOKEN", call.kwargs["env"])
                    first_posts = sum(method == "POST" for method, _, _ in api.calls)
                    gitlab.prepare_repositories(run_dir, read_state(run_dir))
                self.assertEqual(first_posts, 3)
                self.assertEqual(sum(method == "POST" for method, _, _ in api.calls), first_posts)
                saved = read_state(run_dir)["remote_sync"]
                self.assertEqual(set(saved["repositories"]), {"root", "frontend"})
                for name, record in saved["repositories"].items():
                    self.assertEqual(command("remote", "get-url", "origin", cwd=workspace if name == "root" else workspace / name), record["url"])

    def test_partial_creation_is_persisted_and_resume_only_creates_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root, ["backend"])
                api = FakeGitLab()
                api.fail_project = "project-backend"
                with patch.object(gitlab, "_Client", return_value=api):
                    with self.assertRaisesRegex(RuntimeError, "建仓中断"):
                        gitlab.prepare_repositories(run_dir, state)
                    partial = read_state(run_dir)
                    self.assertEqual(set(partial["remote_sync"]["repositories"]), {"root"})
                    api.fail_project = None
                    gitlab.prepare_repositories(run_dir, partial)
                self.assertEqual(len(api.projects), 2)
                self.assertEqual(sum(method == "POST" and path == "groups" for method, path, _ in api.calls), 1)

    def test_unknown_origin_and_same_name_objects_are_not_adopted(self):
        for conflict in ("origin", "same-origin", "subgroup", "project"):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with isolated_git_environment(root):
                    run_dir, workspace, state = self.make_run(root)
                    api = FakeGitLab()
                    if conflict in {"origin", "same-origin"}:
                        url = "git@example.invalid:unknown.git" if conflict == "origin" else f"git@gitlab.com:{TEST_PARENT_PATH}/project/project.git"
                        command("remote", "add", "origin", url, cwd=workspace)
                    else:
                        with patch.object(gitlab, "_Client", return_value=api):
                            gitlab.prepare_repositories(run_dir, state)
                        command("remote", "remove", "origin", cwd=workspace)
                        if conflict == "subgroup":
                            state["remote_sync"] = {"enabled": True, "project_name": "project"}
                        else:
                            state["remote_sync"]["repositories"] = {}
                    api.calls.clear()
                    with patch.object(gitlab, "_Client", return_value=api):
                        with self.assertRaisesRegex(RuntimeError, "未知 origin|归属未确认"):
                            gitlab.prepare_repositories(run_dir, state)
                    self.assertFalse(any(method == "POST" for method, _, _ in api.calls))
                    if conflict in {"origin", "same-origin"}:
                        self.assertEqual(api.calls, [])

    def test_changed_origin_and_remote_metadata_fail_without_writes(self):
        for conflict in ("origin", "pushurl", "visibility", "namespace", "subgroup-parent"):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with isolated_git_environment(root):
                    run_dir, workspace, state = self.make_run(root)
                    api = FakeGitLab()
                    with patch.object(gitlab, "_Client", return_value=api):
                        gitlab.prepare_repositories(run_dir, state)
                        if conflict == "origin":
                            command("remote", "set-url", "origin", "git@example.invalid:wrong.git", cwd=workspace)
                        elif conflict == "pushurl":
                            command("config", "remote.origin.pushurl", "git@example.invalid:wrong.git", cwd=workspace)
                        elif conflict == "visibility":
                            api.projects[30]["visibility"] = "public"
                        elif conflict == "namespace":
                            api.projects[30]["namespace"]["id"] = 99
                        else:
                            api.group["parent_id"] = 99
                        api.calls.clear()
                        with self.assertRaises(RuntimeError):
                            gitlab.prepare_repositories(run_dir, state)
                    self.assertFalse(any(method != "GET" for method, _, _ in api.calls))

    def test_unrecorded_creation_response_loss_refuses_repeated_post(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, _, state = self.make_run(root)
                api = FakeGitLab()
                request = api.request
                def lose_response(method, path, *args, **kwargs):
                    value = request(method, path, *args, **kwargs)
                    if method == "POST" and path == "groups":
                        raise RuntimeError("模拟响应丢失")
                    return value
                with patch.object(gitlab, "_Client", return_value=api), patch.object(api, "request", side_effect=lose_response):
                    with self.assertRaisesRegex(RuntimeError, "响应丢失"):
                        gitlab.prepare_repositories(run_dir, state)
                with patch.object(gitlab, "_Client", return_value=api):
                    with self.assertRaisesRegex(RuntimeError, "归属未确认"):
                        gitlab.prepare_repositories(run_dir, read_state(run_dir))
                self.assertEqual(sum(method == "POST" for method, _, _ in api.calls), 1)

    def test_new_contract_rejects_clean_unborn_repository_before_api(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = step_tests.InitializeRepositoriesTests().make_run(Path(directory), [])
            state["remote_sync"] = {"enabled": True, "project_name": "project"}
            with patch.object(gitlab, "_Client") as api, patch.object(step, "run_agent_decision_loop") as agent:
                with self.assertRaises(RuntimeError):
                    asyncio.run(step.run(run_dir, state))
            api.assert_not_called()
            agent.assert_not_called()
            self.assertEqual(read_state(run_dir)["status"], "failed")

    def test_origin_binding_interruption_reuses_registered_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root)
                api = FakeGitLab()
                real_git = gitlab._git
                def fail_binding(path, *args, **kwargs):
                    if args[:3] == ("remote", "add", "origin"):
                        raise RuntimeError("模拟 origin 绑定中断")
                    return real_git(path, *args, **kwargs)
                with patch.object(gitlab, "_Client", return_value=api):
                    with patch.object(gitlab, "_git", side_effect=fail_binding):
                        with self.assertRaisesRegex(RuntimeError, "绑定中断"):
                            gitlab.prepare_repositories(run_dir, state)
                    partial = read_state(run_dir)
                    self.assertEqual(partial["remote_sync"]["repositories"]["root"]["project_id"], 30)
                    self.assertEqual(command("remote", cwd=workspace), "")
                    api.calls.clear()
                    gitlab.prepare_repositories(run_dir, partial)
                    self.assertFalse(any(method == "POST" for method, _, _ in api.calls))
                    self.assertEqual(command("remote", cwd=workspace), "origin")

    def test_invalid_contract_cannot_fall_back_to_legacy(self):
        for remote in (None, {}, {"enabled": False}, {"enabled": 1, "project_name": "project"},
                       {"enabled": True, "project_name": "../project"},
                       {"enabled": True, "project_name": "project", "repositories": {"root": {"project_id": 2}}}):
            with self.subTest(remote=remote), tempfile.TemporaryDirectory() as directory:
                run_dir, _, state = self.make_run(Path(directory))
                state["remote_sync"] = remote
                with patch.object(gitlab, "_Client") as api:
                    with self.assertRaises(RuntimeError):
                        gitlab.prepare_repositories(run_dir, state)
                api.assert_not_called()

    def test_finalize_changes_only_registered_private_project_and_sets_upstream_without_push(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root)
                api = FakeGitLab()
                with patch.object(gitlab, "_Client", return_value=api):
                    gitlab.prepare_repositories(run_dir, state)
                    api.calls.clear()
                    with patch.object(gitlab.subprocess, "run", wraps=subprocess.run) as commands:
                        gitlab.finalize_repositories(state, verified_versions={"root": command("rev-parse", "HEAD", cwd=workspace)})
                    self.assertTrue(any(method == "PUT" for method, _, _ in api.calls))
                    self.assertFalse(any("push" in call.args[0] for call in commands.call_args_list))
                    self.assertEqual(command("config", "branch.main.remote", cwd=workspace), "origin")
                    self.assertEqual(command("config", "branch.main.merge", cwd=workspace), "refs/heads/main")
                    api.calls.clear()
                    gitlab.finalize_repositories(state, verified_versions={"root": command("rev-parse", "HEAD", cwd=workspace)})
                    self.assertFalse(any(method == "PUT" for method, _, _ in api.calls))
                    api.projects[30]["visibility"] = "public"
                    api.projects[30]["default_branch"] = "other"
                    api.calls.clear()
                    with self.assertRaises(RuntimeError):
                        gitlab.finalize_repositories(state, verified_versions={"root": command("rev-parse", "HEAD", cwd=workspace)})
                    self.assertFalse(any(method == "PUT" for method, _, _ in api.calls))

    def test_real_bare_push_partial_resume_and_result_state_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with isolated_git_environment(root):
                run_dir, workspace, state = self.make_run(root, ["frontend", "backend"])
                bare_root = root / "bare"
                bare_root.mkdir()
                for name in ("project", "project-frontend", "project-backend"):
                    command("init", "--bare", str(bare_root / f"{name}.git"), cwd=root)
                # 将固定 SSH 传输定向到本次临时 bare；没有访问 GitLab 或外部 SSH。
                bin_dir = root / "bin"
                bin_dir.mkdir()
                ssh = bin_dir / "ssh"
                ssh.write_text(
                    f"#!{sys.executable}\nimport os, shlex, sys\nfrom pathlib import Path\n"
                    "if '-G' in sys.argv: sys.exit(0)\n"
                    "args = shlex.split(sys.argv[-1])\n"
                    f"target = Path({str(bare_root)!r}) / Path(args[1]).name\n"
                    "os.execvp(args[0], [args[0], str(target)])\n"
                )
                ssh.chmod(0o755)
                hook = bare_root / "project-backend.git/hooks/pre-receive"
                hook.write_text("#!/bin/sh\nexit 1\n")
                hook.chmod(0o755)
                api = FakeGitLab()
                api.fail_project = "project-backend"
                request = api.request
                def require_saved_completion(method, path, *args, **kwargs):
                    persisted = read_state(run_dir)["initialize_repositories"]["local_completion_versions"]
                    self.assertEqual(set(persisted), {"root", "frontend", "backend"})
                    return request(method, path, *args, **kwargs)
                api.request = require_saved_completion
                with patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"}), patch.object(gitlab, "_Client", return_value=api):
                    with self.assertRaisesRegex(RuntimeError, "建仓中断"):
                        asyncio.run(step.run(run_dir, state))
                    local_complete = read_state(run_dir)
                    targets = local_complete["initialize_repositories"]["local_completion_versions"]
                    self.assertEqual(targets, {
                        name: command("rev-parse", "HEAD", cwd=workspace if name == "root" else workspace / name)
                        for name in ("root", "frontend", "backend")
                    })
                    self.assertFalse((run_dir / "steps/08-push.json").exists())
                    (workspace / "README.md").write_text("建仓失败后的新变更\n")
                    for committed in (False, True):
                        if committed:
                            commit_all(workspace, "test: 首次提交完成后的漂移")
                        with self.subTest(committed=committed), patch.object(
                            step, "run_agent_decision_loop",
                        ) as agent, patch.object(gitlab, "_Client") as unexpected_api:
                            with self.assertRaisesRegex(RuntimeError, "未提交|漂移"):
                                asyncio.run(step.run(run_dir, read_state(run_dir)))
                        agent.assert_not_called()
                        unexpected_api.assert_not_called()
                        self.assertEqual(read_state(run_dir)["initialize_repositories"]["local_completion_versions"], targets)
                    # 仅复原本测试创建的仓库，继续验证原目标的正常恢复。
                    command("reset", "--hard", targets["root"], cwd=workspace)
                    api.fail_project = None
                    with self.assertRaises(RuntimeError):
                        asyncio.run(step.run(run_dir, read_state(run_dir)))
                    partial = json.loads((run_dir / "steps/08-push.json").read_text())
                    self.assertEqual([row["name"] for row in partial["repositories"]], ["frontend", "backend", "root"])
                    self.assertEqual(partial["repositories"][0]["status"], "pushed")
                    self.assertEqual(partial["repositories"][2]["status"], "pending")
                    self.assertNotEqual(subprocess.run(
                        ["git", "--git-dir", str(bare_root / "project.git"), "rev-parse", "--verify", "refs/heads/main"],
                        capture_output=True,
                    ).returncode, 0)
                    hook.unlink()
                    original_write = step.write_state
                    def interrupt_final(target, value):
                        if value.get("current_node") == step.NEXT_NODE:
                            raise OSError("模拟 result 已写、state 未写")
                        original_write(target, value)
                    with patch.object(step, "write_state", side_effect=interrupt_final):
                        with self.assertRaisesRegex(OSError, "state 未写"):
                            asyncio.run(step.run(run_dir, read_state(run_dir)))
                    interrupted = read_state(run_dir)
                    self.assertEqual(json.loads((run_dir / "steps/08.json").read_text())["status"], "success")
                    self.assertEqual(interrupted["current_node"], step.CURRENT_NODE)
                    # 远程已接收 main，但客户端未能保留 tracking ref 的恢复现场。
                    for name in ("root", "frontend", "backend"):
                        local = workspace if name == "root" else workspace / name
                        command("update-ref", "-d", "refs/remotes/origin/main", cwd=local)
                        self.assertNotEqual(subprocess.run(
                            ["git", "rev-parse", "--verify", "refs/remotes/origin/main"],
                            cwd=local, capture_output=True,
                        ).returncode, 0)
                    saved = asyncio.run(step.run(run_dir, interrupted))
                    self.assertEqual(saved["status"], "success")
                    self.assertEqual(saved["outputs"], [])
                    receipt = json.loads((run_dir / "steps/08-push.json").read_text())
                    self.assertTrue(all(row["status"] == "unchanged" for row in receipt["repositories"]))
                    for name in ("root", "frontend", "backend"):
                        local = workspace if name == "root" else workspace / name
                        bare_name = "project" if name == "root" else f"project-{name}"
                        remote_sha = command("--git-dir", str(bare_root / f"{bare_name}.git"), "rev-parse", "main", cwd=root)
                        self.assertEqual(remote_sha, command("rev-parse", "HEAD", cwd=local))
                        self.assertEqual(command("rev-parse", "--abbrev-ref", "main@{upstream}", cwd=local), "origin/main")
                        self.assertEqual(command("rev-parse", "main@{upstream}", cwd=local), remote_sha)
                    self.assertEqual(sum(method == "POST" for method, _, _ in api.calls), 5)
                    self.assertEqual(sum(method == "POST" and path == "groups" for method, path, _ in api.calls), 1)
                    self.assertEqual({row["name"]: row["target_sha"] for row in receipt["repositories"]}, targets)

    def test_step_clean_and_saved_success_paths_both_require_remote_setup(self):
        for position in (8, 9):
            with self.subTest(position=position), tempfile.TemporaryDirectory() as directory:
                run_dir, _, state = self.make_run(Path(directory))
                state.update(step=position, current_step=position, current_node=step.CURRENT_NODE if position == 8 else step.NEXT_NODE)
                with patch.object(step, "prepare_repositories", side_effect=gitlab.RemoteBlocked("缺少授权")):
                    with self.assertRaises(step.InitializeRepositoriesBlocked):
                        asyncio.run(step.run(run_dir, state))
                self.assertEqual(read_state(run_dir)["current_node"], step.CURRENT_NODE)
                self.assertEqual(json.loads((run_dir / "steps/08.json").read_text())["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
