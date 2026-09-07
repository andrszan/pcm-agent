from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.agent_decision_loop import BLOCKED_RESUME_PROMPT
from common.claude_agent import ClaudeRunResult
from common.state import read_state, write_requirement_step_result, write_state
from model_policy import get_agent_profile
from steps.step_17_commit.step import (
    COMMIT_MAX_TURNS,
    CURRENT_NODE,
    MAX_DECISION_ROUNDS,
    NEXT_NODE,
    PHASE,
    REPOSITORY_REPAIR_PROMPT,
    STEP,
    RequirementCommitBlocked,
    result,
    run,
)


def command(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


def commit_all(repository: Path, message: str = "test commit") -> str:
    command("add", "-A", cwd=repository)
    command(
        "-c", "user.name=PCM Test", "-c", "user.email=pcm@example.invalid",
        "commit", "-m", message, cwd=repository,
    )
    return command("rev-parse", "HEAD", cwd=repository)


def agent_result(
    cwd: Path,
    session: str = "development-session-1",
    text: str = "已处理当前提交任务。",
) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": ["commit-changes"],
            "slash_commands": ["commit-changes"],
        },
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
    reason: str = "已核验",
    required_inputs: list[str] | None = None,
) -> tuple[dict[str, Any], int, str]:
    data = {
        "verdict": verdict,
        "answer": answer,
        "reason": reason,
        "required_inputs": required_inputs or [],
    }
    return data, 1, json.dumps(data, ensure_ascii=False)


class RequirementCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.case_number = 0

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_run(
        self, children: list[str] | None = None
    ) -> tuple[Path, Path, dict[str, Any], dict[str, str]]:
        children = children or []
        self.case_number += 1
        case_root = self.root / f"case-{self.case_number}"
        run_dir = case_root / "run"
        (run_dir / "steps/requirements/BR-001").mkdir(parents=True)
        workspace_root = case_root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)
        repositories = [("root", workspace), *[(name, workspace / name) for name in children]]
        for _name, repository in repositories[1:]:
            repository.mkdir()
        bases: dict[str, str] = {}
        for name, repository in repositories:
            command("init", "-b", "main", cwd=repository)
            (repository / "base.txt").write_text(f"{name} base\n", encoding="utf-8")
            bases[name] = commit_all(repository, "base")
            command("switch", "-c", "req/br-001", cwd=repository)
        if children:
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as file:
                for name in children:
                    file.write(f"{name}/\n")
        names = [name for name, _repository in repositories]
        state: dict[str, Any] = {
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "applicable_repositories": names,
            "repositories": [
                {"name": name, "path": str(repository)} for name, repository in repositories
            ],
            "requirement_registry": {
                "schema_version": 1,
                "requirements": [{
                    "id": "BR-001", "title": "账户访问", "order": 1,
                    "depends_on": [], "status": "active", "completion": None,
                }],
            },
            "active_requirement": "BR-001",
            "claude_sessions": {
                "development_BR-001": "development-session-1",
                "rule_retrospective_BR-001": "development-session-1",
            },
            "requirement_cycle": {
                "requirement_id": "BR-001",
                "branch": "req/br-001",
                "repositories": {name: {"base_sha": bases[name]} for name in names},
                "trd_path": "docs/trd/BR-001.md",
                "development_session_id": "development-session-1",
                "return_node_after_completion": "phase_1:select_requirement",
            },
            "blocked": None,
            "error": None,
        }
        write_requirement_step_result(run_dir, "BR-001", 16, {
            "step": 16, "name": "规则复盘", "status": "success", "summary": "已完成。",
            "applicable": True, "outputs": [], "blocked": None, "error": None,
            "requirement_id": "BR-001", "development_session_id": "development-session-1",
        })
        write_state(run_dir, state)
        return run_dir, workspace, state, bases

    @staticmethod
    def dirty(workspace: Path, names: list[str]) -> None:
        for name in names:
            repository = workspace if name == "root" else workspace / name
            (repository / f"{name}-change.txt").write_text("changed\n", encoding="utf-8")

    @staticmethod
    def commit_names(workspace: Path, names: list[str]) -> None:
        for name in names:
            repository = workspace if name == "root" else workspace / name
            commit_all(repository, f"feat: {name}")

    @staticmethod
    def execute(run_dir: Path, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return asyncio.run(run(run_dir, state, **kwargs))

    @staticmethod
    def success(bases: dict[str, str], tips: dict[str, str]) -> dict[str, Any]:
        return result(
            "success", "已完成。", requirement_id="BR-001", branch="req/br-001",
            repositories=[{
                "name": name, "path": "." if name == "root" else name,
                "base_sha": bases[name], "tip_sha": tips[name],
            } for name in bases],
        )

    def test_all_clean_skips_agent_decision_and_conversation(self) -> None:
        run_dir, _workspace, state, bases = self.make_run(["web"])

        async def unexpected(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("全 clean 不应调用 Agent 或负责人")

        saved = self.execute(
            run_dir, state, agent_runner=unexpected, decision_runner=unexpected,
            config_loader=lambda: object(),
        )
        self.assertEqual([item["tip_sha"] for item in saved["repositories"]], list(bases.values()))
        completed = read_state(run_dir)
        self.assertEqual(completed["current_node"], NEXT_NODE)
        self.assertNotIn("requirement_commit_BR-001", completed["claude_sessions"])
        self.assertFalse((run_dir / "conversations/requirement_commit_BR-001.json").exists())

    def test_dirty_completed_creates_full_conversation(self) -> None:
        run_dir, workspace, state, _bases = self.make_run(["web", "api"])
        names = ["root", "web", "api"]
        self.dirty(workspace, names)
        calls: list[dict[str, Any]] = []
        decision_prompts: list[str] = []

        async def agent(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            self.commit_names(workspace, names)
            value = agent_result(kwargs["cwd"])
            kwargs["on_update"](value)
            return value

        async def completed(messages, config, *, system_prompt):
            decision_prompts.append(system_prompt)
            return decision("completed")

        self.execute(
            run_dir, state, agent_runner=agent, decision_runner=completed,
            config_loader=lambda: object(),
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["max_turns"], COMMIT_MAX_TURNS)
        profile = get_agent_profile("requirement_commit")
        self.assertEqual(calls[0]["task"], "requirement_commit")
        self.assertEqual(
            (calls[0]["model"], calls[0]["effort"]),
            (profile.model, profile.effort),
        )
        self.assertNotIn("max_budget_usd", calls[0])
        self.assertEqual(
            calls[0]["prompt"],
            "/commit-changes\n"
            "请提交当前需求 `BR-001 账户访问` 在以下仓库中的全部已有变更：\n"
            "- root: `.`\n"
            "- web: `web`\n"
            "- api: `api`\n\n"
            "统一需求分支：`req/br-001`\n"
            "只 commit，不 push。",
        )
        self.assertEqual(calls[0]["resume_session_id"], "development-session-1")
        self.assertEqual(MAX_DECISION_ROUNDS, 32)
        self.assertEqual(len(decision_prompts), 1)
        for required in (
            "全部白名单仓库仍在统一需求分支",
            "仅当仍有读取 Git 状态",
            "现有变更无法原样安全提交",
            "只处理 Git 提交",
            "不 push",
        ):
            self.assertIn(required, decision_prompts[0])
        for forbidden in (
            "第 15 步",
            "第 16 步",
            "第 17 步",
            "本步骤",
            "上游开发步骤",
            "PCM",
            "current_node",
            "session",
            "不得运行 lint",
            "不得创建或修改 .gitignore",
            "浏览器验收",
            "安全审查",
        ):
            self.assertNotIn(forbidden, calls[0]["prompt"])
            self.assertNotIn(forbidden, decision_prompts[0])
        saved_state = read_state(run_dir)
        key = "requirement_commit_BR-001"
        self.assertEqual(saved_state["claude_sessions"][key], "development-session-1")
        self.assertEqual(
            saved_state["decision_conversations"][key]["path"],
            "conversations/requirement_commit_BR-001.json",
        )
        conversation = json.loads(
            (run_dir / "conversations/requirement_commit_BR-001.json").read_text(encoding="utf-8")
        )
        self.assertEqual([message["role"] for message in conversation["messages"]], [
            "system", "assistant", "user", "assistant",
        ])

    def test_failure_retries_with_development_session(self) -> None:
        run_dir, workspace, state, _bases = self.make_run()
        self.dirty(workspace, ["root"])

        async def interrupted(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            raise ConnectionError("temporary disconnect")

        with self.assertRaisesRegex(RuntimeError, "Agent SDK 执行异常"):
            self.execute(
                run_dir, state, agent_runner=interrupted,
                decision_runner=lambda *args, **kwargs: None,
                config_loader=lambda: object(),
            )
        failed_state = read_state(run_dir)
        key = "requirement_commit_BR-001"
        self.assertEqual(
            failed_state["claude_sessions"][key], "development-session-1"
        )
        self.assertEqual(
            failed_state["decision_conversations"][key]["path"],
            "conversations/requirement_commit_BR-001.json",
        )
        calls: list[dict[str, Any]] = []

        async def recovered(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            self.commit_names(workspace, ["root"])
            value = agent_result(kwargs["cwd"])
            kwargs["on_update"](value)
            return value

        async def completed(messages, config, *, system_prompt):
            return decision("completed")

        self.execute(
            run_dir, failed_state, agent_runner=recovered,
            decision_runner=completed, config_loader=lambda: object(),
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["resume_session_id"], "development-session-1"
        )
        self.assertTrue(calls[0]["prompt"].startswith("/commit-changes\n"))

    def test_continue_then_completed_reuses_session(self) -> None:
        run_dir, workspace, state, _bases = self.make_run()
        self.dirty(workspace, ["root"])
        calls: list[dict[str, Any]] = []
        git_continue = (
            "不要修改文件内容；只重新读取白名单仓库的 Git 状态和剩余 diff，"
            "精确暂存并提交现有定稿变更，然后核验提交后状态。"
        )
        decisions = [
            decision("continue", answer=git_continue),
            decision("completed"),
        ]
        decision_calls = 0

        async def agent(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            if len(calls) > 2:
                raise AssertionError("continue 场景不应调用第三轮 Agent")
            if len(calls) == 2:
                self.commit_names(workspace, ["root"])
            value = agent_result(kwargs["cwd"], text=f"continue 第 {len(calls)} 轮")
            kwargs["on_update"](value)
            return value

        async def decide(messages, config, *, system_prompt):
            nonlocal decision_calls
            decision_calls += 1
            if decision_calls > len(decisions):
                raise AssertionError("continue 场景不应请求第三次决策")
            return decisions[decision_calls - 1]

        self.execute(
            run_dir, state, agent_runner=agent, decision_runner=decide,
            config_loader=lambda: object(),
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["resume_session_id"], "development-session-1")
        self.assertEqual(calls[1]["prompt"], git_continue)
        self.assertEqual(sum(call["prompt"].count("/commit-changes") for call in calls), 1)

    def test_completed_dirty_repairs_same_session(self) -> None:
        run_dir, workspace, state, _bases = self.make_run()
        self.dirty(workspace, ["root"])
        calls: list[dict[str, Any]] = []

        async def agent(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            if len(calls) == 2:
                self.commit_names(workspace, ["root"])
            value = agent_result(kwargs["cwd"], text=f"repair 第 {len(calls)} 轮")
            kwargs["on_update"](value)
            return value

        async def completed(messages, config, *, system_prompt):
            return decision("completed")

        self.execute(
            run_dir, state, agent_runner=agent, decision_runner=completed,
            config_loader=lambda: object(),
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["prompt"], REPOSITORY_REPAIR_PROMPT)
        self.assertEqual(calls[1]["resume_session_id"], "development-session-1")
        for required in (
            "使用 commit-changes",
            "提交这些已有变更",
            "只 commit，不 push",
        ):
            self.assertIn(required, calls[1]["prompt"])

    def test_decision_round_limit_stops_before_fourth_agent_call(self) -> None:
        run_dir, workspace, state, _bases = self.make_run()
        self.dirty(workspace, ["root"])
        calls: list[dict[str, Any]] = []
        decision_calls = 0
        git_continue = "只读取 Git 状态和 diff，精确暂存并提交现有变更。"

        async def agent(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            value = agent_result(kwargs["cwd"], text=f"第 {len(calls)} 轮仍有未提交内容")
            kwargs["on_update"](value)
            return value

        async def decide(messages, config, *, system_prompt):
            nonlocal decision_calls
            decision_calls += 1
            return decision("continue", answer=git_continue)

        with self.assertRaisesRegex(RuntimeError, "达到上限"):
            self.execute(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )

        self.assertEqual(len(calls), MAX_DECISION_ROUNDS)
        self.assertEqual(decision_calls, MAX_DECISION_ROUNDS)

    def test_blocked_then_resume_same_conversation(self) -> None:
        run_dir, workspace, state, _bases = self.make_run()
        self.dirty(workspace, ["root"])

        async def first_agent(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            value = agent_result(kwargs["cwd"], text="blocked 第一轮")
            kwargs["on_update"](value)
            return value

        async def blocked(messages, config, *, system_prompt):
            return decision(
                "blocked", reason="缺少签名凭据", required_inputs=["Git 签名凭据"]
            )

        with self.assertRaises(RequirementCommitBlocked):
            self.execute(
                run_dir, state, agent_runner=first_agent, decision_runner=blocked,
                config_loader=lambda: object(),
            )
        blocked_state = read_state(run_dir)
        self.assertEqual(blocked_state["status"], "blocked")
        self.assertEqual(
            json.loads((run_dir / "steps/requirements/BR-001/17.json").read_text())["status"],
            "blocked",
        )
        calls: list[dict[str, Any]] = []

        async def resumed_agent(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            calls.append({"prompt": prompt, **kwargs})
            self.commit_names(workspace, ["root"])
            value = agent_result(kwargs["cwd"], text="blocked 恢复轮")
            kwargs["on_update"](value)
            return value

        async def completed(messages, config, *, system_prompt):
            return decision("completed")

        self.execute(
            run_dir, blocked_state, agent_runner=resumed_agent,
            decision_runner=completed, config_loader=lambda: object(),
        )
        self.assertEqual(calls[0]["prompt"], BLOCKED_RESUME_PROMPT)
        self.assertEqual(calls[0]["resume_session_id"], "development-session-1")

    def test_incomplete_resume_anchors_are_rejected(self) -> None:
        variants = ("session", "reference", "conversation")
        for variant in variants:
            with self.subTest(variant=variant):
                run_dir, workspace, state, _bases = self.make_run()
                self.dirty(workspace, ["root"])
                key = "requirement_commit_BR-001"
                if variant == "session":
                    state["claude_sessions"][key] = "commit-session-1"
                elif variant == "reference":
                    state["decision_conversations"] = {
                        key: {"path": f"conversations/{key}.json"}
                    }
                else:
                    path = run_dir / f"conversations/{key}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("{}", encoding="utf-8")
                write_state(run_dir, state)

                async def unexpected(*args: Any, **kwargs: Any) -> Any:
                    raise AssertionError("残缺锚点不应调用 Agent 或负责人")

                with self.assertRaisesRegex(RuntimeError, "恢复缺少|没有复用"):
                    self.execute(
                        run_dir, state, agent_runner=unexpected,
                        decision_runner=unexpected, config_loader=lambda: object(),
                    )

    def test_untracked_and_symlink_boundaries(self) -> None:
        run_dir, workspace, state, _bases = self.make_run()
        command("config", "status.showUntrackedFiles", "no", cwd=workspace)
        self.dirty(workspace, ["root"])
        calls = 0

        async def agent(prompt: str, **kwargs: Any) -> ClaudeRunResult:
            nonlocal calls
            calls += 1
            self.commit_names(workspace, ["root"])
            value = agent_result(kwargs["cwd"])
            kwargs["on_update"](value)
            return value

        async def completed(messages, config, *, system_prompt):
            return decision("completed")

        self.execute(
            run_dir, state, agent_runner=agent, decision_runner=completed,
            config_loader=lambda: object(),
        )
        self.assertEqual(calls, 1)

        run_dir, workspace, state, _bases = self.make_run(["web"])
        external = self.root / "outside-web"
        (workspace / "web").rename(external)
        (workspace / "web").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "适用仓库描述"):
            self.execute(
                run_dir, state, agent_runner=agent, decision_runner=completed,
                config_loader=lambda: object(),
            )

    def test_result_recovery_and_advanced_compatibility(self) -> None:
        run_dir, workspace, state, bases = self.make_run()
        self.dirty(workspace, ["root"])
        tip = commit_all(workspace, "feat: account access")
        saved = self.success(bases, {"root": tip})
        write_requirement_step_result(run_dir, "BR-001", STEP, saved)
        write_state(run_dir, state)

        async def unexpected(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("恢复路径不应调用 Agent 或负责人")

        self.assertEqual(self.execute(
            run_dir, read_state(run_dir), agent_runner=unexpected,
            decision_runner=unexpected, config_loader=lambda: object(),
        ), saved)
        advanced = read_state(run_dir)
        advanced["requirement_commit_BR-001"] = {"repositories": [{"tree_sha256": "a" * 64}]}
        advanced["decision_conversations"] = {
            "requirement_commit_BR-001": {"path": "conversations/old.json"}
        }
        write_state(run_dir, advanced)
        before = (run_dir / "state.json").read_bytes()
        workspace.rename(workspace.with_name("workspace-moved"))
        self.assertEqual(self.execute(
            run_dir, read_state(run_dir), agent_runner=unexpected,
            decision_runner=unexpected, config_loader=lambda: object(),
        ), saved)
        self.assertEqual((run_dir / "state.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
