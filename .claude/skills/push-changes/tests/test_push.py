"""真实临时 bare 仓验收；任何 Git 传输均指向本测试创建的 file remote。"""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "push.py"
spec = importlib.util.spec_from_file_location("push", SCRIPT)
push = importlib.util.module_from_spec(spec)
spec.loader.exec_module(push)


class PushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="push-changes-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        home = self.root / "home"
        home.mkdir()
        # 与用户 Git 配置、身份和凭据隔离，不接触现有 origin。
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("GIT_", "PCM_", "LLM_"))}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), GIT_CONFIG_NOSYSTEM="1")
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.counter = 0

    def git(self, path, *args, check=True):
        return subprocess.run(["git", "-C", str(path), *args], check=check,
                              capture_output=True, text=True, timeout=15)

    def repository(self, name=None, commit=True):
        self.counter += 1
        name = name or f"repo-{self.counter}"
        path = self.root / name
        bare = self.root / f"{name}.git"
        path.mkdir()
        bare.mkdir()
        self.git(path, "init", "-b", "main")
        self.git(bare, "init", "--bare", "-b", "main")
        self.git(path, "config", "user.name", "本地测试")
        self.git(path, "config", "user.email", "test@example.invalid")
        self.git(path, "config", "commit.gpgsign", "false")
        self.git(path, "remote", "add", "origin", bare.as_uri())
        if commit:
            self.commit(path)
        return dict(name=name, path=str(path)), bare

    def commit(self, path):
        self.git(path, "commit", "--allow-empty", "-m", "test")
        return self.git(path, "rev-parse", "HEAD").stdout.strip()

    def sha(self, path, ref="refs/heads/main"):
        result = self.git(path, "rev-parse", "--verify", ref, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    def failure(self, repos, message=None, **kwargs):
        with self.assertRaises(push.PushError) as context:
            push.push_repositories(repos, **kwargs)
        if message:
            self.assertIn(message, str(context.exception))
        self.assertFalse(context.exception.blocked)
        return context.exception

    def test_first_push_unchanged_fast_forward_and_target_snapshot(self):
        repo, bare = self.repository()
        snapshots = []
        result = push.push_repositories([repo], on_update=snapshots.append)[0]
        self.assertEqual(result["status"], "pushed")
        self.assertEqual(result["target_sha"], self.sha(bare))
        self.assertEqual(result["remote_sha"], self.sha(bare))
        self.assertTrue(any(row[0]["target_sha"] and row[0]["status"] == "pending" for row in snapshots))
        self.assertEqual(snapshots[0][0]["status"], "pending")
        self.assertEqual(push.push_repositories([repo])[0]["status"], "unchanged")
        sha = self.commit(repo["path"])
        repo.update(target_sha=sha, expected_url=bare.as_uri())
        self.assertEqual(push.push_repositories([repo])[0]["status"], "pushed")
        self.assertEqual(self.sha(bare), sha)

    def test_only_explicit_branch_no_tags_default_refspec_or_upstream(self):
        repo, bare = self.repository()
        path = repo["path"]
        self.git(path, "branch", "other")
        self.git(path, "tag", "-a", "v1", "-m", "test")
        self.git(path, "config", "push.followTags", "true")
        self.git(path, "config", "push.default", "matching")
        self.git(path, "config", "push.autoSetupRemote", "true")
        self.git(path, "config", "push.recurseSubmodules", "on-demand")
        self.git(path, "config", "remote.origin.push", "refs/*:refs/*")
        push.push_repositories([repo])
        refs = self.git(bare, "for-each-ref", "--format=%(refname)").stdout.splitlines()
        self.assertEqual(refs, ["refs/heads/main"])
        self.git(path, "switch", "-c", "req/example")
        self.failure([repo], "当前分支")
        push.push_repositories([repo], branch="req/example")
        self.assertEqual(self.sha(bare, "refs/heads/req/example"), self.sha(path))
        self.assertNotEqual(self.git(path, "config", "--get", "branch.req/example.remote", check=False).returncode, 0)
        self.assertNotEqual(self.git(path, "config", "--get", "branch.main.remote", check=False).returncode, 0)

    def test_all_repositories_preflight_before_any_push(self):
        first, bare = self.repository()
        second, _ = self.repository()
        Path(second["path"], "dirty.txt").write_text("not committed")
        failure = self.failure([first, second], "未提交")
        self.assertEqual([row["status"] for row in failure.results], ["pending", "failed"])
        self.assertEqual(self.sha(bare), "")

    def test_dirty_staged_and_untracked(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                repo, bare = self.repository()
                Path(repo["path"], "data").write_text("not committed")
                if staged:
                    self.git(repo["path"], "add", "data")
                self.failure([repo], "未提交")
                self.assertEqual(self.sha(bare), "")

    def test_repository_boundary_unborn_and_detached(self):
        repo, bare = self.repository()
        subdir = Path(repo["path"], "child")
        subdir.mkdir()
        self.failure([dict(repo, path=str(subdir))], "top-level")
        self.git(repo["path"], "checkout", "--detach")
        self.failure([repo], "当前分支")
        unborn, _ = self.repository(commit=False)
        self.failure([unborn], "HEAD 不存在")
        self.assertEqual(self.sha(bare), "")

    def test_in_progress_operations(self):
        repo, bare = self.repository()
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "BISECT_START"):
            with self.subTest(name=name):
                marker = Path(repo["path"], ".git", name)
                marker.write_text("test")
                self.failure([repo], "进行中")
                marker.unlink()
        self.assertEqual(self.sha(bare), "")

    def test_wrong_binding_multiple_push_urls_and_mirror(self):
        repo, bare = self.repository()
        self.failure([dict(repo, expected_url="ssh://git@example.invalid/wrong.git")], "expected_url")
        self.git(repo["path"], "config", "--add", "remote.origin.pushurl", bare.as_uri())
        self.git(repo["path"], "config", "--add", "remote.origin.pushurl", (self.root / "other.git").as_uri())
        self.failure([repo], "多目标")
        self.git(repo["path"], "config", "--unset-all", "remote.origin.pushurl")
        self.git(repo["path"], "config", "remote.origin.mirror", "true")
        self.failure([repo], "mirror")
        self.assertEqual(self.sha(bare), "")

    def test_push_url_different_from_fetch_and_rewrite(self):
        repo, bare = self.repository()
        other, other_bare = self.repository()
        self.git(repo["path"], "remote", "set-url", "origin", other_bare.as_uri())
        self.git(repo["path"], "config", "remote.origin.pushurl", "local-push:target")
        self.git(repo["path"], "config", f"url.{bare.as_uri()}.insteadOf", "local-push:target")
        result = push.push_repositories([dict(repo, expected_url=bare.as_uri())])[0]
        self.assertEqual(result["url"], bare.as_uri())
        self.assertEqual(self.sha(bare), self.sha(repo["path"]))
        self.assertEqual(self.sha(other_bare), "")
        self.assertEqual(self.git(other["path"], "status", "--porcelain").stdout, "")

    def test_push_instead_of_rewrite(self):
        repo, bare = self.repository()
        self.git(repo["path"], "remote", "set-url", "origin", "push-alias:target")
        self.git(repo["path"], "config", f"url.{bare.as_uri()}.pushInsteadOf", "push-alias:target")
        self.assertEqual(push.push_repositories([repo])[0]["url"], bare.as_uri())
        self.assertEqual(self.sha(bare), self.sha(repo["path"]))

    def test_token_url_and_rewrite_rejected_without_secrets(self):
        for url in ("https://user:do-not-print@example.invalid/repo.git",
                    "https://do-not-print@example.invalid/repo.git",
                    "https://example.invalid/repo.git?token=do-not-print",
                    "ssh://git:do-not-print@example.invalid/repo.git"):
            with self.subTest(url=url):
                repo, bare = self.repository()
                self.git(repo["path"], "config", "remote.origin.pushurl", "url-alias:target")
                self.git(repo["path"], "config", f"url.{url}.insteadOf", "url-alias:target")
                failure = self.failure([repo])
                self.assertNotIn("do-not-print", str(failure) + json.dumps(failure.results))
                self.assertEqual(self.sha(bare), "")

    def test_target_sha_mismatch_and_unknown_input(self):
        repo, bare = self.repository()
        old = self.sha(repo["path"])
        self.commit(repo["path"])
        self.failure([dict(repo, target_sha=old)], "漂移")
        self.failure([dict(repo, target_sha="HEAD")], "完整提交")
        self.failure([repo], branch="bad:branch")
        self.failure([repo], remote="--all")
        self.failure([repo, repo], "重复")
        self.failure([])
        self.assertEqual(self.sha(bare), "")

    def test_remote_ahead_and_diverged_preflight(self):
        for diverged in (False, True):
            with self.subTest(diverged=diverged):
                first, first_bare = self.repository()
                repo, bare = self.repository()
                old = self.sha(repo["path"])
                new = self.commit(repo["path"])
                self.git(bare, "fetch", repo["path"], f"{new}:refs/heads/main")
                self.git(repo["path"], "reset", "--hard", old)
                if diverged:
                    self.git(repo["path"], "commit", "--allow-empty", "-m", "diverged")
                self.failure([first, repo], "领先或分叉")
                self.assertEqual(self.sha(first_bare), "")
                self.assertEqual(self.sha(bare), new)

    def test_unknown_remote_object_no_fetch(self):
        first, first_bare = self.repository()
        repo, bare = self.repository()
        other, _ = self.repository()
        self.git(other["path"], "commit", "--allow-empty", "-m", "unique remote commit")
        remote_sha = self.sha(other["path"])
        self.git(bare, "fetch", other["path"], f"{remote_sha}:refs/heads/main")
        self.failure([first, repo], "对象不在本地")
        self.assertEqual(self.sha(first_bare), "")
        self.assertNotEqual(self.git(repo["path"], "cat-file", "-e", remote_sha, check=False).returncode, 0)

    def test_partial_success_hooks_and_resume(self):
        first, first_bare = self.repository()
        second, second_bare = self.repository()
        root, root_bare = self.repository()
        hook = second_bare / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nprintf 'private-hook-secret\\n' >&2\nexit 1\n")
        hook.chmod(0o755)
        updates = []
        failure = self.failure([first, second, root], on_update=updates.append)
        self.assertEqual([row["status"] for row in failure.results], ["pushed", "failed", "pending"])
        self.assertEqual(updates[-1], failure.results)
        self.assertEqual(self.sha(first_bare), self.sha(first["path"]))
        self.assertEqual(self.sha(root_bare), "")
        self.assertNotIn("private-hook-secret", json.dumps(failure.results) + str(failure))
        hook.unlink()
        result = push.push_repositories([first, second, root])
        self.assertEqual([row["status"] for row in result], ["unchanged", "pushed", "pushed"])

    def test_pre_push_hook_is_not_skipped(self):
        repo, bare = self.repository()
        hook = Path(repo["path"], ".git", "hooks", "pre-push")
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.failure([repo])
        self.assertEqual(self.sha(bare), "")

    def test_branch_drift_after_real_push_detected(self):
        repo, bare = self.repository()
        original = self.sha(repo["path"])
        git = push._git

        def drift(path, *args, **kwargs):
            result = git(path, *args, **kwargs)
            if "push" in args:
                self.commit(path)
            return result

        with patch.object(push, "_git", side_effect=drift):
            failure = self.failure([repo], "漂移")
        self.assertEqual(failure.results[0]["status"], "failed")
        self.assertEqual(self.sha(bare), original)
        self.assertNotEqual(self.sha(repo["path"]), original)

    def test_lost_response_resume_queries_remote_fact(self):
        repo, bare = self.repository()
        git = push._git

        def lost(path, *args, **kwargs):
            result = git(path, *args, **kwargs)
            if "push" in args:
                raise push._Failure("测试响应丢失")
            return result

        with patch.object(push, "_git", side_effect=lost):
            self.failure([repo], "响应丢失")
        self.assertEqual(self.sha(bare), self.sha(repo["path"]))
        self.assertEqual(push.push_repositories([repo])[0]["status"], "unchanged")

    def test_sanitized_environment_and_local_git_redirect_removed(self):
        repo, bare = self.repository()
        other, _ = self.repository()
        hook = Path(repo["path"], ".git", "hooks", "pre-push")
        hook.write_text("#!/bin/sh\ntest -z \"$PCM_GITLAB_TOKEN$pcm_gitlab_token$Pcm_Gitlab_Token$LLM_API_KEY\" || exit 1\n"
                        "test \"$SSH_AUTH_SOCK\" = /test/socket || exit 1\n"
                        "test \"$pcm_other\" = keep-me || exit 1\n")
        hook.chmod(0o755)
        with patch.dict(os.environ, {"PCM_GITLAB_TOKEN": "tool-secret", "LLM_API_KEY": "llm-secret",
                                     "pcm_gitlab_token": "lower-tool-secret", "Pcm_Gitlab_Token": "mixed-tool-secret",
                                     "pcm_other": "keep-me",
                                     "GIT_DIR": str(Path(other["path"], ".git")),
                                     "GIT_WORK_TREE": other["path"], "GIT_INDEX_FILE": "/bad/index",
                                     "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "remote.origin.mirror",
                                     "GIT_CONFIG_VALUE_0": "true", "SSH_AUTH_SOCK": "/test/socket"}):
            result = push.push_repositories([repo])
            env = push._environment()
            for key in ("PCM_GITLAB_TOKEN", "pcm_gitlab_token", "Pcm_Gitlab_Token"):
                self.assertNotIn(key, env)
            self.assertNotIn("GIT_DIR", env)
            self.assertNotIn("GIT_CONFIG_COUNT", env)
            self.assertIn("StrictHostKeyChecking=yes", env["GIT_SSH_COMMAND"])
            self.assertIn("BatchMode=yes", env["GIT_SSH_COMMAND"])
            self.assertNotIn("tool-secret", json.dumps(result))
        self.assertEqual(self.sha(bare), self.sha(repo["path"]))

    def test_callback_failure_stops_without_leaking(self):
        repo, bare = self.repository()

        def broken(_):
            raise RuntimeError("private persistence secret")

        failure = self.failure([repo], "保存", on_update=broken)
        self.assertNotIn("private persistence secret", str(failure))
        self.assertEqual(self.sha(bare), "")

    def test_auth_classification_is_explicit_and_host_trust_preserved(self):
        self.assertTrue(push._command_error("Permission denied (publickey).", ssh=True).blocked)
        self.assertFalse(push._command_error("Permission denied (publickey).", ssh=False).blocked)
        self.assertFalse(push._command_error("Host key verification failed.", ssh=True).blocked)
        self.assertFalse(push._command_error("repository not found", ssh=True).blocked)
        self.assertFalse(push._command_error("network is unreachable", ssh=True).blocked)

    def test_timeout_is_finite_and_hook_children_stopped(self):
        repo, bare = self.repository()
        hook = Path(repo["path"], ".git", "hooks", "pre-push")
        hook.write_text("#!/bin/sh\nsleep 20\n")
        hook.chmod(0o755)
        with patch.object(push, "NETWORK_TIMEOUT", 0.2):
            self.failure([repo], "超时")
        self.assertEqual(self.sha(bare), "")

    def test_preflight_failure_preserves_entire_batch_and_supplied_targets(self):
        first, first_bare = self.repository()
        second, second_bare = self.repository()
        first["target_sha"] = self.sha(first["path"])
        second["target_sha"] = self.sha(second["path"])
        Path(first["path"], "dirty").write_text("not committed")
        snapshots = []
        failure = self.failure([first, second], on_update=snapshots.append)
        self.assertEqual(len(failure.results), 2)
        self.assertEqual([row["target_sha"] for row in failure.results],
                         [first["target_sha"], second["target_sha"]])
        self.assertEqual(failure.results[1]["status"], "pending")
        self.assertEqual(snapshots[-1], failure.results)
        invalid = self.failure([{}, second])
        self.assertEqual(len(invalid.results), 2)
        self.assertEqual(invalid.results[1]["target_sha"], second["target_sha"])
        self.assertEqual(self.sha(first_bare), "")
        self.assertEqual(self.sha(second_bare), "")

    def test_missing_remote_and_partial_clone_stop_before_transport(self):
        repo, bare = self.repository()
        self.git(repo["path"], "config", "remote.origin.promisor", "true")
        self.failure([repo], "partial clone")
        self.git(repo["path"], "config", "--unset", "remote.origin.promisor")
        self.git(repo["path"], "remote", "remove", "origin")
        self.failure([repo], "remote")
        self.assertEqual(self.sha(bare), "")

    def test_linked_worktree_is_its_own_repository(self):
        repo, bare = self.repository()
        worktree = self.root / "linked"
        self.git(repo["path"], "worktree", "add", "-b", "req/linked", str(worktree))
        result = push.push_repositories([dict(name="linked", path=str(worktree))], branch="req/linked")
        self.assertEqual(result[0]["status"], "pushed")
        self.assertEqual(self.sha(bare, "refs/heads/req/linked"), self.sha(repo["path"]))
        self.assertEqual(self.sha(bare), "")

    def test_cli_multiple_repos_and_failure_exit_code(self):
        first, _ = self.repository()
        second, _ = self.repository()
        command = [os.sys.executable, str(SCRIPT), "--repo", first["path"], "--repo", second["path"]]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual([row["status"] for row in json.loads(completed.stdout)["results"]], ["pushed", "pushed"])
        Path(second["path"], "dirty").write_text("pending")
        failed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual([row["status"] for row in json.loads(failed.stdout)["results"]], ["pending", "failed"])


if __name__ == "__main__":
    unittest.main()
