from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.state import read_state, write_requirement_step_result, write_state
from steps.step_16_rule_retrospective.step import (
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    STEP,
    RuleRetrospectiveBlocked,
    result,
    run,
)
import steps.step_16_rule_retrospective.step as retrospective_step


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=check
    )


def commit(repository: Path, *paths: str, message: str = "test commit") -> str:
    git("add", "--", *paths, cwd=repository)
    git(
        "-c",
        "user.name=PCM Test",
        "-c",
        "user.email=pcm@example.invalid",
        "commit",
        "-m",
        message,
        cwd=repository,
    )
    return git("rev-parse", "HEAD", cwd=repository).stdout.strip()


def agent_result(workspace: Path, *, session: str = "development-session-1") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(workspace),
            "skills": ["session-rule-retrospective"],
            "slash_commands": ["session-rule-retrospective"],
        },
        text="已依据真实开发会话完成复盘，没有剩余复盘工作。",
        result_subtype="success",
        is_error=False,
        session_id=session,
        stop_reason="end_turn",
        num_turns=1,
        total_cost_usd=0.1,
        exception=None,
    )


def decision(
    verdict: str,
    *,
    answer: str = "",
    reason: str = "已核验",
    required_inputs: list[str] | None = None,
) -> tuple[dict, int, str]:
    value = {
        "verdict": verdict,
        "answer": answer,
        "reason": reason,
        "required_inputs": required_inputs or [],
    }
    return value, 1, json.dumps(value, ensure_ascii=False)


class RuleRetrospectiveTests(unittest.TestCase):
    def make_run(
        self,
        root: Path,
        *,
        with_rules: bool = True,
        rule_symlink: bool = False,
    ) -> tuple[Path, Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)
        (workspace / "README.md").write_text("# project\n", encoding="utf-8")
        root_paths = ["README.md"]
        if with_rules:
            rules = workspace / ".claude/rules"
            rules.mkdir(parents=True)
            if rule_symlink:
                os.symlink("../../README.md", rules / "existing.md")
            else:
                (rules / "existing.md").write_text("# 既有规则\n", encoding="utf-8")
            root_paths.append(".claude/rules/existing.md")
        frontend = workspace / "frontend"
        frontend.mkdir()
        (frontend / "README.md").write_text("# frontend\n", encoding="utf-8")

        git("init", "-b", "main", cwd=workspace)
        with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
            exclude.write("frontend/\n")
        commit(workspace, *root_paths)
        git("branch", "req/br-001", cwd=workspace)
        git("switch", "req/br-001", cwd=workspace)

        git("init", "-b", "main", cwd=frontend)
        commit(frontend, "README.md")
        git("branch", "req/br-001", cwd=frontend)
        git("switch", "req/br-001", cwd=frontend)

        bases = {
            "root": git("rev-parse", "HEAD", cwd=workspace).stdout.strip(),
            "frontend": git("rev-parse", "HEAD", cwd=frontend).stdout.strip(),
        }
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {
                "root": str(workspace_root.resolve()),
                "final_path": str(workspace.resolve()),
            },
            "applicable_repositories": ["root", "frontend"],
            "repositories": [
                {
                    "name": name,
                    "path": str((workspace if name == "root" else frontend).resolve()),
                    "branch": "main",
                    "worktree_clean": True,
                }
                for name in ("root", "frontend")
            ],
            "requirement_registry": {
                "schema_version": 1,
                "requirements": [
                    {
                        "id": "BR-001",
                        "title": "账户访问",
                        "order": 1,
                        "depends_on": [],
                        "status": "active",
                        "completion": None,
                    }
                ],
            },
            "active_requirement": "BR-001",
            "requirement_cycle": {
                "requirement_id": "BR-001",
                "branch": "req/br-001",
                "repositories": {
                    name: {"base_sha": base_sha} for name, base_sha in bases.items()
                },
                "trd_path": "docs/trd/BR-001.md",
                "development_session_id": "development-session-1",
            },
            "claude_sessions": {"development_BR-001": "development-session-1"},
            "blocked": None,
            "error": None,
        }
        write_requirement_step_result(
            run_dir,
            "BR-001",
            15,
            {
                "step": 15,
                "name": "实现与验证",
                "status": "success",
                "summary": "已完成。",
                "applicable": True,
                "outputs": [],
                "blocked": None,
                "error": None,
                "requirement_id": "BR-001",
                "trd_path": "docs/trd/BR-001.md",
                "development_session_id": "development-session-1",
            },
        )
        write_state(run_dir, state)
        return run_dir, workspace, frontend, state

    @staticmethod
    def run_step(run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    def complete(self, workspace: Path) -> tuple[object, object]:
        async def agent(*_: object, **__: object) -> ClaudeRunResult:
            return agent_result(workspace)

        async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
            return decision("completed")

        return agent, decide

    def test_no_change_reuses_development_session_with_independent_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            prompts: list[str] = []
            resumes: list[str | None] = []

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                persisted = read_state(run_dir)
                self.assertEqual(
                    persisted["claude_sessions"]["rule_retrospective_BR-001"],
                    "development-session-1",
                )
                self.assertIn("baseline", persisted["rule_retrospective_BR-001"])
                prompts.append(prompt)
                resumes.append(kwargs.get("resume_session_id"))
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(resumes, ["development-session-1"])
            self.assertEqual(len(prompts), 1)
            self.assertTrue(prompts[0].startswith("/session-rule-retrospective 本次开发会话\n"))
            for forbidden in ("第 16 步", "PCM", "requirement:", "development-session-1"):
                self.assertNotIn(forbidden, prompts[0])
            self.assertEqual(saved["outputs"], [])
            self.assertEqual(saved["development_session_id"], "development-session-1")
            self.assertEqual(
                set(saved),
                {
                    "step",
                    "name",
                    "status",
                    "summary",
                    "applicable",
                    "outputs",
                    "blocked",
                    "error",
                    "requirement_id",
                    "development_session_id",
                },
            )
            completed = read_state(run_dir)
            self.assertEqual(
                (completed["step"], completed["current_step"], completed["current_node"]),
                (17, 17, NEXT_NODE),
            )
            self.assertTrue((run_dir / "conversations/rule_retrospective_BR-001.json").is_file())
            self.assertEqual(
                completed["decision_conversations"]["rule_retrospective_BR-001"]["path"],
                "conversations/rule_retrospective_BR-001.json",
            )
            self.assertEqual(completed["requirement_registry"]["requirements"][0]["status"], "active")
            self.assertIsNone(completed["requirement_registry"]["requirements"][0]["completion"])

    def test_initial_rules_symlink_is_rejected_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(
                Path(directory), rule_symlink=True
            )
            before = (run_dir / "state.json").read_bytes()

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("规则目录含符号链接时不得调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "符号链接"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=forbidden,
                    config_loader=lambda: object(),
                )
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

    def test_existing_git_visible_external_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            external = workspace.parent / "external"
            external.mkdir()
            os.symlink(external, workspace / "external-link")
            before = (run_dir / "state.json").read_bytes()

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("外部符号链接存在时不得调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "适用仓库外"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=forbidden,
                    config_loader=lambda: object(),
                )
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

    def test_missing_rules_directory_is_valid_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(
                Path(directory), with_rules=False
            )
            agent, decide = self.complete(workspace)
            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["outputs"], [])
            self.assertFalse((workspace / ".claude/rules").exists())

    def test_rules_markdown_change_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                (workspace / ".claude/rules/retrospective.md").write_text(
                    "# 可复用规则\n", encoding="utf-8"
                )
                (workspace / ".claude/rules/existing.md").write_text(
                    "# 既有规则\n\n补充约束。\n", encoding="utf-8"
                )
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertTrue((workspace / ".claude/rules/retrospective.md").is_file())
            self.assertIn(
                "补充约束",
                (workspace / ".claude/rules/existing.md").read_text(encoding="utf-8"),
            )

    def test_existing_dirty_file_is_preserved_when_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            caller_file = workspace / "caller-notes.txt"
            caller_file.write_text("调用方已有内容\n", encoding="utf-8")
            agent, decide = self.complete(workspace)
            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(caller_file.read_text(encoding="utf-8"), "调用方已有内容\n")

    def test_existing_dirty_directory_replacement_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            readme = workspace / "README.md"
            readme.unlink()
            readme.mkdir()
            (readme / "child.txt").write_text("已有目录内容\n", encoding="utf-8")
            agent, decide = self.complete(workspace)
            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(
                (readme / "child.txt").read_text(encoding="utf-8"),
                "已有目录内容\n",
            )

    def test_unregistered_nested_git_repository_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            vendor = workspace / "vendor"
            vendor.mkdir()
            git("init", "-b", "main", cwd=vendor)
            (vendor / "README.md").write_text("# vendor\n", encoding="utf-8")
            before = (run_dir / "state.json").read_bytes()

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("未登记嵌套仓库存在时不得调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "嵌套 Git 仓库"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=forbidden,
                    config_loader=lambda: object(),
                )
            self.assertEqual((run_dir / "state.json").read_bytes(), before)

    def test_registered_child_repository_may_be_visible_in_root_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            (workspace / ".git/info/exclude").write_text("", encoding="utf-8")
            agent, decide = self.complete(workspace)
            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")

    def test_rewriting_existing_untracked_or_tracked_dirty_nonrule_is_rejected(self) -> None:
        for case in ("untracked", "tracked"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, _, state = self.make_run(Path(directory))
                target = workspace / ("caller.txt" if case == "untracked" else "README.md")
                target.write_text("调用方已有变更\n", encoding="utf-8")

                async def agent(*_: object, **__: object) -> ClaudeRunResult:
                    target.write_text("复盘错误改写\n", encoding="utf-8")
                    return agent_result(workspace)

                with self.assertRaises(RuntimeError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=lambda *_args, **_kwargs: decision("completed"),
                        config_loader=lambda: object(),
                    )
                self.assertEqual(target.read_text(encoding="utf-8"), "复盘错误改写\n")

    def test_symbolic_ref_target_change_is_rejected_even_when_sha_is_equal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            git(
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/heads/main",
                cwd=workspace,
            )

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                git(
                    "symbolic-ref",
                    "refs/remotes/origin/HEAD",
                    "refs/heads/req/br-001",
                    cwd=workspace,
                )
                return agent_result(workspace)

            with self.assertRaises(RuntimeError):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    config_loader=lambda: object(),
                )

    def test_nonroot_and_root_boundary_violations_are_rejected(self) -> None:
        cases = (
            "nonroot",
            "outside",
            "nonmd",
            "symlink",
            "hardlink",
            "parent-symlink",
            "delete",
            "rename",
            "copy",
            "stage",
            "commit",
            "branch",
            "tag",
            "pseudo-ref",
            "assume-unchanged",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, frontend, state = self.make_run(Path(directory))

                async def agent(*_: object, **__: object) -> ClaudeRunResult:
                    if case == "nonroot":
                        (frontend / "changed.py").write_text("x = 1\n", encoding="utf-8")
                    elif case == "outside":
                        (workspace / "outside.txt").write_text("outside\n", encoding="utf-8")
                    elif case == "nonmd":
                        (workspace / ".claude/rules/not-markdown.txt").write_text(
                            "bad\n", encoding="utf-8"
                        )
                    elif case == "symlink":
                        os.symlink("existing.md", workspace / ".claude/rules/link.md")
                    elif case == "hardlink":
                        external = workspace.parent / "external-rule.md"
                        external.write_text("外部内容\n", encoding="utf-8")
                        os.link(external, workspace / ".claude/rules/hardlink.md")
                    elif case == "parent-symlink":
                        rules = workspace / ".claude/rules"
                        moved = workspace / ".claude/rules-real"
                        rules.rename(moved)
                        os.symlink("rules-real", rules)
                    elif case == "delete":
                        (workspace / ".claude/rules/existing.md").unlink()
                    elif case == "rename":
                        (workspace / ".claude/rules/existing.md").rename(
                            workspace / ".claude/rules/renamed.md"
                        )
                    elif case == "copy":
                        source = workspace / ".claude/rules/existing.md"
                        target = workspace / ".claude/rules/copied.md"
                        target.write_bytes(source.read_bytes())
                        git("add", "--", ".claude/rules/copied.md", cwd=workspace)
                        git("config", "status.renames", "copies", cwd=workspace)
                    elif case == "stage":
                        path = workspace / ".claude/rules/staged.md"
                        path.write_text("staged\n", encoding="utf-8")
                        git("add", "--", ".claude/rules/staged.md", cwd=workspace)
                    elif case == "commit":
                        path = workspace / ".claude/rules/committed.md"
                        path.write_text("committed\n", encoding="utf-8")
                        commit(workspace, ".claude/rules/committed.md")
                    elif case == "branch":
                        git("branch", "retrospective-scratch", cwd=workspace)
                    elif case == "tag":
                        git("tag", "retrospective-marker", cwd=workspace)
                    elif case == "pseudo-ref":
                        git_path = git(
                            "rev-parse", "--git-path", "ORIG_HEAD", cwd=workspace
                        ).stdout.strip()
                        target = Path(git_path)
                        if not target.is_absolute():
                            target = workspace / target
                        target.write_text(
                            git("rev-parse", "HEAD", cwd=workspace).stdout,
                            encoding="utf-8",
                        )
                    else:
                        git(
                            "update-index",
                            "--assume-unchanged",
                            "README.md",
                            cwd=workspace,
                        )
                        (workspace / "README.md").write_text(
                            "被 index 标志隐藏的改写\n", encoding="utf-8"
                        )
                    return agent_result(workspace)

                with self.assertRaises(RuntimeError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=lambda *_args, **_kwargs: decision("completed"),
                        config_loader=lambda: object(),
                    )
                self.assertIn("baseline", read_state(run_dir)["rule_retrospective_BR-001"])

    def test_fresh_ref_drift_has_no_state_or_agent_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            (workspace / "drift.txt").write_text("drift\n", encoding="utf-8")
            commit(workspace, "drift.txt")
            before = (run_dir / "state.json").read_bytes()
            called = False

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                nonlocal called
                called = True
                return agent_result(workspace)

            with self.assertRaisesRegex(RuntimeError, "未提交基线"):
                self.run_step(run_dir, state, agent_runner=agent, config_loader=lambda: object())
            self.assertFalse(called)
            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            self.assertNotIn("rule_retrospective_BR-001", read_state(run_dir))

    def test_baseline_is_persisted_and_recovery_does_not_resample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))

            async def interrupted(*_: object, **__: object) -> ClaudeRunResult:
                raise OSError("simulated interruption")

            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, state, agent_runner=interrupted, config_loader=lambda: object())
            interrupted_state = read_state(run_dir)
            baseline = interrupted_state["rule_retrospective_BR-001"]["baseline"]
            resumes: list[str | None] = []

            async def agent(*_: object, **kwargs: object) -> ClaudeRunResult:
                resumes.append(kwargs.get("resume_session_id"))
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            with patch.object(
                retrospective_step,
                "_verify_fresh_repositories",
                side_effect=AssertionError("恢复时不得重新采样基线"),
            ):
                self.run_step(
                    run_dir,
                    interrupted_state,
                    agent_runner=agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            self.assertEqual(resumes, ["development-session-1"])
            self.assertEqual(
                read_state(run_dir)["rule_retrospective_BR-001"]["baseline"], baseline
            )

    def test_blocked_keeps_anchor_baseline_and_original_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            agent, _ = self.complete(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("blocked", reason="缺少外部授权", required_inputs=["外部授权"])

            with self.assertRaises(RuleRetrospectiveBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            blocked = read_state(run_dir)
            self.assertEqual(
                (blocked["step"], blocked["current_step"], blocked["current_node"]),
                (STEP, STEP, CURRENT_NODE),
            )
            self.assertEqual(blocked["claude_sessions"]["development_BR-001"], "development-session-1")
            self.assertEqual(
                blocked["claude_sessions"]["rule_retrospective_BR-001"], "development-session-1"
            )
            self.assertIn("baseline", blocked["rule_retrospective_BR-001"])
            saved = json.loads(
                (run_dir / "steps/requirements/BR-001/16.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["status"], "blocked")

    def test_result_then_state_recovery_and_advanced_rerun_skip_agent_and_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            agent, decide = self.complete(workspace)
            original_write_state = retrospective_step.write_state

            def interrupt_advance(path: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("simulated state interruption")
                original_write_state(path, value)

            with patch.object(retrospective_step, "write_state", side_effect=interrupt_advance):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=decide,
                        config_loader=lambda: object(),
                    )
            interrupted = read_state(run_dir)
            self.assertEqual(interrupted["current_node"], CURRENT_NODE)
            self.assertEqual(
                json.loads(
                    (run_dir / "steps/requirements/BR-001/16.json").read_text(encoding="utf-8")
                )["status"],
                "success",
            )

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("不应再次调用 Agent")

            recovered = self.run_step(run_dir, interrupted, agent_runner=forbidden)
            advanced = read_state(run_dir)
            with patch.object(
                retrospective_step,
                "_git_run",
                side_effect=AssertionError("推进后不应读取 Git"),
            ):
                self.assertEqual(self.run_step(run_dir, advanced, agent_runner=forbidden), recovered)

    def test_agent_returning_different_session_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace, session="replacement-session")

            with self.assertRaisesRegex(RuntimeError, "session"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    config_loader=lambda: object(),
                )
            self.assertEqual(
                read_state(run_dir)["claude_sessions"]["rule_retrospective_BR-001"],
                "development-session-1",
            )

    def test_cycle_and_development_result_trd_mismatch_fails_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            state["requirement_cycle"]["trd_path"] = "docs/trd/other.md"
            write_state(run_dir, state)

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("TRD 交接不一致时不得调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "第 15 步"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=forbidden,
                    config_loader=lambda: object(),
                )

    def test_inconsistent_development_session_fails_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _, state = self.make_run(Path(directory))
            state["requirement_cycle"]["development_session_id"] = "other-session"
            write_state(run_dir, state)

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("session 不一致时不得调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "开发 session"):
                self.run_step(run_dir, state, agent_runner=forbidden, config_loader=lambda: object())


if __name__ == "__main__":
    unittest.main()
