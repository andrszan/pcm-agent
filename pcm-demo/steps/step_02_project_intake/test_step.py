from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.decision import AgentDecision
from common.files import sha256, write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_02_project_intake.step import (
    OUTPUTS,
    PROJECT_INTAKE_DECISION_SYSTEM_PROMPT,
    ProjectIntakeBlocked,
    initial_prompt,
    run,
)


def agent_result(*, cwd: Path, session: str = "session-1", text: str = "需要确认") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": ["project-intake"],
            "slash_commands": ["project-intake"],
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
) -> AgentDecision:
    return AgentDecision(
        verdict=verdict,
        answer=answer,
        reason=reason,
        required_inputs=required_inputs or [],
    )


class ProjectIntakeTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        (run_dir / "logs").mkdir()
        workspace = root / "workspace"
        (workspace / ".claude").mkdir(parents=True)
        (workspace / "docs").mkdir()
        draft = root / "draft.md"
        draft.write_text("# 产品初稿\n", encoding="utf-8")
        (workspace / "docs/产品初稿.md").write_bytes(draft.read_bytes())
        write_json(
            run_dir / "steps/01.json",
            {
                "step": 1,
                "name": "建立项目工作区",
                "status": "success",
                "summary": "完成",
                "applicable": True,
                "outputs": ["docs/产品初稿.md"],
                "blocked": None,
                "error": None,
            },
        )
        (workspace / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        (workspace / "AGENTS.md").write_text("规则\n", encoding="utf-8")
        (workspace / ".claude/settings.json").write_text("{}\n", encoding="utf-8")
        root_repository = initialize_root_repository(workspace)
        state = {
            "run_id": "test",
            "status": "success",
            "current_step": 1,
            "publication_phase": "git_initialized",
            "root_repository": root_repository,
            "workspace": {
                "root": str(root),
                "staging_path": str(root / "staging-unused"),
                "final_path": str(workspace),
            },
            "checks": {
                "template_capabilities_present": True,
                "upstream_git_removed": True,
                "docs_reinitialized": True,
                "draft_hash_matches": True,
                "source_draft_unchanged": True,
                "renamed_to_final_path": True,
                "root_git_initialized": True,
                "root_git_is_final_path": True,
                "root_git_has_no_commits": True,
            },
            "input": {
                "source_path": str(draft),
                "source_sha256": sha256(draft),
                "published_path": str(workspace / "docs/产品初稿.md"),
            },
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    def write_outputs(self, workspace: Path) -> None:
        for relative in OUTPUTS:
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# 完成\n", encoding="utf-8")

    def test_initial_prompt_describes_only_authority_outputs_and_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, workspace, _ = self.make_run(Path(directory))
            prompt = initial_prompt(workspace / "docs/产品初稿.md", workspace)

        self.assertEqual(prompt.splitlines()[0], "/project-intake @./docs/产品初稿.md")
        self.assertIn("产品初稿为当前产品定义的权威输入", prompt)
        for output in OUTPUTS:
            self.assertIn(output.as_posix(), prompt)
        self.assertIn("只处理产品定义文档", prompt)
        for forbidden in ("第 2 步", "第2步", "PCM", "节点", "阶段", "调用 Skill"):
            self.assertNotIn(forbidden, prompt)
            self.assertNotIn(forbidden, PROJECT_INTAKE_DECISION_SYSTEM_PROMPT)

    def test_completed_then_repair_then_completed_uses_same_session_and_raw_reply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[dict[str, object]] = []
            decision_inputs: list[list[dict[str, str]]] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    self.write_outputs(workspace)
                current = agent_result(
                    cwd=workspace,
                    text=f"完整 Agent 原文 {len(calls)}",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            outcomes = iter(
                [
                    decision("completed", reason="文档已经完成"),
                    decision("completed", reason="修复后的文档已完成"),
                ]
            )

            async def fake_decision(
                messages: list[dict[str, str]],
                config: object,
                *,
                system_prompt: str,
            ) -> tuple[dict[str, object], int, str]:
                self.assertEqual(system_prompt, PROJECT_INTAKE_DECISION_SYSTEM_PROMPT)
                decision_inputs.append(copy.deepcopy(messages))
                current = next(outcomes)
                return current.model_dump(), 1, current.model_dump_json()

            with patch("steps.step_02_project_intake.step.trust_project"):
                outcome = asyncio.run(
                    run(
                        run_dir,
                        state,
                        agent_runner=fake_agent,
                        decision_runner=fake_decision,
                        config_loader=lambda: object(),
                    )
                )

            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertTrue(str(calls[0]["prompt"]).startswith("/project-intake"))
            self.assertEqual(calls[1]["resume_session_id"], "session-1")
            self.assertIn("请生成或补全两份非空正式产品定义文档", str(calls[1]["prompt"]))
            self.assertEqual(decision_inputs[0][-1], {"role": "user", "content": "完整 Agent 原文 1"})
            saved = read_state(run_dir)
            self.assertEqual((saved["status"], saved["current_step"]), ("success", 2))
            self.assertNotIn("pending_agent_prompt", saved["project_intake"])
            history = json.loads(
                (run_dir / "conversations/project_intake.json").read_text(encoding="utf-8")
            )["messages"]
            self.assertEqual(history[2], {"role": "user", "content": "完整 Agent 原文 1"})
            self.assertEqual(json.loads(history[3]["content"])["verdict"], "completed")
            self.assertIn("请生成或补全两份非空正式产品定义文档", history[4]["content"])
            self.assertEqual(history[-2], {"role": "user", "content": "完整 Agent 原文 2"})
            self.assertEqual(json.loads(history[-1]["content"])["verdict"], "completed")

    def test_blocked_decision_maps_to_existing_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=workspace, text="需要一个外部账号")
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def fake_decision(messages, config, *, system_prompt):
                current = decision(
                    "blocked",
                    reason="环境没有外部账号",
                    required_inputs=["提供外部账号"],
                )
                return current.model_dump(), 1, current.model_dump_json()

            with patch("steps.step_02_project_intake.step.trust_project"):
                with self.assertRaises(ProjectIntakeBlocked) as raised:
                    asyncio.run(
                        run(
                            run_dir,
                            state,
                            agent_runner=fake_agent,
                            decision_runner=fake_decision,
                            config_loader=lambda: object(),
                        )
                    )

            self.assertEqual(str(raised.exception), "环境没有外部账号")
            self.assertEqual(raised.exception.required_inputs, ["提供外部账号"])

    def test_existing_success_reuses_domain_facts_without_agent_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            self.write_outputs(workspace)
            write_json(
                run_dir / "steps/02.json",
                {
                    "step": 2,
                    "name": "项目需求与产品定义",
                    "status": "success",
                    "summary": "已完成。",
                    "applicable": True,
                    "outputs": [path.as_posix() for path in OUTPUTS],
                    "blocked": None,
                    "error": None,
                },
            )
            state.update({"status": "success", "current_step": 2})
            write_state(run_dir, state)

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("已有成功不应再次调用 Agent")

            outcome = asyncio.run(run(run_dir, state, agent_runner=unexpected_agent))

        self.assertEqual(outcome["status"], "success")
        self.assertEqual(outcome["outputs"], [path.as_posix() for path in OUTPUTS])

    def test_legacy_completion_record_remains_read_only_compatible(self) -> None:
        legacy_completion = "已完成 project-intake：两份正式产品定义文档已生成并通过文件事实核验。"
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            self.write_outputs(workspace)
            state.update(
                {
                    "current_step": 2,
                    "status": "running",
                    "decision_conversations": {
                        "project_intake": {
                            "path": "conversations/project_intake.json",
                            "turn": 1,
                        }
                    },
                }
            )
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / "conversations/project_intake.json",
                {
                    "messages": [
                        {"role": "system", "content": PROJECT_INTAKE_DECISION_SYSTEM_PROMPT},
                        {"role": "assistant", "content": "历史初始指令"},
                        {"role": "user", "content": "历史 Agent 原文"},
                        {"role": "assistant", "content": legacy_completion},
                    ]
                },
            )
            write_state(run_dir, state)

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("兼容历史完成记录不应调用 Agent")

            with patch("steps.step_02_project_intake.step.trust_project"):
                outcome = asyncio.run(run(run_dir, state, agent_runner=unexpected_agent))

        self.assertEqual(outcome["status"], "success")

    def test_invalid_source_input_fails_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "docs/产品初稿.md").write_text("changed", encoding="utf-8")

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("输入核验失败不应调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "初稿.*不一致"):
                asyncio.run(run(run_dir, state, agent_runner=unexpected_agent))


if __name__ == "__main__":
    unittest.main()
