from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.files import write_json
from common.state import read_state, write_requirement_step_result, write_state
from model_policy import get_agent_profile
from steps.step_14_trd_design.step import (
    CURRENT_NODE,
    NEXT_NODE,
    PHASE,
    STEP,
    TRD_DESIGN_DECISION_RULES,
    TRDDesignBlocked,
    failure_scope,
    has_complete_success,
    result,
    run,
)
import steps.step_14_trd_design.step as trd_step


def agent_result(
    workspace: Path,
    *,
    text: str = "已形成活动 TRD。",
    session: str = "trd-session-1",
) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(workspace),
            "skills": ["trd-design"],
            "slash_commands": ["trd-design"],
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
) -> tuple[dict, int, str]:
    value = {
        "verdict": verdict,
        "answer": answer,
        "reason": reason,
        "required_inputs": required_inputs or [],
    }
    return value, 1, json.dumps(value, ensure_ascii=False)


class TRDDesignTests(unittest.TestCase):
    def make_run(
        self,
        root: Path,
        *,
        title: str = "身份、角色访问与站内消息入口",
    ) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps/requirements/BR-001").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        workspace.mkdir(parents=True)
        backlog_path = "docs/backlog/canonical-source.md"
        backlog = workspace / backlog_path
        backlog.parent.mkdir(parents=True)
        backlog.write_text(
            "# 正式 Backlog\n\n"
            "BACKLOG_CONTEXT_MARKER\n\n"
            "- BR-001 身份、角色访问与站内消息入口，依赖：无。\n"
            "- BR-002 维修预约入口，依赖：BR-001。\n",
            encoding="utf-8",
        )
        (workspace / "docs/backlog/backlog.md").write_text(
            "HARDCODED_BACKLOG_PATH_DECOY\n",
            encoding="utf-8",
        )
        state = {
            "status": "running",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "requirement_registry": {
                "schema_version": 1,
                "source": {
                    "path": backlog_path,
                    "sha256": "test-backlog-sha256",
                },
                "requirements": [
                    {
                        "id": "BR-001",
                        "title": title,
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
                "return_node_after_completion": "phase_1:select_requirement",
            },
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    @staticmethod
    def run_step(run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    @staticmethod
    def write_trd(workspace: Path, state: dict, content: str = "# 活动 TRD\n\n实现约束。\n") -> Path:
        target = workspace / state["requirement_cycle"]["trd_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def test_decision_rules_keep_step_completion_contract_concise(self) -> None:
        self.assertIn("没有阻碍实现的未决事项", TRD_DESIGN_DECISION_RULES)
        self.assertIn("稳定业务 owner", TRD_DESIGN_DECISION_RULES)
        self.assertIn("每个受影响交付单元", TRD_DESIGN_DECISION_RULES)
        self.assertIn("边界内部文件粒度可调整", TRD_DESIGN_DECISION_RULES)
        self.assertIn("架构 delta", TRD_DESIGN_DECISION_RULES)
        self.assertIn("没有静默降级", TRD_DESIGN_DECISION_RULES)
        self.assertIn("明确的下一步指令", TRD_DESIGN_DECISION_RULES)
        self.assertNotIn("体验决定已在 TRD 收敛", TRD_DESIGN_DECISION_RULES)
        self.assertNotIn("不得静默偏离", TRD_DESIGN_DECISION_RULES)

    def test_fresh_persists_path_and_gives_lead_full_backlog_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []
            decision_prompts: list[str] = []

            async def agent(prompt: str, **_: object) -> ClaudeRunResult:
                persisted = read_state(run_dir)
                self.assertEqual(
                    persisted["requirement_cycle"]["trd_path"],
                    "docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md",
                )
                prompts.append(prompt)
                self.write_trd(workspace, persisted)
                return agent_result(workspace)

            async def decide(*_: object, **kwargs: object) -> tuple[dict, int, str]:
                decision_prompts.append(str(kwargs["system_prompt"]))
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                today_provider=lambda: date(2026, 8, 25),
            )

            self.assertEqual(len(prompts), 1)
            self.assertTrue(prompts[0].startswith("/trd-design\n"))
            self.assertIn(saved["trd_path"], prompts[0])
            self.assertNotIn("@docs/", prompts[0])
            for required in (
                "任意来源发现已确认的 Target 或有依据的默认 Target",
                "来源、适用范围、经核验的 Current、Target",
                "遵循或改变",
                "依据与重议条件",
                "偏离须说明理由",
                "跨需求骨架须由负责人决定",
                "没有适用决定时不得虚构或阻塞",
                "工程架构资料",
                "每个受影响交付单元",
                "稳定业务 owner",
                "目录/包/模块边界",
                "公开/私有边界",
                "允许/禁止依赖",
                "预期改动归属",
                "边界内部文件名、数量和等价拆分",
                "巨型入口/页面",
                "通用收纳目录",
                "同名平铺文件",
                "架构 delta",
                "最小迁移",
                "不得静默降级",
            ):
                self.assertIn(required, prompts[0])
            self.assertEqual(len(decision_prompts), 1)
            self.assertIn("docs/backlog/canonical-source.md", decision_prompts[0])
            self.assertIn("BACKLOG_CONTEXT_MARKER", decision_prompts[0])
            self.assertIn("BR-002 维修预约入口，依赖：BR-001", decision_prompts[0])
            self.assertNotIn("HARDCODED_BACKLOG_PATH_DECOY", decision_prompts[0])
            self.assertNotIn("BACKLOG_CONTEXT_MARKER", prompts[0])
            self.assertNotIn("实现约束。", decision_prompts[0])
            for required in (
                "范围、关键行为、技术方案、验证场景和需求级体验设计已经收敛",
                "没有阻碍实现的未决事项",
                "每个受影响交付单元",
                "稳定业务 owner",
                "目录/包/模块边界",
                "公开/私有边界",
                "允许/禁止依赖",
                "预期改动归属",
                "边界内部文件粒度可调整",
                "架构 delta",
                "最小迁移",
                "没有静默降级",
            ):
                self.assertIn(required, decision_prompts[0])
            for duplicated in (
                "体验决定已在 TRD 收敛",
                "默认 Target 已说明依据与重议条件",
                "不得静默偏离",
                "跨需求骨架改变已有负责人决定",
            ):
                self.assertNotIn(duplicated, decision_prompts[0])
            for content in (prompts[0], decision_prompts[0]):
                for forbidden in (
                    "第 14 步",
                    "PCM",
                    "session",
                    "@./docs/",
                    "docs/design/工程架构设计.md",
                    "docs/ui-ux/framework.md",
                    "ui-ux-framework",
                    "React",
                    "Tailwind",
                    "shadcn",
                ):
                    self.assertNotIn(forbidden, content)
            self.assertFalse((run_dir / "steps/02.json").exists())
            self.assertFalse((run_dir / "steps/13.json").exists())
            self.assertEqual(saved["trd_session_id"], "trd-session-1")
            self.assertEqual(saved["outputs"], [saved["trd_path"]])
            completed = read_state(run_dir)
            self.assertEqual(
                (completed["step"], completed["current_step"], completed["current_node"]),
                (15, 15, NEXT_NODE),
            )
            self.assertTrue(has_complete_success(run_dir, completed))

    def test_continue_reuses_public_loop_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls: list[tuple[object, object, object, object]] = []
            decisions = iter(
                [
                    decision("continue", answer="请补全验证场景。"),
                    decision("completed"),
                ]
            )

            async def agent(_prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append(
                    (
                        kwargs.get("resume_session_id"),
                        kwargs.get("task"),
                        kwargs.get("model"),
                        kwargs.get("effort"),
                    )
                )
                if len(calls) == 2:
                    self.write_trd(workspace, read_state(run_dir))
                return agent_result(workspace, text=f"第 {len(calls)} 轮结果。")

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return next(decisions)

            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                today_provider=lambda: date(2026, 8, 25),
            )
            profile = get_agent_profile("trd_design")
            self.assertEqual(
                calls,
                [
                    (None, "trd_design", profile.model, profile.effort),
                    ("trd-session-1", "trd_design", profile.model, profile.effort),
                ],
            )

    def test_completed_missing_document_repairs_in_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            prompts: list[str] = []
            resumes: list[str | None] = []

            async def agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                prompts.append(prompt)
                resumes.append(kwargs.get("resume_session_id"))
                if len(prompts) == 2:
                    self.write_trd(workspace, read_state(run_dir))
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            self.run_step(
                run_dir,
                state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                today_provider=lambda: date(2026, 8, 25),
            )
            self.assertEqual(len(prompts), 2)
            self.assertIn("缺失或为空", prompts[1])
            self.assertEqual(resumes, [None, "trd-session-1"])
            self.assertNotIn("/commit-changes", "\n".join(prompts))

    def test_blocked_preserves_scoped_result_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision(
                    "blocked",
                    reason="缺少外部授权",
                    required_inputs=["外部授权"],
                )

            with self.assertRaises(TRDDesignBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=agent,
                    decision_runner=decide,
                    config_loader=lambda: object(),
                    today_provider=lambda: date(2026, 8, 25),
                )
            saved = json.loads(
                (run_dir / "steps/requirements/BR-001/14.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["status"], "blocked")
            self.assertEqual(saved["trd_session_id"], "trd-session-1")
            blocked = read_state(run_dir)
            self.assertEqual((blocked["status"], blocked["current_node"]), ("blocked", CURRENT_NODE))

    def test_recovery_reuses_first_path_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def interrupted(*_: object, **__: object) -> ClaudeRunResult:
                raise RuntimeError("simulated interruption")

            with self.assertRaises(RuntimeError):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=interrupted,
                    config_loader=lambda: object(),
                    today_provider=lambda: date(2026, 8, 25),
                )
            interrupted_state = read_state(run_dir)
            first_path = interrupted_state["requirement_cycle"]["trd_path"]

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                self.write_trd(workspace, read_state(run_dir))
                return agent_result(workspace, session="trd-session-2")

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            saved = self.run_step(
                run_dir,
                interrupted_state,
                agent_runner=agent,
                decision_runner=decide,
                config_loader=lambda: object(),
                today_provider=lambda: date(2026, 8, 26),
            )
            self.assertEqual(saved["trd_path"], first_path)
            self.assertIn("2026-08-25", saved["trd_path"])

    def test_decision_failure_recovery_reuses_agent_reply_and_clears_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            trd_path = (
                "docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md"
            )
            key = "trd_design_BR-001"
            state["status"] = "failed"
            state["requirement_cycle"]["trd_path"] = trd_path
            state["claude_sessions"] = {key: "trd-session-1"}
            state["decision_conversations"] = {
                key: {"path": f"conversations/{key}.json"}
            }
            state[key] = {
                "last_agent_result": {
                    "subtype": "success",
                    "is_error": False,
                    "has_errors": False,
                    "api_error_status": None,
                    "exception_type": None,
                    "terminal_reason": "completed",
                },
                "last_decision_failure": {"kind": "transport"},
            }
            write_state(run_dir, state)
            self.write_trd(workspace, state)
            (run_dir / "conversations").mkdir()
            write_json(
                run_dir / f"conversations/{key}.json",
                {
                    "messages": [
                        {"role": "system", "content": "历史 system prompt"},
                        {"role": "assistant", "content": "初始 Agent 提示"},
                        {"role": "user", "content": "已完成并写入活动 TRD。"},
                    ]
                },
            )

            async def forbidden_agent(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("不应再次调用 Agent")

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=forbidden_agent,
                decision_runner=decide,
                config_loader=lambda: object(),
            )

            self.assertEqual(saved["status"], "success")
            completed = read_state(run_dir)
            self.assertEqual(completed["current_node"], NEXT_NODE)
            self.assertNotIn("last_decision_failure", completed[key])
            messages = json.loads(
                (run_dir / f"conversations/{key}.json").read_text(encoding="utf-8")
            )["messages"]
            self.assertEqual(messages[-1]["role"], "assistant")

    def test_success_result_recovers_state_and_advanced_rerun_skips_file_and_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def agent(*_: object, **__: object) -> ClaudeRunResult:
                self.write_trd(workspace, read_state(run_dir))
                return agent_result(workspace)

            async def decide(*_: object, **__: object) -> tuple[dict, int, str]:
                return decision("completed")

            original_write_state = trd_step.write_state

            def interrupt_advance(path: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("simulated state interruption")
                original_write_state(path, value)

            with patch.object(trd_step, "write_state", side_effect=interrupt_advance):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=agent,
                        decision_runner=decide,
                        config_loader=lambda: object(),
                        today_provider=lambda: date(2026, 8, 25),
                    )

            interrupted = read_state(run_dir)
            saved = json.loads(
                (run_dir / "steps/requirements/BR-001/14.json").read_text(encoding="utf-8")
            )

            async def forbidden(*_: object, **__: object) -> ClaudeRunResult:
                raise AssertionError("不应再次调用 Agent")

            recovered = self.run_step(run_dir, interrupted, agent_runner=forbidden)
            self.assertEqual(recovered, saved)
            advanced = read_state(run_dir)
            (workspace / saved["trd_path"]).unlink()
            self.assertEqual(self.run_step(run_dir, advanced, agent_runner=forbidden), saved)

    def test_invalid_title_fails_before_path_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory), title="登录/注册")
            before = (run_dir / "state.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "文件名"):
                self.run_step(run_dir, state, today_provider=lambda: date(2026, 8, 25))
            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            self.assertNotIn("trd_path", read_state(run_dir)["requirement_cycle"])

    def test_failure_scope_uses_persisted_path_and_step_never_imports_git_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            self.assertIsNone(failure_scope(run_dir, state))
            state["requirement_cycle"]["trd_path"] = (
                "docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md"
            )
            write_state(run_dir, state)
            scope = failure_scope(run_dir, state)
            self.assertEqual(scope["requirement_id"], "BR-001")
            self.assertEqual(scope["branch"], "req/br-001")
            self.assertEqual(scope["trd_path"], state["requirement_cycle"]["trd_path"])
            self.assertNotIn("subprocess", vars(trd_step))
            self.assertNotIn("os", vars(trd_step))


if __name__ == "__main__":
    unittest.main()
