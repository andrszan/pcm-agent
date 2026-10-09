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
from common.decision import AgentDecision, render_decision_system_prompt
from common.files import sha256, write_json
from common.frontend_scope import LegacyFrontendContractError, PROTOTYPE_ENTRY
from common.agent_decision_loop import BLOCKED_RESUME_PROMPT, ResumeMessage, prepare_resume_message
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_02_project_intake.step import (
    DECISION_LOOP_SPEC,
    OUTPUTS,
    PROJECT_INTAKE_DECISION_RULES,
    ProjectIntakeBlocked,
    PROTOTYPE_LOOP_SPEC,
    prototype_prompt,
    output_contents,
    validate_existing_contract,
    result,
    completion_repair_prompt,
    initial_prompt,
    run,
)


def agent_result(*, cwd: Path, session: str = "session-1", text: str = "需要确认") -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(cwd),
            "skills": ["project-intake", "frontend-ui-ux"],
            "slash_commands": ["project-intake", "frontend-ui-ux"],
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
    def setUp(self) -> None:
        classification = patch(
            "steps.step_02_project_intake.step.classify_frontend_scope",
            return_value={"applicable": False, "reason": "纯服务端产品"},
        )
        self.classification = classification.start()
        self.addCleanup(classification.stop)
        capabilities = patch("steps.step_02_project_intake.step.ensure_frontend_capabilities")
        self.capabilities = capabilities.start()
        self.addCleanup(capabilities.stop)
        trust = patch("steps.step_02_project_intake.step.trust_project")
        trust.start()
        self.addCleanup(trust.stop)

    def make_run(self, root: Path) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        (run_dir / "logs").mkdir()
        workspace = root / "workspace"
        (workspace / ".claude").mkdir(parents=True)
        (workspace / "docs").mkdir()
        draft = root / "draft.md"
        draft.write_text(
            "# 产品初稿\n"
            "这是用于生成正式产品定义的权威初稿内容。\n"
            "目标用户需要清晰的产品范围和功能说明。\n",
            encoding="utf-8",
        )
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

    def test_initial_prompt_passes_slash_command_and_document_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, workspace, _ = self.make_run(Path(directory))
            prompt = initial_prompt(workspace / "docs/产品初稿.md", workspace)

        self.assertEqual(prompt.splitlines()[0], "/project-intake @./docs/产品初稿.md")
        for output in OUTPUTS:
            self.assertIn(output.as_posix(), prompt)

    def test_initial_prompt_includes_explicit_imported_resources_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, workspace, _ = self.make_run(Path(directory))
            resources = workspace / "initial-resources/客户样本"
            resources.mkdir(parents=True)
            prompt = initial_prompt(
                workspace / "docs/产品初稿.md",
                workspace,
                "initial-resources/客户样本",
            )

        self.assertEqual(
            prompt.splitlines()[0],
            "/project-intake @./docs/产品初稿.md",
        )
        self.assertIn("`./initial-resources/客户样本`", prompt)
        self.assertNotIn("@./initial-resources/", prompt)
        file_prompt = initial_prompt(
            workspace / "docs/产品初稿.md", workspace, "initial-resources/客户样本.csv"
        )
        self.assertIn("`./initial-resources/客户样本.csv`", file_prompt)
        self.assertNotIn("@./initial-resources/", file_prompt)

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
                expected_system_prompt = render_decision_system_prompt(
                    PROJECT_INTAKE_DECISION_RULES,
                    {
                        "产品初稿": {
                            "path": "docs/产品初稿.md",
                            "content": (workspace / "docs/产品初稿.md").read_text(
                                encoding="utf-8"
                            ),
                        },
                        "目标产品定义文档": [
                            path.as_posix() for path in OUTPUTS
                        ],
                    },
                )
                self.assertEqual(system_prompt, expected_system_prompt)
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
            self.assertEqual(calls[1]["prompt"], completion_repair_prompt())
            self.assertEqual(decision_inputs[0][-1], {"role": "user", "content": "完整 Agent 原文 1", "timestamp": decision_inputs[0][-1]["timestamp"]})
            saved = read_state(run_dir)
            self.assertEqual(
                (
                    saved["status"],
                    saved["step"],
                    saved["current_step"],
                    saved["current_node"],
                ),
                ("success", 3, 3, "project:03_foundation_selection"),
            )
            self.assertNotIn("pending_agent_prompt", saved["project_intake"])
            history = json.loads(
                (run_dir / "conversations/project_intake.json").read_text(encoding="utf-8")
            )["messages"]
            self.assertEqual(history[2], decision_inputs[0][-1])
            self.assertEqual(json.loads(history[3]["content"])["verdict"], "completed")
            self.assertEqual(history[4]["content"], completion_repair_prompt())
            self.assertEqual(history[-2], {"role": "user", "content": "完整 Agent 原文 2", "timestamp": history[-2]["timestamp"]})
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
                    "prototype": {"applicable": False, "entry": None, "reason": "纯服务端产品"},
                    "applicable": True,
                    "outputs": [path.as_posix() for path in OUTPUTS],
                    "blocked": None,
                    "error": None,
                },
            )
            state.update({"status": "running", "current_step": 2})
            write_state(run_dir, state)

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("已有成功不应再次调用 Agent")

            outcome = asyncio.run(run(run_dir, state, agent_runner=unexpected_agent))

            self.assertEqual(outcome["status"], "success")
            self.assertEqual(outcome["outputs"], [path.as_posix() for path in OUTPUTS])
            saved = read_state(run_dir)
            self.assertEqual(
                (saved["step"], saved["current_step"], saved["current_node"]),
                (3, 3, "project:03_foundation_selection"),
            )

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
                        {"role": "system", "content": DECISION_LOOP_SPEC.decision_system_prompt},
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
                outcome = asyncio.run(run(run_dir, state, agent_runner=unexpected_agent, config_loader=lambda: object()))

        self.assertEqual(outcome["status"], "success")

    def test_published_draft_is_authoritative_after_source_changes(self) -> None:
        for change in ("deleted", "moved", "modified", "unrecorded"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                source = Path(state["input"]["source_path"])
                if change == "deleted":
                    source.unlink()
                elif change == "moved":
                    source.rename(source.with_name("moved.md"))
                elif change == "modified":
                    source.write_text("源文件已另作他用", encoding="utf-8")
                else:
                    del state["input"]["source_path"]
                calls = []

                async def fake_agent(prompt, **kwargs):
                    calls.append(prompt)
                    self.write_outputs(workspace)
                    current = agent_result(cwd=workspace)
                    kwargs["on_update"](current)
                    return current

                async def completed(messages, config, *, system_prompt):
                    current = decision("completed")
                    return current.model_dump(), 1, current.model_dump_json()

                with patch("steps.step_02_project_intake.step.trust_project"):
                    outcome = asyncio.run(run(
                        run_dir, state, agent_runner=fake_agent,
                        decision_runner=completed, config_loader=lambda: object(),
                    ))
                self.assertEqual(outcome["status"], "success")
                self.assertEqual(len(calls), 1)
                self.assertEqual(read_state(run_dir)["current_step"], 3)

    def test_invalid_published_draft_fails_before_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "docs/产品初稿.md").write_text("changed", encoding="utf-8")

            async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                raise AssertionError("输入核验失败不应调用 Agent")

            with self.assertRaisesRegex(RuntimeError, "初稿.*不一致"):
                asyncio.run(run(run_dir, state, agent_runner=unexpected_agent))

    def write_prototype(self, workspace: Path) -> None:
        entry = workspace / PROTOTYPE_ENTRY
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("<!doctype html><html lang='zh-CN'><title>预约</title></html>", encoding="utf-8")

    def run_product(self, run_dir: Path, workspace: Path, state: dict, *, repair: bool = False, resume_message=None, decisions=None):
        calls = []

        async def agent(prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            if kwargs["task"] == "project_intake":
                self.write_outputs(workspace)
                session = "intake-session"
            else:
                self.assertEqual(
                    read_state(run_dir)["project_intake"]["prototype"]["applicable"], True
                )
                if not repair or len([c for c in calls if c["task"] == "development"]) > 1:
                    self.write_prototype(workspace)
                session = "prototype-session"
            current = agent_result(cwd=workspace, session=session, text="已完成当前任务及实际验证")
            kwargs["on_update"](current)
            return current

        outcomes = iter(decisions) if decisions is not None else None

        async def completed(messages, config, *, system_prompt):
            current = next(outcomes) if outcomes is not None else decision("completed")
            return current.model_dump(), 1, current.model_dump_json()

        outcome = asyncio.run(run(
            run_dir, state, agent_runner=agent, decision_runner=completed,
            config_loader=lambda: object(), resume_message=resume_message,
        ))
        return outcome, calls

    def test_ui_product_uses_separate_prototype_session_and_repairs_missing_entry(self) -> None:
        self.classification.return_value = {"applicable": True, "reason": "有预约页面"}
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            outcome, calls = self.run_product(run_dir, workspace, state, repair=True)
            self.assertEqual([call["task"] for call in calls], ["project_intake", "development", "development"])
            self.assertIsNone(calls[1]["resume_session_id"])
            self.assertEqual(calls[2]["resume_session_id"], "prototype-session")
            self.assertIn("docs/prototype/index.html", calls[2]["prompt"])
            self.assertEqual(outcome["outputs"], [p.as_posix() for p in OUTPUTS])
            self.assertEqual(outcome["prototype"], {
                "applicable": True, "entry": PROTOTYPE_ENTRY.as_posix(), "reason": "有预约页面",
            })
            self.assertEqual(set(state["claude_sessions"]), {"project_intake", "product_prototype"})
            for key in ("project_intake", "product_prototype"):
                history = json.loads((run_dir / f"conversations/{key}.json").read_text())
                self.assertEqual(history["messages"][0]["role"], "system")
            self.classification.assert_awaited_once()
            self.assertEqual(self.classification.call_args.kwargs["purpose"], "prototype")
            context = json.loads(self.classification.call_args.kwargs["context"])
            self.assertEqual(set(context), {p.as_posix() for p in OUTPUTS})
            self.capabilities.assert_called_once_with(workspace.resolve())
            self.assertFalse((workspace / "frontend").exists())
            self.assertFalse((workspace / "backend").exists())

    def test_fresh_modern_step_one_success_can_enter_intake_without_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            state.update({
                "phase": "project_initialization", "step": 2, "current_step": 2,
                "current_node": "project:02_intake", "status": "success",
            })
            write_state(run_dir, state)
            validate_existing_contract(run_dir, state)
            outcome, calls = self.run_product(run_dir, workspace, state)
            self.assertEqual(outcome["status"], "success")
            self.assertEqual([c["task"] for c in calls], ["project_intake"])

    def test_no_ui_product_has_no_prototype_session_plugin_or_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            outcome, calls = self.run_product(run_dir, workspace, state)
            self.assertFalse(outcome["prototype"]["applicable"])
            self.assertIsNone(outcome["prototype"]["entry"])
            self.assertEqual(len(calls), 1)
            self.assertNotIn("product_prototype", state.get("claude_sessions", {}))
            self.assertFalse((run_dir / "conversations/product_prototype.json").exists())
            self.assertFalse((workspace / "docs/prototype").exists())
            self.capabilities.assert_not_called()

    def test_invalid_classification_is_not_false_and_does_not_start_prototype(self) -> None:
        for value in ({"applicable": "false", "reason": "无界面"}, {"applicable": False, "reason": ""}):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                self.classification.return_value = value
                run_dir, workspace, state = self.make_run(Path(directory))
                with self.assertRaises(ValueError):
                    self.run_product(run_dir, workspace, state)
                self.assertNotIn("prototype", state["project_intake"])
                self.assertNotIn("product_prototype", state.get("claude_sessions", {}))
                self.assertFalse((run_dir / "steps/02.json").exists())
        self.capabilities.assert_not_called()

    def test_missing_capability_preserves_classification_before_prototype_session(self) -> None:
        self.classification.return_value = {"applicable": True, "reason": "有界面"}
        self.capabilities.side_effect = RuntimeError("缺少前端能力")
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "缺少前端能力"):
                self.run_product(run_dir, workspace, state)
            self.assertTrue(read_state(run_dir)["project_intake"]["prototype"]["applicable"])
            self.assertNotIn("product_prototype", state.get("claude_sessions", {}))
            self.assertFalse((run_dir / "conversations/product_prototype.json").exists())
            self.capabilities.side_effect = None
            self.classification.side_effect = AssertionError("恢复不得重新分类")
            outcome, calls = self.run_product(run_dir, workspace, state)
            self.assertEqual(outcome["status"], "success")
            self.assertEqual([c["task"] for c in calls], ["development"])

    def test_blocked_prototype_keeps_contract_and_resumes_only_original_domain(self) -> None:
        self.classification.return_value = {"applicable": True, "reason": "有界面"}
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            with self.assertRaises(ProjectIntakeBlocked) as raised:
                self.run_product(run_dir, workspace, state, decisions=[
                    decision("completed"),
                    decision("blocked", reason="缺少必要输入", required_inputs=["提供必要输入"]),
                ])
            self.assertEqual(raised.exception.prototype, state["project_intake"]["prototype"])
            self.assertEqual(raised.exception.required_inputs, ["提供必要输入"])
            state["status"] = "blocked"
            write_state(run_dir, state)
            self.classification.side_effect = AssertionError("原型恢复不得重新分类")
            message = ResumeMessage("product_prototype", "必要输入已补齐，请继续")
            outcome, calls = self.run_product(run_dir, workspace, state, resume_message=message)
            self.assertTrue(message.consumed)
            self.assertEqual(outcome["status"], "success")
            self.assertEqual([c["task"] for c in calls], ["development"])
            self.assertEqual(calls[0]["resume_session_id"], "prototype-session")
            self.assertEqual(calls[0]["prompt"], message.content)

    def test_intake_blocked_then_prototype_init_interruption_remains_message_resumable(self) -> None:
        self.classification.return_value = {"applicable": True, "reason": "有界面"}
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            calls = []
            verdicts = iter([
                decision("blocked", reason="缺少产品输入", required_inputs=["产品输入"]),
                decision("completed"), decision("completed"),
            ])

            async def agent(prompt, **kwargs):
                calls.append((kwargs["task"], prompt, kwargs.get("resume_session_id")))
                is_intake = kwargs["task"] == "project_intake"
                if is_intake:
                    self.write_outputs(workspace)
                else:
                    self.write_prototype(workspace)
                value = agent_result(cwd=workspace, session="intake-session" if is_intake else "prototype-session")
                if len(calls) == 3:
                    value.result_subtype = None
                    value.text = ""
                    kwargs["on_update"](value)
                    raise asyncio.CancelledError()
                return value

            async def decide(*args, **kwargs):
                value = next(verdicts)
                return value.model_dump(), 1, value.model_dump_json()

            def execute(current, resume_message=None):
                return asyncio.run(run(run_dir, current, agent_runner=agent,
                    decision_runner=decide, config_loader=lambda: object(), resume_message=resume_message))

            with self.assertRaises(ProjectIntakeBlocked):
                execute(state)
            # 与 CLI 保存阻塞结果后的父状态一致。
            state.update(status="blocked", blocked={"reason": "缺少产品输入", "required_inputs": ["产品输入"]}, error=None)
            write_state(run_dir, state)
            with self.assertRaises(asyncio.CancelledError):
                execute(read_state(run_dir))
            interrupted = read_state(run_dir)
            message_file = Path(directory) / "resume.txt"
            message_file.write_text("继续完成原型", encoding="utf-8")
            message = prepare_resume_message(message_file, run_dir, interrupted, 2)
            self.assertEqual(message.target_key, "product_prototype")
            self.assertEqual(interrupted["status"], "running")
            self.assertIsNone(interrupted["blocked"])
            self.assertIsNone(interrupted["error"])
            outcome = execute(interrupted, message)
            self.assertEqual(outcome["status"], "success")
            self.assertTrue(message.consumed)
            self.assertEqual(calls[-1], ("development", "继续完成原型", "prototype-session"))
            self.assertEqual(len(calls), 4)

    def test_existing_prototype_blocked_keeps_automatic_resume_semantics(self) -> None:
        self.classification.return_value = {"applicable": True, "reason": "有界面"}
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            with self.assertRaises(ProjectIntakeBlocked):
                self.run_product(run_dir, workspace, state, decisions=[
                    decision("completed"), decision("blocked", reason="缺少必要输入", required_inputs=["必要输入"]),
                ])
            state.update(status="blocked", blocked={"reason": "缺少必要输入", "required_inputs": ["必要输入"]}, error=None)
            write_state(run_dir, state)
            outcome, calls = self.run_product(run_dir, workspace, read_state(run_dir))
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["resume_session_id"], "prototype-session")
            self.assertEqual(calls[0]["prompt"], BLOCKED_RESUME_PROMPT)

    def test_classification_failure_preserves_document_completion_for_retry(self) -> None:
        self.classification.side_effect = RuntimeError("分类请求失败")
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "分类请求失败"):
                self.run_product(run_dir, workspace, state)
            self.assertNotIn("prototype", state["project_intake"])
            self.assertNotIn("product_prototype", state.get("claude_sessions", {}))
            self.classification.side_effect = None
            outcome, calls = self.run_product(run_dir, workspace, state)
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(calls, [])

    def test_current_success_reuses_files_and_repairs_only_original_prototype_session(self) -> None:
        self.classification.return_value = {"applicable": True, "reason": "有界面"}
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            original, _ = self.run_product(run_dir, workspace, state)
            state.update({"step": 2, "current_step": 2, "current_node": "project:02_intake"})
            write_state(run_dir, state)
            self.classification.side_effect = AssertionError("成功复用不得重新分类")
            outcome, calls = self.run_product(run_dir, workspace, state)
            self.assertEqual(outcome, original)
            self.assertEqual(calls, [])
            state.update({"step": 2, "current_step": 2, "current_node": "project:02_intake"})
            write_state(run_dir, state)
            (workspace / PROTOTYPE_ENTRY).unlink()
            outcome, calls = self.run_product(run_dir, workspace, state)
            self.assertEqual(outcome, original)
            self.assertEqual([c["task"] for c in calls], ["development"])
            self.assertEqual(calls[0]["resume_session_id"], "prototype-session")

    def test_old_success_is_rejected_read_only_before_classification(self) -> None:
        for modern in (True, False):
            with self.subTest(modern=modern), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                state.update({"current_step": 2, "status": "success"})
                if modern:
                    state.update({"step": 2, "current_node": "project:02_intake", "phase": "project_initialization"})
                write_state(run_dir, state)
                write_json(run_dir / "steps/02.json", result("success", "旧完成", outputs=[p.as_posix() for p in OUTPUTS]))
                paths = (run_dir / "state.json", run_dir / "steps/02.json")
                before = [path.read_bytes() for path in paths]
                memory = copy.deepcopy(state)
                with self.assertRaises(LegacyFrontendContractError):
                    validate_existing_contract(run_dir, state)
                with self.assertRaises(LegacyFrontendContractError):
                    self.run_product(run_dir, workspace, state)
                self.assertEqual([path.read_bytes() for path in paths], before)
                self.assertEqual(state, memory)
                self.assertFalse((run_dir / "conversations").exists())
        self.classification.assert_not_awaited()
        self.capabilities.assert_not_called()

    def test_historical_success_is_not_subject_to_new_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory))
            state.update({"step": 3, "current_step": 3, "phase": "project_initialization", "current_node": "project:03_foundation_selection"})
            write_state(run_dir, state)
            write_json(run_dir / "steps/02.json", result("success", "旧完成"))
            before = (run_dir / "steps/02.json").read_bytes()
            validate_existing_contract(run_dir, state)
            self.assertEqual((run_dir / "steps/02.json").read_bytes(), before)

    def test_prototype_files_reject_links_directories_and_bad_utf8(self) -> None:
        for invalid in ("symlink", "parent-link", "directory", "bad-utf8"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                entry = workspace / PROTOTYPE_ENTRY
                entry.parent.mkdir(parents=True)
                if invalid == "symlink":
                    entry.symlink_to(workspace / "missing")
                elif invalid == "parent-link":
                    entry.parent.rmdir()
                    entry.parent.symlink_to(workspace / "missing")
                elif invalid == "directory":
                    entry.mkdir()
                else:
                    entry.write_bytes(b"\xff")
                with self.assertRaises(RuntimeError):
                    output_contents(workspace, (PROTOTYPE_ENTRY,))

    def test_prototype_prompt_passes_capabilities_resources_and_runtime_paths(self) -> None:
        prompt = prototype_prompt("initial-resources/客户资料")
        self.assertEqual(prompt.splitlines()[0], "/frontend-ui-ux")
        for text in ("/ui-ux-pro-max:ui-ux-pro-max", "docs/prototype/index.html", ".pcm/runtime.json", "initial-resources/客户资料"):
            self.assertIn(text, prompt)
        self.assertNotIn("第 2 步", prompt)
        self.assertEqual(PROTOTYPE_LOOP_SPEC.task, "development")


if __name__ == "__main__":
    unittest.main()
