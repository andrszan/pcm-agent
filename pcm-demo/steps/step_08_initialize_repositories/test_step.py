from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.files import write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_03_foundation_selection.step import TemplateSelection
from steps.step_08_initialize_repositories.step import (
    CURRENT_NODE,
    DECISION_LOOP_SPEC,
    INITIAL_COMMITS_PREFIX,
    INITIAL_COMMITS_REPAIR_PROMPT,
    INITIALIZE_REPOSITORIES_MAX_BUDGET_USD,
    INITIALIZE_REPOSITORIES_MAX_TURNS,
    NEXT_NODE,
    InitializeRepositoriesBlocked,
    run,
)
import steps.step_08_initialize_repositories.step as initialize_step


def command(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


def commit_all(repository: Path, message: str = "initial baseline") -> str:
    command("add", ".", cwd=repository)
    command(
        "-c",
        "user.name=PCM Test",
        "-c",
        "user.email=pcm@example.invalid",
        "commit",
        "-m",
        message,
        cwd=repository,
    )
    return command("rev-parse", "HEAD", cwd=repository)


def marker(names: list[str], workspace: Path) -> str:
    commits = [
        {"name": name, "sha": command("rev-parse", "HEAD", cwd=workspace if name == "root" else workspace / name)}
        for name in names
    ]
    return INITIAL_COMMITS_PREFIX + json.dumps({"repositories": commits}, ensure_ascii=False)


def agent_result(*, cwd: Path, text: str, session: str = "session-1") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={"cwd": str(cwd), "skills": ["commit-changes"], "slash_commands": ["commit-changes"]},
        text=text,
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
    reason: str = "完成条件已经满足",
    required_inputs: list[str] | None = None,
) -> tuple[dict, int, str]:
    data = {
        "verdict": verdict,
        "answer": answer,
        "reason": reason,
        "required_inputs": required_inputs or [],
    }
    return data, 1, json.dumps(data, ensure_ascii=False)


class InitializeRepositoriesTests(unittest.TestCase):
    def make_run(self, root: Path, outputs: list[str]) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        (workspace / "docs/requirements").mkdir(parents=True)
        for path in (
            "docs/requirements/项目需求说明.md",
            "docs/requirements/产品功能说明.md",
            "docs/requirements/项目准备清单.md",
        ):
            (workspace / path).write_text(f"# {Path(path).stem}\n", encoding="utf-8")
        design = workspace / "docs/design/技术方案.md"
        design.parent.mkdir(parents=True)
        design.write_text("# 总体技术方案\n", encoding="utf-8")

        selections: dict[str, dict | None] = {"frontend": None, "backend": None}
        assembly: dict[str, dict | None] = {"frontend": None, "backend": None}
        if outputs:
            (workspace / ".gitignore").write_text(
                "".join(f"{name}/\n" for name in outputs), encoding="utf-8"
            )
        for target in outputs:
            project = workspace / target
            project.mkdir()
            (project / f"{target}.txt").write_text(target, encoding="utf-8")
            initialize_root_repository(project)
            selected = TemplateSelection(
                id=f"{target}-template",
                git_url="file:///templates.git",
                default_branch="main",
                path=f"templates/{target}",
                reason="test",
            )
            selections[target] = selected.model_dump(mode="json")
            assembly[target] = {
                "target": target,
                "id": selected.id,
                "git_url": selected.git_url,
                "default_branch": selected.default_branch,
                "path": selected.path,
                "origin": selected.git_url,
                "branch": "main",
                "commit_sha": "a" * 40,
            }

        write_json(
            run_dir / "steps/03.json",
            {"step": 3, "status": "success", "template_selection": selections},
        )
        write_json(
            run_dir / "steps/04.json",
            {
                "step": 4,
                "status": "success",
                "applicable": bool(outputs),
                "outputs": outputs,
                "assembly": assembly,
            },
        )
        write_json(
            run_dir / "steps/05.json",
            {"step": 5, "status": "success", "outputs": ["docs/requirements/项目准备清单.md"]},
        )
        write_json(
            run_dir / "steps/06.json",
            {"step": 6, "status": "success", "applicable": bool(outputs), "outputs": outputs},
        )
        write_json(
            run_dir / "steps/07.json",
            {
                "step": 7,
                "status": "success",
                "applicable": True,
                "outputs": ["docs/design/技术方案.md"],
            },
        )
        root_repository = initialize_root_repository(workspace)
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": "project_initialization",
            "step": 8,
            "current_step": 8,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "root_repository": root_repository,
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    def run_step(self, run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    @staticmethod
    def commit_repositories(workspace: Path, names: list[str]) -> None:
        for name in names:
            commit_all(workspace if name == "root" else workspace / name)

    def test_root_only_and_all_repositories_complete_in_one_agent_call(self) -> None:
        for outputs in ([], ["frontend", "backend"]):
            with self.subTest(outputs=outputs), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), outputs)
                names = ["root", *outputs]
                calls: list[dict] = []
                decisions: list[str] = []

                async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    calls.append({"prompt": prompt, **kwargs})
                    self.commit_repositories(workspace, names)
                    current = agent_result(cwd=kwargs["cwd"], text=f"完成\n{marker(names, workspace)}")  # type: ignore[arg-type, index]
                    kwargs["on_update"](current)  # type: ignore[index, operator]
                    return current

                async def completed(messages, config, *, system_prompt):
                    decisions.append(system_prompt)
                    return decision("completed")

                saved = self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["cwd"].resolve(), workspace.resolve())
                self.assertIsNone(calls[0]["resume_session_id"])
                self.assertEqual(calls[0]["max_turns"], INITIALIZE_REPOSITORIES_MAX_TURNS)
                self.assertEqual(calls[0]["max_budget_usd"], INITIALIZE_REPOSITORIES_MAX_BUDGET_USD)
                self.assertEqual(decisions, [DECISION_LOOP_SPEC.decision_system_prompt])
                prompt = calls[0]["prompt"]
                self.assertTrue(prompt.startswith("/commit-changes\n"))
                self.assertIn("权威仓库清单", prompt)
                self.assertIn("组装事实", prompt)
                self.assertIn("INITIAL_COMMITS_JSON", prompt)
                for forbidden in ("第 8 步", "PCM", "节点", "session", "决策模型", "轮次", "预算"):
                    self.assertNotIn(forbidden, prompt)
                self.assertEqual(saved["applicable_repositories"], names)
                self.assertEqual(list(saved["initial_commits"]), names)
                self.assertEqual(saved["outputs"], [])
                self.assertEqual((read_state(run_dir)["step"], read_state(run_dir)["current_node"]), (9, NEXT_NODE))
                self.assertEqual(command("rev-list", "--count", "HEAD", cwd=workspace), "1")
                self.assertFalse(command("ls-tree", "HEAD", "--", "frontend", "backend", cwd=workspace))

    def test_missing_marker_or_unborn_repository_uses_same_session_repair(self) -> None:
        for case in ("marker", "unborn"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
                names = ["root", "frontend"]
                calls: list[dict] = []

                async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    calls.append({"prompt": prompt, **kwargs})
                    if len(calls) == 1 and case == "marker":
                        self.commit_repositories(workspace, names)
                        text = "提交已完成"
                    elif len(calls) == 1:
                        text = "尚未提交"
                    else:
                        if case == "unborn":
                            self.commit_repositories(workspace, names)
                        text = marker(names, workspace)
                    current = agent_result(cwd=kwargs["cwd"], text=text)  # type: ignore[arg-type, index]
                    kwargs["on_update"](current)  # type: ignore[index, operator]
                    return current

                async def completed(messages, config, *, system_prompt):
                    return decision("completed")

                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )
                self.assertEqual(len(calls), 2)
                self.assertIsNone(calls[0]["resume_session_id"])
                self.assertEqual(calls[1]["resume_session_id"], "session-1")
                self.assertEqual(calls[1]["prompt"], INITIAL_COMMITS_REPAIR_PROMPT)

    def test_blocked_partial_submission_resumes_without_rewriting_existing_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            names = ["root", "frontend"]
            calls: list[dict] = []
            decisions = ["blocked", "completed"]

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 1:
                    commit_all(workspace)
                    text = "根仓已提交，等待外部授权"
                else:
                    commit_all(workspace / "frontend")
                    text = marker(names, workspace)
                current = agent_result(cwd=kwargs["cwd"], text=text)  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def decide(messages, config, *, system_prompt):
                verdict = decisions.pop(0)
                if verdict == "blocked":
                    return decision("blocked", reason="缺少授权", required_inputs=["授权"])
                return decision("completed")

            with self.assertRaises(InitializeRepositoriesBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                )
            root_sha = command("rev-parse", "HEAD", cwd=workspace)
            blocked_state = read_state(run_dir)
            self.assertEqual(blocked_state["status"], "blocked")
            self.assertEqual(
                blocked_state["initialize_repositories"]["observed_heads"],
                {"root": root_sha, "frontend": None},
            )
            write_json(
                run_dir / "steps/08.json",
                initialize_step.result(
                    "blocked",
                    "缺少授权",
                    blocked={
                        "reason": "缺少授权",
                        "required_inputs": ["授权"],
                        "applicable_repositories": names,
                    },
                ),
            )
            saved = self.run_step(
                run_dir,
                blocked_state,
                agent_runner=fake_agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["initial_commits"]["root"], root_sha)
            self.assertEqual(command("rev-parse", "HEAD", cwd=workspace), root_sha)
            self.assertEqual(calls[1]["resume_session_id"], "session-1")

    def test_blocked_decision_rechecks_observed_git_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                commit_all(workspace)
                current = agent_result(cwd=kwargs["cwd"], text="等待外部授权")  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked(messages, config, *, system_prompt):
                command("switch", "-c", "feature", cwd=workspace)
                return decision(
                    "blocked",
                    reason="缺少授权",
                    required_inputs=["授权"],
                )

            with self.assertRaisesRegex(RuntimeError, "最近 Agent 回合记录不一致|分支为 main"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=blocked,
                    config_loader=lambda: object(),
                )

    def test_no_session_commit_and_unsafe_repository_states_fail_before_agent(self) -> None:
        for mutation in ("existing", "wrong-branch", "multiple", "root-path", "root-gitlink", "dirty"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                outputs = ["frontend"] if mutation in {"root-path", "root-gitlink"} else []
                run_dir, workspace, state = self.make_run(Path(directory), outputs)
                if mutation == "existing":
                    commit_all(workspace)
                elif mutation == "wrong-branch":
                    command("switch", "-c", "feature", cwd=workspace)
                else:
                    state["claude_sessions"] = {"initialize_repositories": "session-1"}
                    if mutation == "root-path":
                        child_git = workspace / "frontend/.git"
                        parked_git = workspace.parent / "parked-frontend-git"
                        os.rename(child_git, parked_git)
                        try:
                            command("add", "-f", "frontend/frontend.txt", cwd=workspace)
                            commit_all(workspace)
                        finally:
                            os.rename(parked_git, child_git)
                    else:
                        commit_all(workspace)
                    if mutation == "multiple":
                        (workspace / "extra.txt").write_text("extra", encoding="utf-8")
                        commit_all(workspace, "second")
                    elif mutation == "root-gitlink":
                        commit_all(workspace / "frontend")
                        command("add", "-f", "frontend", cwd=workspace)
                        command(
                            "-c",
                            "user.name=PCM Test",
                            "-c",
                            "user.email=pcm@example.invalid",
                            "commit",
                            "--amend",
                            "--no-edit",
                            cwd=workspace,
                        )
                    elif mutation == "dirty":
                        (workspace / "docs/design/技术方案.md").write_text("changed", encoding="utf-8")
                    write_state(run_dir, state)

                async def unexpected_agent(*args, **kwargs):
                    raise AssertionError("非法 Git 现场不应调用 Agent")

                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state, agent_runner=unexpected_agent)

    def test_existing_session_does_not_adopt_external_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            state["claude_sessions"] = {"initialize_repositories": "session-1"}
            state["initialize_repositories"] = {"observed_heads": {"root": None}}
            write_state(run_dir, state)
            commit_all(workspace)

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("外部提交冲突不应调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "最近 Agent 回合记录不一致"):
                self.run_step(run_dir, state, agent_runner=unexpected_agent)

    def test_shallow_history_cannot_be_initial_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            initialize_root_repository(source)
            (source / "one.txt").write_text("one", encoding="utf-8")
            commit_all(source, "first")
            (source / "two.txt").write_text("two", encoding="utf-8")
            commit_all(source, "second")
            shallow = root / "shallow"
            subprocess.run(
                ["git", "clone", "--depth", "1", source.as_uri(), str(shallow)],
                check=True,
                capture_output=True,
            )

            with self.assertRaisesRegex(RuntimeError, "浅历史"):
                initialize_step._require_single_initial_commit(shallow)

    def test_completion_requires_root_gitignore_not_local_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            names = ["root", "frontend"]

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / ".gitignore").write_text("# 子仓规则已删除\n", encoding="utf-8")
                (workspace / ".git/info/exclude").write_text("frontend/\n", encoding="utf-8")
                commit_all(workspace / "frontend")
                commit_all(workspace)
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text=marker(names, workspace),
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            with self.assertRaisesRegex(RuntimeError, "完成核验失败"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )

    def test_replace_reference_cannot_rewrite_initial_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            repository.mkdir()
            initialize_root_repository(repository)
            (repository / "file.txt").write_text("content", encoding="utf-8")
            head = commit_all(repository)
            tree = command("rev-parse", "HEAD^{tree}", cwd=repository)
            replacement = command(
                "-c",
                "user.name=PCM Test",
                "-c",
                "user.email=pcm@example.invalid",
                "commit-tree",
                tree,
                "-m",
                "replacement",
                cwd=repository,
            )
            command("replace", head, replacement, cwd=repository)

            with self.assertRaisesRegex(RuntimeError, "replace"):
                initialize_step._require_single_initial_commit(repository)

    def test_unignored_coverage_artifact_fails_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            (workspace / ".coverage").write_bytes(b"coverage")

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("未处理覆盖率产物不应调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "覆盖率数据库"):
                self.run_step(run_dir, state, agent_runner=unexpected_agent)

    def test_root_ignore_is_required_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
            (workspace / ".gitignore").unlink()

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("缺少根忽略规则不应调用 Agent")

            with self.assertRaisesRegex(RuntimeError, ".gitignore"):
                self.run_step(run_dir, state, agent_runner=unexpected_agent)

    def test_invalid_marker_set_order_or_sha_repairs_in_same_session(self) -> None:
        for kind in ("set", "order", "sha"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory), ["frontend"])
                names = ["root", "frontend"]
                calls: list[dict] = []

                async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    calls.append({"prompt": prompt, **kwargs})
                    if len(calls) == 1:
                        self.commit_repositories(workspace, names)
                        entries = json.loads(marker(names, workspace).removeprefix(INITIAL_COMMITS_PREFIX))["repositories"]
                        if kind == "set":
                            entries = entries[:1]
                        elif kind == "order":
                            entries = list(reversed(entries))
                        else:
                            entries[0]["sha"] = "0" * 40
                        text = INITIAL_COMMITS_PREFIX + json.dumps({"repositories": entries})
                    else:
                        text = marker(names, workspace)
                    current = agent_result(cwd=kwargs["cwd"], text=text)  # type: ignore[arg-type, index]
                    kwargs["on_update"](current)  # type: ignore[index, operator]
                    return current

                async def completed(messages, config, *, system_prompt):
                    return decision("completed")

                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[1]["prompt"], INITIAL_COMMITS_REPAIR_PROMPT)

    def test_result_write_interruption_advances_on_retry_and_success_reuses_without_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), [])
            calls = 0

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                nonlocal calls
                calls += 1
                commit_all(workspace)
                current = agent_result(cwd=kwargs["cwd"], text=marker(["root"], workspace))  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            original_write_state = initialize_step.write_state

            def interrupt_final_state(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("模拟状态写入中断")
                original_write_state(target, value)

            with patch.object(initialize_step, "write_state", side_effect=interrupt_final_state):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=fake_agent,
                        decision_runner=completed,
                        config_loader=lambda: object(),
                    )
            self.assertTrue((run_dir / "steps/08.json").is_file())
            interrupted = read_state(run_dir)

            async def unexpected(*args, **kwargs):
                raise AssertionError("已有成功结果不应调用 Agent 或决策模型")

            advanced = self.run_step(
                run_dir,
                interrupted,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(advanced["status"], "success")
            saved_state = read_state(run_dir)
            self.assertEqual((saved_state["step"], saved_state["current_node"]), (9, NEXT_NODE))
            reused = self.run_step(
                run_dir,
                saved_state,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(reused, advanced)
            self.assertEqual(calls, 1)

    def test_cli_step_eight_missing_id_corrupt_state_and_blocked_mapping(self) -> None:
        missing = subprocess.run(
            [sys.executable, str(DEMO_ROOT / "run_step.py"), "--step", "8"],
            cwd=DEMO_ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("第 8 步执行失败", missing.stderr)
        self.assertNotIn("Traceback", missing.stderr)

        run_dir = DEMO_ROOT / "runs" / "corrupt-step-eight-test"
        if run_dir.exists():
            self.skipTest("本地 demo runs 已存在 corrupt-step-eight-test")
        try:
            (run_dir / "steps").mkdir(parents=True)
            (run_dir / "state.json").write_text("{invalid", encoding="utf-8")
            corrupt = subprocess.run(
                [sys.executable, str(DEMO_ROOT / "run_step.py"), "--step", "8", "--run-id", run_dir.name],
                cwd=DEMO_ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(corrupt.returncode, 1)
            saved = json.loads((run_dir / "steps/08.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "failed")
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)

        import run_step as cli

        preserved_dir = DEMO_ROOT / "runs" / "preserve-step-eight-success-test"
        if preserved_dir.exists():
            self.skipTest("本地 demo runs 已存在 preserve-step-eight-success-test")
        try:
            (preserved_dir / "steps").mkdir(parents=True)
            write_state(
                preserved_dir,
                {"status": "running", "step": 8, "current_step": 8, "current_node": CURRENT_NODE},
            )
            write_json(
                preserved_dir / "steps/08.json",
                initialize_step.result(
                    "success",
                    "已完成",
                    applicable_repositories=["root"],
                    initial_commits={"root": "a" * 40},
                    repositories=[],
                ),
            )
            args = Namespace(
                step=8,
                product_draft=None,
                workspace_root=None,
                catalog_path=None,
                run_id=preserved_dir.name,
            )
            with (
                patch.object(cli, "parse_args", return_value=args),
                patch.object(cli, "run_step_eight", side_effect=OSError("模拟最终状态写入失败")),
            ):
                self.assertEqual(cli.main(), 1)
            preserved = json.loads((preserved_dir / "steps/08.json").read_text(encoding="utf-8"))
            self.assertEqual(preserved["status"], "success")
        finally:
            if preserved_dir.exists():
                shutil.rmtree(preserved_dir)

        blocked_dir = DEMO_ROOT / "runs" / "blocked-step-eight-test"
        if blocked_dir.exists():
            self.skipTest("本地 demo runs 已存在 blocked-step-eight-test")
        try:
            (blocked_dir / "steps").mkdir(parents=True)
            write_state(blocked_dir, {"status": "running"})

            async def blocked_run(*args, **kwargs):
                raise InitializeRepositoriesBlocked("缺少授权", ["授权"], ["root"])

            args = Namespace(
                step=8,
                product_draft=None,
                workspace_root=None,
                catalog_path=None,
                run_id=blocked_dir.name,
            )
            with (
                patch.object(cli, "parse_args", return_value=args),
                patch.object(cli, "run_step_eight", side_effect=blocked_run),
            ):
                self.assertEqual(cli.main(), 1)
            blocked = json.loads((blocked_dir / "steps/08.json").read_text(encoding="utf-8"))
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(
                blocked["blocked"],
                {"reason": "缺少授权", "required_inputs": ["授权"], "applicable_repositories": ["root"]},
            )
        finally:
            if blocked_dir.exists():
                shutil.rmtree(blocked_dir)


if __name__ == "__main__":
    unittest.main()
