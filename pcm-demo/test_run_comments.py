from __future__ import annotations

import copy
import io
import json
import os
import shlex
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from functools import partial
from pathlib import Path
from unittest.mock import AsyncMock, patch

import run_comments
from common.agent_decision_loop import run_agent_decision_loop
from common.claude_agent import ClaudeRunResult
from common.coordination import (
    acquire_execution_locks, acquire_product_lock, claim_product, ensure_runtime,
    lock_status, product_key, product_lock_path, run_lock_path,
)
from common.decision import AgentDecision
from common.state import create_run_dir, read_state, write_state
from quality.git import git


class CommentsCLITests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.runs = self.root / "runs"
        self.coordination = self.runs / ".coordination"
        self.product = self.root / "product"
        self.repos = {"root": self.product, "frontend": self.product / "frontend",
                      "backend": self.product / "backend"}
        for name, repo in self.repos.items():
            repo.mkdir(parents=True)
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.name", "Comments Test")
            git(repo, "config", "user.email", "comments@example.invalid")
            git(repo, "config", "commit.gpgsign", "false")
            git(repo, "config", "core.hooksPath", str(self.root / "no-hooks"))
            git(repo, "config", "core.filemode", "true")
            if name == "root":
                (repo / ".gitignore").write_text("/frontend/\n/backend/\n", encoding="utf-8")
            (repo / "code.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "test: 初始化临时仓库")
        self.key, self.product = product_key(self.product)
        record = claim_product(self.coordination, "source", self.key, self.product)
        ensure_runtime(self.product, self.key, "source", record)
        self.source = {
            "run_id": "source", "status": "success",
            "workspace": {"root": str(self.root), "final_path": str(self.product)},
            "applicable_repositories": list(self.repos),
            "repositories": [{"name": name, "path": str(repo)} for name, repo in self.repos.items()],
            "coordination": {
                "schema_version": 1, "execution_run_id": "source", "claim_phase": "claimed",
                "product_key": self.key, "product_path": str(self.product),
                "port_slot": record["port_slot"], "ports": record["ports"],
                "runtime_path": ".pcm/runtime.json",
            },
        }
        source_dir = create_run_dir(self.runs, "source")
        write_state(source_dir, self.source)
        (source_dir / "timings.json").write_bytes(b'{ "schema_version": 2, "steps": [] }\n')
        self.before = self.protected_bytes()
        self.versions = {name: git(repo, "rev-parse", "HEAD") for name, repo in self.repos.items()}
        self.agent = AsyncMock(return_value=self.result())
        self.decision = AsyncMock(return_value=self.verdict("completed"))
        # 仅注入模型与裁决边界，状态、对话恢复、Git 和本机锁均走真实实现。
        loop = partial(run_agent_decision_loop, agent_runner=self.agent,
                       decision_runner=self.decision, config_loader=lambda: None)
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        for context in (
            patch.object(run_comments, "RUNS_DIR", self.runs),
            patch.object(run_comments, "COORDINATION_ROOT", self.coordination),
            patch.object(run_comments, "run_agent_decision_loop", loop),
            patch.dict(os.environ, {"PCM_MAX_CONCURRENT_PROJECTS": "2"}),
            redirect_stdout(self.stdout), redirect_stderr(self.stderr),
        ):
            self.stack.enter_context(context)

    def result(self, **changes):
        fields = {
            "init": {"cwd": str(self.product), "skills": [], "slash_commands": []},
            "text": "测试边界返回的完整报告\r\n保留格式\n", "result_subtype": "success",
            "is_error": False, "session_id": "comments-session", "stop_reason": None,
            "num_turns": 1, "total_cost_usd": 0, "exception": None,
        }
        return ClaudeRunResult(**{**fields, **changes})

    def verdict(self, verdict):
        value = AgentDecision(verdict=verdict, answer="", reason="测试裁决",
                              required_inputs=["补充资料"] if verdict == "blocked" else [])
        return value.model_dump(), [], value.model_dump_json()

    def start(self, run_id="comments", workspace=None):
        return run_comments.main(["--workspace", str(workspace or self.product), "--run-id", run_id])

    def resume(self, *extra):
        return run_comments.main(["--resume", "comments", *extra])

    def state(self):
        return read_state(self.runs / "comments")

    def conversation(self):
        path = self.runs / "comments/conversations/code_comments.json"
        return json.loads(path.read_bytes())["messages"]

    def protected_bytes(self):
        paths = list((self.runs / "source").rglob("*"))
        paths += [self.coordination / "products.json", self.product / ".pcm/runtime.json",
                  self.product / ".gitignore", self.product / ".git/info/exclude"]
        return {str(path): path.read_bytes() for path in paths if path.is_file()}

    def product_files(self):
        return {str(path.relative_to(self.product)): (path.read_bytes(), path.stat().st_mode)
                for path in self.product.rglob("*")
                if ".git" not in path.relative_to(self.product).parts and path.is_file()}

    def scene(self):
        return self.product_files(), {
            name: (git(repo, "rev-parse", "HEAD"), git(repo, "branch", "--show-current"),
                   git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
                   git(repo, "diff", "--cached", "--binary"))
            for name, repo in self.repos.items()
        }

    def test_cli_constraints(self):
        args = run_comments.parse_args(["--workspace", str(self.product), "--run-id", "comments"])
        self.assertEqual((args.workspace, args.run_id, args.resume), (self.product, "comments", None))
        args = run_comments.parse_args(["--resume", "comments", "--resume-message-file", "message.txt"])
        self.assertEqual(args.resume_message_file, Path("message.txt"))
        for argv in ([], ["--workspace", str(self.product), "--resume", "comments"],
                     ["--resume", "comments", "--run-id", "other"],
                     ["--workspace", str(self.product), "--resume-message-file", "message.txt"],
                     ["--resume", "comments", "--source-run", "source"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as error:
                run_comments.parse_args(argv)
            self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.protected_bytes(), self.before)
        self.agent.assert_not_awaited()

    def test_clean_registered_repositories_receive_current_skill_without_installation(self):
        before = self.scene()
        skill = (run_comments.SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        reference = (run_comments.SKILL_ROOT / "references/language-conventions.md").read_text(encoding="utf-8")

        async def respond(prompt, **kwargs):
            self.assertTrue(lock_status(run_lock_path(self.coordination, "comments"))[0])
            self.assertTrue(lock_status(product_lock_path(self.coordination, self.key))[0])
            return self.result()

        self.agent.side_effect = respond
        self.assertEqual(self.start(), 0, self.stderr.getvalue())
        state = self.state()
        self.assertEqual((state["status"], state["current_node"]), ("success", run_comments.COMPLETED_NODE))
        self.assertEqual(state["entry_versions"], self.versions)
        self.assertEqual(state["coordination"]["owner_run_id"], "source")
        self.assertEqual(state["coordination"]["execution_run_id"], "comments")
        self.assertIsNone(run_comments.loop_spec(state).skill_name)
        self.agent.assert_awaited_once()
        prompt = self.agent.await_args.args[0]
        self.assertIn(skill, prompt)
        self.assertIn(reference, prompt)
        for repo in self.repos.values():
            self.assertIn(str(repo), prompt)
            self.assertFalse((repo / ".claude").exists())
        self.assertEqual(state["initial_prompt"], prompt)
        self.assertEqual(self.conversation()[1]["content"], prompt)
        self.assertEqual(state["summary"], self.result().text)
        kwargs = self.agent.await_args.kwargs
        self.assertEqual((kwargs["cwd"], kwargs["resume_session_id"], kwargs["task"]),
                         (self.product, None, "development"))
        profile = run_comments.get_agent_profile("development")
        self.assertEqual((kwargs["model"], kwargs["effort"]), (profile.model, profile.effort))
        self.assertEqual(self.scene(), before)
        self.assertEqual(self.protected_bytes(), self.before)

    def test_comment_edits_remain_unstaged_and_uncommitted_in_all_repositories(self):
        edited = {}

        async def respond(prompt, **kwargs):
            for repo in self.repos.values():
                path = repo / "code.py"
                edited[path] = b"# fixture comment\n" + path.read_bytes()
                path.write_bytes(edited[path])
            return self.result()

        self.agent.side_effect = respond
        self.assertEqual(self.start(), 0, self.stderr.getvalue())
        for name, repo in self.repos.items():
            self.assertEqual((repo / "code.py").read_bytes(), edited[repo / "code.py"])
            self.assertEqual(git(repo, "rev-parse", "HEAD"), self.versions[name])
            self.assertEqual(git(repo, "branch", "--show-current"), "main")
            self.assertEqual(git(repo, "diff", "--cached", "--name-only"), "")
            self.assertEqual(git(repo, "diff", "--name-only"), "code.py")
            self.assertEqual(git(repo, "ls-files", "--others", "--exclude-standard"), "")
        self.assertEqual(self.protected_bytes(), self.before)

    def test_completed_resume_returns_saved_result_without_agent_or_writes(self):
        self.assertEqual(self.start(), 0)
        path = self.runs / "comments"
        before = {p: p.read_bytes() for p in path.rglob("*") if p.is_file()}
        (self.product / "code.py").write_text("# 后续人工编辑\n", encoding="utf-8")
        product_before = self.scene()
        self.assertEqual(self.resume(), 0)
        self.agent.assert_awaited_once()
        self.decision.assert_awaited_once()
        self.assertEqual({p: p.read_bytes() for p in path.rglob("*") if p.is_file()}, before)
        self.assertEqual(self.scene(), product_before)
        self.assertEqual(self.protected_bytes(), self.before)

    def test_existing_dirty_staged_and_untracked_changes_are_preserved_and_rejected(self):
        for name, repo in self.repos.items():
            for kind in ("dirty", "staged", "untracked"):
                with self.subTest(repo=name, kind=kind):
                    path = repo / ("untracked.py" if kind == "untracked" else "code.py")
                    original = path.read_bytes() if path.exists() else None
                    try:
                        path.write_bytes(b"# existing user work\n")
                        if kind == "staged":
                            git(repo, "add", "code.py")
                        before = self.scene()
                        run_id = f"{name}-{kind}"
                        self.assertEqual(self.start(run_id), 1)
                        self.assertFalse((self.runs / run_id).exists())
                        self.assertEqual(self.scene(), before)
                        self.agent.assert_not_awaited()
                    finally:
                        if kind == "staged":
                            git(repo, "reset", "--", "code.py")
                        if original is None:
                            path.unlink()
                        else:
                            path.write_bytes(original)
        self.assertEqual(self.protected_bytes(), self.before)

    def test_initial_non_main_branch_is_rejected(self):
        repo = self.repos["frontend"]
        git(repo, "checkout", "-b", "feature")
        before = self.scene()
        self.assertEqual(self.start(), 1)
        self.assertEqual(self.scene(), before)
        self.assertFalse((self.runs / "comments").exists())
        self.agent.assert_not_awaited()

    def test_wrong_source_owner_and_repository_paths_are_rejected_without_repair(self):
        for kind in ("owner", "workspace", "repository"):
            with self.subTest(kind=kind):
                source = copy.deepcopy(self.source)
                if kind == "owner":
                    source["coordination"]["execution_run_id"] = "foreign"
                elif kind == "workspace":
                    source["workspace"]["final_path"] = str(self.root / "foreign")
                else:
                    source["repositories"][1]["path"] = str(self.root / "foreign")
                write_state(self.runs / "source", source)
                before = self.protected_bytes()
                self.assertEqual(self.start(kind), 1)
                self.assertEqual(self.protected_bytes(), before)
                self.assertFalse((self.runs / kind).exists())
                self.agent.assert_not_awaited()

    def test_nested_directory_must_be_an_independent_repository(self):
        (self.repos["frontend"] / ".git").rename(self.root / "frontend-git")
        before = self.product_files()
        self.assertEqual(self.start(), 1)
        self.assertEqual(self.product_files(), before)
        self.assertFalse((self.runs / "comments").exists())
        self.agent.assert_not_awaited()

    def assert_boundary_refuses(self, mutate):
        scenes = []

        async def respond(prompt, **kwargs):
            mutate(self.repos["backend"])
            scenes.append(self.scene())
            return self.result()

        self.agent.side_effect = respond
        self.assertEqual(self.start(), 1, self.stderr.getvalue())
        self.assertEqual(self.state()["status"], "failed")
        self.assertEqual(self.state()["current_node"], run_comments.NODE)
        self.assertEqual(self.scene(), scenes[0])
        saved = (self.runs / "comments/state.json").read_bytes()
        self.assertEqual(self.resume(), 1)
        self.assertEqual((self.runs / "comments/state.json").read_bytes(), saved)
        self.assertEqual(self.scene(), scenes[0])
        self.agent.assert_awaited_once()
        self.assertEqual(self.protected_bytes(), self.before)

    def test_branch_drift_is_rejected_at_completion_and_resume(self):
        self.assert_boundary_refuses(lambda repo: git(repo, "checkout", "-b", "foreign"))

    def test_head_drift_is_rejected_at_completion_and_resume(self):
        self.assert_boundary_refuses(lambda repo: git(repo, "commit", "--allow-empty", "-m", "test: HEAD 漂移"))

    def test_added_file_is_rejected_at_completion_and_resume(self):
        self.assert_boundary_refuses(lambda repo: (repo / "added.py").write_bytes(b"# added\n"))

    def test_deleted_file_is_rejected_at_completion_and_resume(self):
        self.assert_boundary_refuses(lambda repo: (repo / "code.py").unlink())

    def test_changed_file_mode_is_rejected_at_completion_and_resume(self):
        self.assert_boundary_refuses(lambda repo: (repo / "code.py").chmod(0o755))

    def test_staged_edit_is_rejected_at_completion_and_resume(self):
        def mutate(repo):
            (repo / "code.py").write_bytes(b"# staged edit\n")
            git(repo, "add", "code.py")
        self.assert_boundary_refuses(mutate)

    def test_run_lock_contention_rejects_new_and_resume_then_releases(self):
        with acquire_execution_locks(self.coordination, "comments", 2) as held:
            self.assertEqual(self.start(), 1)
            self.assertTrue(lock_status(held.run.path)[0])
            self.assertFalse((self.runs / "comments").exists())
            self.agent.assert_not_awaited()
        self.decision.return_value = self.verdict("blocked")
        self.assertEqual(self.start(), 2)
        before = (self.runs / "comments/state.json").read_bytes()
        with acquire_execution_locks(self.coordination, "comments", 2):
            self.assertEqual(self.resume(), 1)
            self.assertEqual((self.runs / "comments/state.json").read_bytes(), before)
        self.agent.assert_awaited_once()
        self.decision.return_value = self.verdict("completed")
        self.assertEqual(self.resume(), 0)
        self.assertEqual(self.protected_bytes(), self.before)

    def test_product_lock_contention_rejects_new_and_resume_then_releases(self):
        with acquire_product_lock(self.coordination, "source", self.key, self.product) as held:
            self.assertEqual(self.start(), 1)
            self.assertTrue(lock_status(held.path)[0])
            self.assertFalse((self.runs / "comments").exists())
            self.agent.assert_not_awaited()
        self.decision.return_value = self.verdict("blocked")
        self.assertEqual(self.start(), 2)
        before = (self.runs / "comments/state.json").read_bytes()
        with acquire_product_lock(self.coordination, "source", self.key, self.product):
            self.assertEqual(self.resume(), 1)
            self.assertEqual((self.runs / "comments/state.json").read_bytes(), before)
        self.agent.assert_awaited_once()
        self.decision.return_value = self.verdict("completed")
        self.assertEqual(self.resume(), 0)
        self.assertEqual(self.protected_bytes(), self.before)

    def test_agent_failure_saves_diagnostic_and_resumes_original_loop(self):
        async def fail(prompt, **kwargs):
            kwargs["on_update"](self.result(result_subtype=None, text=""))
            (self.repos["frontend"] / "code.py").write_bytes(b"# interrupted edit\n")
            raise RuntimeError("测试调用中断")

        self.agent.side_effect = fail
        self.assertEqual(self.start(), 1)
        state = self.state()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error"]["type"], "AgentExecutionFailure")
        self.assertTrue((self.runs / "comments" / state["error"]["diagnostic_path"]).is_file())
        self.assertEqual(state["claude_sessions"], {run_comments.KEY: "comments-session"})
        messages, scene = self.conversation(), self.scene()
        self.agent.side_effect = None
        self.assertEqual(self.resume(), 0, self.stderr.getvalue())
        self.assertEqual(self.agent.await_count, 2)
        self.assertEqual(self.agent.await_args.kwargs["resume_session_id"], "comments-session")
        self.assertEqual(self.conversation()[:len(messages)], messages)
        self.assertEqual(self.state()["decision_conversations"], state["decision_conversations"])
        self.assertEqual(self.scene(), scene)
        self.assertEqual(self.protected_bytes(), self.before)

    def test_blocked_result_and_plain_resume_reuse_original_loop(self):
        self.decision.return_value = self.verdict("blocked")
        self.assertEqual(self.start(), 2)
        state, messages = self.state(), self.conversation()
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["blocked"]["required_inputs"], ["补充资料"])
        self.decision.return_value = self.verdict("completed")
        self.assertEqual(self.resume(), 0)
        self.assertEqual(self.agent.await_args.kwargs["resume_session_id"], "comments-session")
        self.assertEqual(self.conversation()[:len(messages)], messages)
        self.assertEqual(self.state()["decision_conversations"], state["decision_conversations"])
        self.assertIsNone(self.state()["blocked"])
        self.assertEqual(self.protected_bytes(), self.before)

    def test_resume_message_uses_public_original_conversation_and_preserves_input(self):
        self.decision.return_value = self.verdict("blocked")
        self.assertEqual(self.start(), 2)
        messages = self.conversation()
        message = self.root / "message.txt"
        content = "  已补齐资料\r\n继续原任务，不扩大范围。\n"
        message.write_bytes(content.encode("utf-8"))
        self.decision.return_value = self.verdict("completed")
        self.assertEqual(self.resume("--resume-message-file", str(message)), 0, self.stderr.getvalue())
        self.assertEqual(self.agent.await_count, 2)
        self.assertEqual(self.agent.await_args.args[0], content)
        self.assertEqual(self.agent.await_args.kwargs["resume_session_id"], "comments-session")
        current = self.conversation()
        self.assertEqual(current[:len(messages)], messages)
        self.assertEqual(current[len(messages)]["content"], content)
        self.assertEqual(message.read_bytes(), content.encode("utf-8"))
        self.assertEqual(self.protected_bytes(), self.before)

    def test_invalid_resume_message_and_missing_session_do_not_execute_or_write(self):
        self.decision.return_value = self.verdict("blocked")
        self.assertEqual(self.start(), 2)
        message = self.root / "message.txt"
        path = self.runs / "comments/state.json"
        before = path.read_bytes()
        for data in (None, b" \n\t", b"\xff"):
            with self.subTest(data=data):
                if data is not None:
                    message.write_bytes(data)
                self.assertEqual(self.resume("--resume-message-file", str(message)), 1)
                self.assertEqual(path.read_bytes(), before)
                self.agent.assert_awaited_once()
        message.write_text("补充资料", encoding="utf-8")
        state = self.state()
        state.pop("claude_sessions")
        write_state(path.parent, state)
        before = path.read_bytes()
        self.assertEqual(self.resume("--resume-message-file", str(message)), 1)
        self.assertEqual(path.read_bytes(), before)
        self.agent.assert_awaited_once()

    def test_recovery_command_preserves_run_id_as_one_shell_argument(self):
        self.decision.return_value = self.verdict("blocked")
        run_id = "comments demo"
        self.assertEqual(self.start(run_id), 2)
        command = self.stderr.getvalue().split("恢复命令：", 1)[1].strip()
        self.assertEqual(shlex.split(command), [
            "uv", "run", "python", "run_comments.py", "--resume", run_id,
        ])
        self.decision.return_value = self.verdict("completed")
        self.assertEqual(run_comments.main(shlex.split(command)[4:]), 0)
        self.assertEqual(self.agent.await_args.kwargs["resume_session_id"], "comments-session")

    def test_completed_run_rejects_resume_message(self):
        self.assertEqual(self.start(), 0)
        path = self.runs / "comments/state.json"
        before = path.read_bytes()
        message = self.root / "message.txt"
        message.write_text("补充资料", encoding="utf-8")
        self.assertEqual(self.resume("--resume-message-file", str(message)), 1)
        self.assertEqual(path.read_bytes(), before)
        self.agent.assert_awaited_once()

    def test_invalid_workspace_and_run_paths_are_rejected(self):
        link = self.root / "product-link"
        link.symlink_to(self.product, target_is_directory=True)
        file = self.root / "not-directory"
        file.write_bytes(b"unchanged")
        before = self.scene()
        for workspace in (Path("relative-product"), self.root / "missing", file, link):
            with self.subTest(workspace=workspace):
                self.assertEqual(self.start(workspace=workspace), 1)
        for run_id in ("", ".", "..", "../escape", "nested/run", str(self.root / "absolute")):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                run_comments.run_dir_for(run_id)
        for run_id in ("..", "../escape", "nested/run"):
            self.assertEqual(self.start(run_id), 1)
        (self.runs / "linked-run").symlink_to(self.runs / "source", target_is_directory=True)
        self.assertEqual(self.start("linked-run"), 1)
        self.assertEqual(run_comments.main(["--resume", "linked-run"]), 1)
        self.assertEqual(self.scene(), before)
        self.assertEqual(self.protected_bytes(), self.before)
        self.agent.assert_not_awaited()

    def test_symlink_repository_is_rejected(self):
        repo = self.repos["frontend"]
        target = self.root / "frontend-real"
        repo.rename(target)
        repo.symlink_to(target, target_is_directory=True)
        before = (target / "code.py").read_bytes()
        self.assertEqual(self.start(), 1)
        self.assertTrue(repo.is_symlink())
        self.assertEqual((target / "code.py").read_bytes(), before)
        self.assertFalse((self.runs / "comments").exists())
        self.agent.assert_not_awaited()

    def test_new_run_never_overwrites_existing_directory_or_source(self):
        self.assertEqual(self.start(), 0)
        for run_id in ("comments", "source", "unfinished"):
            with self.subTest(run_id=run_id):
                path = self.runs / run_id
                path.mkdir(exist_ok=True)
                (path / "sentinel.bin").write_bytes(b"\x00preserve\xff")
                before = {p: p.read_bytes() for p in path.rglob("*") if p.is_file()}
                self.assertEqual(self.start(run_id), 1)
                self.assertEqual({p: p.read_bytes() for p in path.rglob("*") if p.is_file()}, before)
        self.agent.assert_awaited_once()

    def test_resume_rejects_foreign_workflow_without_writing(self):
        before = (self.runs / "source/state.json").read_bytes()
        self.assertEqual(run_comments.main(["--resume", "source"]), 1)
        self.assertEqual((self.runs / "source/state.json").read_bytes(), before)
        self.agent.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
