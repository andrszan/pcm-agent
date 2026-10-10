from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import SystemMessage
from pydantic import SecretStr

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.agent_decision_loop import AgentExecutionFailure, ResumeMessage
from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import render_decision_system_prompt
from common.files import write_json
from common.frontend_scope import LegacyFrontendContractError
from common.state import read_state, write_state
from common.test_agent_handoff import sdk_result
from config import AgentConfig
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_03_foundation_selection.step import TemplateSelection
from steps.step_05_project_readiness.step import (
    product_output_contents,
    readiness_baseline,
    result as readiness_result,
)
from steps.step_06_project_bootstrap.step import (
    BOOTSTRAP_DECISION_RULES,
    BRAND_ASSETS_DECISION_RULES,
    BRAND_ASSETS_MAX_TURNS,
    COVERAGE_ARTIFACT_REPAIR_PROMPT,
    CURRENT_NODE,
    LEGACY_COMPLETION_MESSAGES,
    NEXT_NODE,
    PROJECT_BOOTSTRAP_MAX_TURNS,
    README_REPAIR_PROMPT,
    TAILWIND_THEME_DECISION_LOOP_SPEC,
    TAILWIND_THEME_DECISION_RULES,
    TAILWIND_THEME_MAX_TURNS,
    ProjectBootstrapBlocked,
    load_prototype,
    prompt_assembly,
    result,
    run,
    verify_existing_bootstrap_success,
    verify_tailwind_v4_frontend,
)


def agent_result(
    *,
    cwd: Path,
    session: str = "session-1",
    text: str = "项目化完整回复",
    skills: list[str] | None = None,
) -> ClaudeRunResult:
    loaded = ["project-bootstrap"] if skills is None else skills
    return ClaudeRunResult(
        init={"cwd": str(cwd), "skills": loaded, "slash_commands": loaded},
        text=text,
        result_subtype="success",
        is_error=False,
        session_id=session,
        stop_reason="end_turn",
        num_turns=1,
        total_cost_usd=0.1,
        exception=None,
    )


def agent_result_for_prompt(
    prompt: str,
    *,
    cwd: Path,
    text: str | None = None,
) -> ClaudeRunResult:
    if prompt.startswith("/frontend-ui-ux\n") and "页面品牌标识" in prompt:
        session, skill, default_text = "session-brand", "frontend-ui-ux", "品牌资产完整回复"
    elif prompt.startswith("/tailwind-theme\n"):
        session, skill, default_text = "session-theme", "tailwind-theme", "主题完整回复"
    else:
        session, skill, default_text = "session-bootstrap", "project-bootstrap", "项目化完整回复"
    return agent_result(
        cwd=cwd,
        session=session,
        text=text or default_text,
        skills=[skill, "ui-ux-pro-max:ui-ux-pro-max"] if skill != "project-bootstrap" else [skill],
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


class ProjectBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        capabilities = patch("steps.step_06_project_bootstrap.step.ensure_frontend_capabilities")
        self.capabilities = capabilities.start()
        self.addCleanup(capabilities.stop)

    def make_run(
        self,
        root: Path,
        *,
        applicable: bool = True,
        frontend: bool = True,
    ) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        (workspace / "docs/requirements").mkdir(parents=True)
        requirements = "docs/requirements/项目需求说明.md"
        features = "docs/requirements/产品功能说明.md"
        checklist = "docs/requirements/项目准备清单.md"
        for output in (requirements, features):
            (workspace / output).write_text(f"# {Path(output).stem}\n", encoding="utf-8")
        (workspace / checklist).write_text(
            "# 项目准备清单\n\n最终数据库绑定：PostgreSQL\n",
            encoding="utf-8",
        )

        outputs: list[str] = []
        selections: dict[str, dict | None] = {"frontend": None, "backend": None}
        assembly_entries: dict[str, dict | None] = {"frontend": None, "backend": None}
        if applicable:
            target = "frontend" if frontend else "backend"
            target_path = workspace / target
            target_path.mkdir()
            if frontend:
                (target_path / "src").mkdir()
                (target_path / "package.json").write_text(
                    '{"dependencies":{"tailwindcss":"^4.1.0"}}\n', encoding="utf-8"
                )
                (target_path / "src/index.css").write_text(
                    '@import "tailwindcss";\n', encoding="utf-8"
                )
            else:
                (target_path / "pyproject.toml").write_text(
                    '[project]\nname = "backend"\nversion = "0.1.0"\n', encoding="utf-8"
                )
            initialize_root_repository(target_path)
            selections[target] = TemplateSelection(
                id=f"{target}-template",
                git_url="file:///templates.git",
                default_branch="main",
                path=f"templates/{target}",
                reason="test",
            ).model_dump(mode="json")
            outputs = [target]
            assembly_entries[target] = {
                "target": target,
                "id": f"{target}-template",
                "git_url": "file:///templates.git",
                "default_branch": "main",
                "path": f"templates/{target}",
                "origin": "file:///templates.git",
                "branch": "main",
                "commit_sha": "a" * 40,
            }

        prototype = {
            "applicable": applicable and frontend,
            "entry": "docs/prototype/index.html" if applicable and frontend else None,
            "reason": "提供可交互产品界面" if applicable and frontend else "仅服务端或无工程交付",
        }
        if prototype["applicable"]:
            (workspace / "docs/prototype").mkdir()
            (workspace / prototype["entry"]).write_text(
                "<!doctype html><title>产品原型</title><main>工作台</main>", encoding="utf-8"
            )
        write_json(
            run_dir / "steps/02.json",
            {"step": 2, "status": "success", "outputs": [requirements, features], "prototype": prototype},
        )
        write_json(
            run_dir / "steps/03.json",
            {
                "step": 3,
                "status": "success",
                "template_selection": selections,
            },
        )
        write_json(
            run_dir / "steps/04.json",
            {
                "step": 4,
                "status": "success",
                "applicable": applicable,
                "outputs": outputs,
                "assembly": assembly_entries,
            },
        )
        write_json(
            run_dir / "steps/05.json",
            readiness_result(
                "success",
                "准备基线已完成。",
                outputs=[checklist],
                readiness_baseline=readiness_baseline(
                    workspace, [requirements, features]
                ),
            ),
        )
        root_repository = initialize_root_repository(workspace)
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": "project_initialization",
            "step": 6,
            "current_step": 6,
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

    def test_completed_repair_resumes_same_session_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            runtime = workspace / ".pcm/runtime.json"
            runtime.parent.mkdir()
            runtime.write_text(
                '{"services":{"frontend":{"port":3137},"backend":{"port":8137}}}\n',
                encoding="utf-8",
            )
            state["coordination"] = {
                "runtime_path": ".pcm/runtime.json",
                "ports": {"frontend": 3137, "backend": 8137},
            }
            write_state(run_dir, state)
            calls: list[dict] = []
            system_prompts: list[str] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                current = agent_result_for_prompt(
                    prompt,
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    text=f"执行回复 {len(calls)}",
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                system_prompts.append(system_prompt)
                return decision("completed")

            with patch(
                "steps.step_06_project_bootstrap.step.render_decision_system_prompt",
                wraps=render_decision_system_prompt,
            ) as render_prompt:
                outcome = self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )
            self.assertEqual(outcome["outputs"], ["frontend"])
            self.assertIs(outcome["tailwind_theme"], True)
            self.assertIn("基础品牌资产已完成适用接入", outcome["summary"])
            self.assertNotIn("token", outcome["summary"])
            self.assertEqual(len(calls), 4)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(calls[1]["resume_session_id"], "session-bootstrap")
            self.assertEqual(calls[1]["prompt"], README_REPAIR_PROMPT)
            self.assertIsNone(calls[2]["resume_session_id"])
            self.assertIsNone(calls[3]["resume_session_id"])
            self.assertEqual(TAILWIND_THEME_MAX_TURNS, 9999)
            self.assertEqual(calls[2]["max_turns"], TAILWIND_THEME_MAX_TURNS)
            self.assertEqual(BRAND_ASSETS_MAX_TURNS, 9999)
            self.assertEqual(calls[3]["max_turns"], BRAND_ASSETS_MAX_TURNS)

            product_outputs = [
                "docs/requirements/项目需求说明.md",
                "docs/requirements/产品功能说明.md",
            ]
            bootstrap_prompt = calls[0]["prompt"]
            self.assertEqual(bootstrap_prompt.splitlines()[0], "/project-bootstrap")
            for reference in (
                "@./docs/requirements/项目需求说明.md",
                "@./docs/requirements/产品功能说明.md",
                "@./docs/requirements/项目准备清单.md",
                "@./frontend",
                "@./.pcm/runtime.json",
            ):
                self.assertIn(reference, bootstrap_prompt)
            for hidden in ("file:///templates.git", "git_url", "origin"):
                self.assertNotIn(hidden, bootstrap_prompt)
            self.assertIn("最终绑定为权威选择", bootstrap_prompt)
            self.assertIn("本地 Agent 规则", bootstrap_prompt)
            self.assertEqual(calls[0]["max_turns"], PROJECT_BOOTSTRAP_MAX_TURNS)
            self.assertNotIn("max_budget_usd", calls[0])

            theme_prompt = calls[2]["prompt"]
            self.assertEqual(theme_prompt.splitlines()[0], "/tailwind-theme")
            self.assertEqual(TAILWIND_THEME_DECISION_LOOP_SPEC.skill_name, "tailwind-theme")
            for text in (
                "请实际通过 Skill 工具调用 /ui-ux-pro-max:ui-ux-pro-max",
                "不推翻已确认的产品与视觉方向", "借用或适配 preset",
                "对比度", "暗色", "字体", "组件状态", "工程校准和验证",
                "不逐个冻结原型中的偶然 CSS", "不重新挑选品牌", "不开发业务页面",
            ):
                self.assertIn(text, theme_prompt)
            self.assertNotIn("不重新选择 preset", theme_prompt)
            for reference in (
                "@./docs/requirements/项目需求说明.md",
                "@./docs/requirements/产品功能说明.md",
                "@./frontend",
            ):
                self.assertIn(reference, theme_prompt)

            brand_prompt = calls[3]["prompt"]
            self.assertEqual(brand_prompt.splitlines()[0], "/frontend-ui-ux")
            for domain_prompt in (bootstrap_prompt, theme_prompt, brand_prompt):
                self.assertIn("@./docs/prototype/index.html", domain_prompt)
                self.assertIn("只读", domain_prompt)
            for domain_prompt in (theme_prompt, brand_prompt):
                self.assertIn("/ui-ux-pro-max:ui-ux-pro-max", domain_prompt)
            self.assertIn("生成服务不可用时", brand_prompt)
            self.assertIn("实际查看", brand_prompt)
            self.assertIn("SVG", brand_prompt)
            self.assertEqual([call["task"] for call in calls], [
                "project_bootstrap", "project_bootstrap", "tailwind_theme", "brand_assets",
            ])
            self.capabilities.assert_called_once_with(workspace.resolve())
            for reference in (
                "@./docs/requirements/项目需求说明.md",
                "@./docs/requirements/产品功能说明.md",
                "@./frontend",
                "@./.pcm/runtime.json",
            ):
                self.assertIn(reference, brand_prompt)

            assembly = json.loads(
                (run_dir / "steps/04.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(render_prompt.call_args_list), 3)
            bootstrap_rules, bootstrap_context = render_prompt.call_args_list[0].args
            theme_rules, theme_context = render_prompt.call_args_list[1].args
            brand_rules, brand_context = render_prompt.call_args_list[2].args
            self.assertEqual(bootstrap_rules, BOOTSTRAP_DECISION_RULES)
            self.assertEqual(theme_rules, TAILWIND_THEME_DECISION_RULES)
            self.assertEqual(brand_rules, BRAND_ASSETS_DECISION_RULES)
            self.assertEqual(
                bootstrap_context["产品定义"],
                product_output_contents(workspace, product_outputs),
            )
            self.assertEqual(
                bootstrap_context["已完成的项目准备基线"],
                "# 项目准备清单\n\n最终数据库绑定：PostgreSQL\n",
            )
            self.assertIn("README", bootstrap_context["派生变体收口"])
            self.assertIn(".claude/rules", bootstrap_context["派生变体收口"])
            self.assertEqual(
                bootstrap_context["组装白名单事实"], prompt_assembly(assembly)
            )
            prototype = load_prototype(run_dir, workspace)
            for context in (bootstrap_context, theme_context, brand_context):
                self.assertEqual(context["产品原型"], prototype)
            self.assertEqual(theme_context["实际前端"], ["frontend"])
            self.assertEqual(brand_context["实际前端"], ["frontend"])
            self.assertEqual(
                brand_context["产品本机运行配置"], {"path": ".pcm/runtime.json"}
            )
            rendered_prompts = [
                render_decision_system_prompt(*call.args)
                for call in render_prompt.call_args_list
            ]
            self.assertEqual(
                system_prompts,
                [rendered_prompts[0], rendered_prompts[0], *rendered_prompts[1:]],
            )
            for system_prompt in system_prompts:
                for hidden in ("file:///templates.git", "git_url", "origin"):
                    self.assertNotIn(hidden, system_prompt)

            saved = read_state(run_dir)
            self.assertEqual((saved["step"], saved["current_node"]), (7, NEXT_NODE))
            self.assertEqual(
                saved["claude_sessions"],
                {
                    "project_bootstrap": "session-bootstrap",
                    "tailwind_theme": "session-theme",
                    "brand_assets": "session-brand",
                },
            )
            bootstrap_history = json.loads(
                (run_dir / "conversations/project_bootstrap.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(
                [item["role"] for item in bootstrap_history],
                ["system", "assistant", "user", "assistant", "assistant", "user", "assistant"],
            )
            self.assertEqual(
                json.loads(bootstrap_history[-1]["content"])["verdict"], "completed"
            )
            self.assertNotIn(
                LEGACY_COMPLETION_MESSAGES[0],
                [item["content"] for item in bootstrap_history],
            )
            theme_history = json.loads(
                (run_dir / "conversations/tailwind_theme.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(
                [item["role"] for item in theme_history],
                ["system", "assistant", "user", "assistant"],
            )
            self.assertEqual(
                json.loads(theme_history[-1]["content"])["verdict"], "completed"
            )
            brand_history = json.loads(
                (run_dir / "conversations/brand_assets.json").read_text(
                    encoding="utf-8"
                )
            )["messages"]
            self.assertEqual(
                [item["role"] for item in brand_history],
                ["system", "assistant", "user", "assistant"],
            )
            self.assertEqual(
                json.loads(brand_history[-1]["content"])["verdict"], "completed"
            )

            saved.pop("project_bootstrap", None)
            saved.pop("tailwind_theme", None)
            saved.pop("brand_assets", None)
            saved.pop("claude_sessions", None)
            saved.pop("decision_conversations", None)
            write_state(run_dir, saved)

            async def unexpected(*args, **kwargs):
                raise AssertionError("既有成功不应调用 Agent 或决策模型")

            reused = self.run_step(
                run_dir,
                saved,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(reused["status"], "success")
            self.assertIs(reused["tailwind_theme"], True)
            self.assertIn("确认既有成功", reused["summary"])
            self.assertNotIn("品牌", reused["summary"])

    def test_sdk_runner_continues_theme_in_same_session_and_can_keep_default_style(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
            frontend = workspace / "frontend"
            before = {
                path.relative_to(frontend): path.read_bytes()
                for path in (frontend / "package.json", frontend / "src/index.css")
            }
            calls: list[str] = []
            sessions: list[str | None] = []

            async def fake_query(*, prompt, options):
                calls.append(prompt)
                sessions.append(options.resume)
                current = agent_result_for_prompt(
                    "/tailwind-theme\n" if options.resume == "session-theme" else prompt,
                    cwd=workspace,
                    text="现有默认风格适合当前产品，保留现状，无需修改。",
                )
                yield SystemMessage(subtype="init", data={
                    **current.init, "session_id": current.session_id, "model": options.model,
                })
                yield sdk_result(current.text, session_id=current.session_id)

            async def sdk_agent(prompt, **kwargs):
                return await run_claude(
                    prompt, **kwargs, agent_config_loader=lambda: AgentConfig(
                        base_url="https://agent.example.invalid", auth_token=SecretStr("test-secret"),
                    ),
                )

            async def completed(messages, config, *, system_prompt):
                if len(calls) == 2:
                    return decision("continue", answer="继续完成适用验证")
                return decision("completed")

            with patch("common.claude_agent.query", new=fake_query), patch(
                "common.claude_agent.load_plugins", return_value=[],
            ):
                outcome = self.run_step(
                    run_dir,
                    state,
                    agent_runner=sdk_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )
            self.assertEqual(outcome["status"], "success")
            self.assertIs(outcome["tailwind_theme"], True)
            self.assertEqual(len(calls), 4)
            self.assertEqual(sessions, [None, None, "session-theme", None])
            self.assertTrue(calls[1].startswith("/tailwind-theme\n"))
            self.assertEqual(calls[2], "继续完成适用验证")
            self.assertTrue(calls[3].startswith("/frontend-ui-ux\n"))
            for relative, contents in before.items():
                self.assertEqual((frontend / relative).read_bytes(), contents)

    def test_unignored_coverage_artifact_uses_same_session_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
            coverage = workspace / ".coverage"
            coverage.write_bytes(b"coverage")
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                if len(calls) == 2:
                    coverage.unlink()
                current = agent_result_for_prompt(
                    prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertIs(saved["tailwind_theme"], True)
            self.assertEqual(len(calls), 4)
            self.assertEqual(calls[1]["resume_session_id"], "session-bootstrap")
            self.assertEqual(calls[1]["prompt"], COVERAGE_ARTIFACT_REPAIR_PROMPT)
            self.assertTrue(calls[2]["prompt"].startswith("/tailwind-theme\n"))
            self.assertTrue(calls[3]["prompt"].startswith("/frontend-ui-ux\n"))

    def test_blocked_decision_preserves_domain_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked(messages, config, *, system_prompt):
                return decision(
                    "blocked",
                    reason="使用既有配置执行健康检查时，外部授权已失效",
                    required_inputs=["恢复既有外部授权后重新验证健康检查"],
                )

            with self.assertRaises(ProjectBootstrapBlocked) as raised:
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=blocked,
                    config_loader=lambda: object(),
                )
            self.assertEqual(
                raised.exception.required_inputs,
                ["恢复既有外部授权后重新验证健康检查"],
            )
            self.assertEqual(raised.exception.outputs, ["frontend"])
            self.assertTrue(workspace.is_dir())
            self.assertFalse((run_dir / "conversations/tailwind_theme.json").exists())
            self.assertNotIn("tailwind_theme", read_state(run_dir).get("claude_sessions", {}))

    def test_blocked_decision_rechecks_git_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def staging_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                subprocess.run(
                    ["git", "add", "README.md"],
                    cwd=workspace,
                    check=True,
                    capture_output=True,
                )
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked(messages, config, *, system_prompt):
                return decision(
                    "blocked",
                    reason="使用既有配置执行健康检查时，外部授权已失效",
                    required_inputs=["恢复既有外部授权后重新验证健康检查"],
                )

            with self.assertRaisesRegex(RuntimeError, "不得暂存文件"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=staging_agent,
                    decision_runner=blocked,
                    config_loader=lambda: object(),
                )

    def test_blocked_decision_rechecks_coverage_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / ".coverage").write_bytes(b"coverage")

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked(messages, config, *, system_prompt):
                return decision(
                    "blocked",
                    reason="使用既有配置执行健康检查时，外部授权已失效",
                    required_inputs=["恢复既有外部授权后重新验证健康检查"],
                )

            with self.assertRaisesRegex(RuntimeError, "覆盖率数据库"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=fake_agent,
                    decision_runner=blocked,
                    config_loader=lambda: object(),
                )

    def test_root_and_child_repository_changes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def staging_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                subprocess.run(
                    ["git", "add", "README.md"], cwd=workspace, check=True, capture_output=True
                )
                current = agent_result(cwd=kwargs["cwd"])  # type: ignore[arg-type, index]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            with self.assertRaisesRegex(RuntimeError, "完成核验失败"):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=staging_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )

        for mutation in ("staged", "committed", "non-main"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                frontend = workspace / "frontend"
                if mutation == "staged":
                    subprocess.run(
                        ["git", "add", "package.json"], cwd=frontend, check=True, capture_output=True
                    )
                elif mutation == "committed":
                    subprocess.run(
                        ["git", "add", "package.json"], cwd=frontend, check=True, capture_output=True
                    )
                    subprocess.run(
                        [
                            "git",
                            "-c",
                            "user.name=PCM Test",
                            "-c",
                            "user.email=pcm@example.invalid",
                            "commit",
                            "-m",
                            "test",
                        ],
                        cwd=frontend,
                        check=True,
                        capture_output=True,
                    )
                else:
                    subprocess.run(
                        ["git", "switch", "-c", "feature"],
                        cwd=frontend,
                        check=True,
                        capture_output=True,
                    )

                async def unexpected_agent(*args: object, **kwargs: object) -> ClaudeRunResult:
                    raise AssertionError("子仓边界异常不应调用 Agent")

                with self.assertRaisesRegex(RuntimeError, "Git 仓库"):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=unexpected_agent,
                        config_loader=lambda: object(),
                    )

    def test_failed_result_file_does_not_block_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            write_json(run_dir / "steps/06.json", {"step": 6, "status": "failed"})

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                current = agent_result_for_prompt(
                    prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            saved = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(saved["status"], "success")
            self.assertIs(saved["tailwind_theme"], True)

    def test_backend_only_runs_bootstrap_and_skips_theme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(
                Path(directory), frontend=False
            )
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                current = agent_result_for_prompt(
                    prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["outputs"], ["backend"])
            self.assertIs(outcome["tailwind_theme"], False)
            self.capabilities.assert_not_called()
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0]["prompt"].startswith("/project-bootstrap\n"))
            self.assertFalse((run_dir / "conversations/tailwind_theme.json").exists())
            self.assertNotIn("tailwind_theme", read_state(run_dir).get("claude_sessions", {}))

    def test_tailwind_gate_accepts_explicit_v4_ranges_and_single_quote_import(self) -> None:
        for version in ("^4", "4.1.0", "workspace:^4.1.0", ">=4 <5"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                _, workspace, _ = self.make_run(Path(directory))
                (workspace / "frontend/package.json").write_text(
                    json.dumps(
                        {"dependencies": {"tailwindcss": version}}, ensure_ascii=False
                    )
                    + "\n",
                    encoding="utf-8",
                )
                (workspace / "frontend/src/index.css").write_text(
                    "@import 'tailwindcss';\n", encoding="utf-8"
                )
                verify_tailwind_v4_frontend(workspace)

    def test_tailwind_gate_accepts_import_options_url_and_inline_css(self) -> None:
        for css in (
            '@import "tailwindcss" source("../src");',
            '@import "tailwindcss"; body { color: black; }',
            '@layer theme, base, components, utilities; @import "tailwindcss";',
            '@import url("tailwindcss");',
            "@import url('tailwindcss') source(none);",
            '@import url(tailwindcss); body { color: black; }',
            '@import /* 入口 */ "tailwindcss" source("../src");',
            '/* "仅为注释 {" */ @import "tailwindcss" source("../src");',
            '@import "tailwindcss" layer(utilities) supports(display: grid) screen;',
        ):
            with self.subTest(css=css), tempfile.TemporaryDirectory() as directory:
                _, workspace, _ = self.make_run(Path(directory))
                (workspace / "frontend/src/index.css").write_text(css, encoding="utf-8")
                verify_tailwind_v4_frontend(workspace)

    def test_tailwind_gate_rejects_commented_or_malformed_imports(self) -> None:
        for css in (
            '/* @import "tailwindcss" source("../src"); */',
            '/* @import url(tailwindcss); */ body { color: black; }',
            '@import "tailwindcss/utilities";',
            '@import url("tailwindcss);',
            '@import "tailwindcss"invalid;',
            '@import "tailwindcss" body { color: black; }',
        ):
            with self.subTest(css=css), tempfile.TemporaryDirectory() as directory:
                _, workspace, _ = self.make_run(Path(directory))
                (workspace / "frontend/src/index.css").write_text(css, encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "CSS-first"):
                    verify_tailwind_v4_frontend(workspace)

    def test_tailwind_gate_rejects_import_directives_inside_strings_or_blocks(self) -> None:
        for css in (
            ':root { --example: @import "tailwindcss"; }',
            ':root { --brace: "}"; --example: @import "tailwindcss"; }',
            """:root { --example: '; @import "tailwindcss";'; }""",
            ''':root { --example: "; @import 'tailwindcss';"; }''',
            r""":root { --example: 'escaped \'; @import "tailwindcss";'; }""",
            ''':root { --example: "/*"; --other: "*/; @import 'tailwindcss';"; }''',
            """:root { --example: '; @import url(tailwindcss);'; }""",
        ):
            with self.subTest(css=css), tempfile.TemporaryDirectory() as directory:
                _, workspace, _ = self.make_run(Path(directory))
                (workspace / "frontend/src/index.css").write_text(css, encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "CSS-first"):
                    verify_tailwind_v4_frontend(workspace)

    def test_frontend_must_be_tailwind_v4_css_first_before_theme_session(self) -> None:
        for invalid in (
            "v3",
            "file-version",
            "ambiguous-range",
            "missing-import",
            "commented-import",
            "split-import-token",
            "split-module-name",
        ):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
                if invalid in {"v3", "file-version", "ambiguous-range"}:
                    versions = {
                        "v3": "^3.4.0",
                        "file-version": "file:../tailwindcss4",
                        "ambiguous-range": "4 || 5",
                    }
                    (workspace / "frontend/package.json").write_text(
                        json.dumps(
                            {"dependencies": {"tailwindcss": versions[invalid]}},
                            ensure_ascii=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                elif invalid == "missing-import":
                    (workspace / "frontend/src/index.css").write_text(
                        "body { color: black; }\n", encoding="utf-8"
                    )
                elif invalid == "commented-import":
                    (workspace / "frontend/src/index.css").write_text(
                        '/* @import "tailwindcss"; */\nbody { color: black; }\n',
                        encoding="utf-8",
                    )
                elif invalid == "split-import-token":
                    (workspace / "frontend/src/index.css").write_text(
                        '@im/**/port "tailwindcss";\n', encoding="utf-8"
                    )
                else:
                    (workspace / "frontend/src/index.css").write_text(
                        '@import "tail/*x*/windcss";\n', encoding="utf-8"
                    )
                calls: list[dict] = []

                async def bootstrap_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                    if prompt.startswith("/tailwind-theme\n"):
                        raise AssertionError("无效 Tailwind 合同不应调用 theme Agent")
                    calls.append({"prompt": prompt, **kwargs})
                    current = agent_result_for_prompt(
                        prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                    )
                    kwargs["on_update"](current)  # type: ignore[index, operator]
                    return current

                async def completed(messages, config, *, system_prompt):
                    return decision("completed")

                with self.assertRaisesRegex(RuntimeError, "Tailwind CSS v4"):
                    self.run_step(
                        run_dir,
                        state,
                        agent_runner=bootstrap_agent,
                        decision_runner=completed,
                        config_loader=lambda: object(),
                    )
                self.assertEqual(len(calls), 1)
                self.assertFalse((run_dir / "conversations/tailwind_theme.json").exists())
                result_path = run_dir / "steps/06.json"
                if result_path.exists():
                    self.assertNotEqual(
                        json.loads(result_path.read_text(encoding="utf-8"))["status"],
                        "success",
                    )

    def test_legacy_theme_blocked_resumes_same_session_and_snapshot_without_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
            calls: list[dict] = []

            async def first_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                current = agent_result_for_prompt(
                    prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                )
                if kwargs["task"] == "tailwind_theme":
                    current.session_id = "session-theme"
                    current.init["skills"] = ["frontend-ui-ux"]
                    current.init["slash_commands"] = ["frontend-ui-ux"]
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            decision_calls = 0

            async def first_decision(messages, config, *, system_prompt):
                nonlocal decision_calls
                decision_calls += 1
                if decision_calls == 2:
                    return decision(
                        "blocked",
                        reason="缺少不可替代的授权品牌资料",
                        required_inputs=["提供授权品牌资料"],
                    )
                return decision("completed")

            with patch(
                "steps.step_06_project_bootstrap.step.TAILWIND_THEME_DECISION_LOOP_SPEC",
                replace(TAILWIND_THEME_DECISION_LOOP_SPEC, skill_name="frontend-ui-ux"),
            ), patch(
                "steps.step_06_project_bootstrap.step.tailwind_theme_initial_prompt",
                return_value="/frontend-ui-ux\n旧主题任务",
            ), patch(
                "steps.step_06_project_bootstrap.step.TAILWIND_THEME_DECISION_RULES",
                "- completed：旧主题设计已完成。",
            ), self.assertRaises(ProjectBootstrapBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=first_agent,
                    decision_runner=first_decision,
                    config_loader=lambda: object(),
                )
            self.assertEqual(len(calls), 2)
            self.assertEqual(decision_calls, 2)
            self.assertTrue(calls[0]["prompt"].startswith("/project-bootstrap\n"))
            self.assertTrue(calls[1]["prompt"].startswith("/frontend-ui-ux\n"))
            theme_history_path = run_dir / "conversations/tailwind_theme.json"
            theme_system = json.loads(theme_history_path.read_text())["messages"][0]
            self.assertIn("旧主题设计已完成", theme_system["content"])

            resumed_state = read_state(run_dir)
            resumed_state.update(
                {
                    "status": "blocked",
                    "blocked": {
                        "reason": "缺少不可替代的授权品牌资料",
                        "required_inputs": ["提供授权品牌资料"],
                    },
                }
            )
            write_state(run_dir, resumed_state)
            resumed_calls: list[dict] = []

            async def resumed_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                resumed_calls.append({"prompt": prompt, **kwargs})
                if prompt == "使用负责人提供的品牌决定":
                    self.assertEqual(kwargs["resume_session_id"], "session-theme")
                    current = agent_result(
                        cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                        session="session-theme",
                        text="主题恢复完成",
                        skills=["tailwind-theme", "ui-ux-pro-max:ui-ux-pro-max"],
                    )
                else:
                    self.assertTrue(prompt.startswith("/frontend-ui-ux\n"))
                    self.assertIsNone(kwargs["resume_session_id"])
                    current = agent_result_for_prompt(
                        prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                    )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def resumed_decision(messages, config, *, system_prompt):
                return decision("completed")

            resume_message = ResumeMessage("tailwind_theme", "使用负责人提供的品牌决定")
            outcome = self.run_step(
                run_dir,
                resumed_state,
                agent_runner=resumed_agent,
                decision_runner=resumed_decision,
                config_loader=lambda: object(),
                resume_message=resume_message,
            )
            self.assertIs(outcome["tailwind_theme"], True)
            self.assertEqual(json.loads(theme_history_path.read_text())["messages"][0], theme_system)
            self.assertTrue(resume_message.consumed)
            self.assertEqual(len(resumed_calls), 2)
            self.assertEqual(resumed_calls[0]["prompt"], "使用负责人提供的品牌决定")
            self.assertTrue(resumed_calls[1]["prompt"].startswith("/frontend-ui-ux\n"))
            self.assertFalse(resumed_calls[0]["prompt"].startswith("/project-bootstrap\n"))

    def test_brand_agent_failure_resumes_brand_session_without_rerunning_previous_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
            calls: list[str] = []

            async def failing_brand_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append(prompt)
                current = agent_result_for_prompt(
                    prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                )
                if kwargs["task"] == "brand_assets":
                    current.result_subtype = "error"
                    current.is_error = True
                    current.has_errors = True
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            with self.assertRaises(AgentExecutionFailure):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=failing_brand_agent,
                    decision_runner=completed,
                    config_loader=lambda: object(),
                )
            self.assertEqual(
                [prompt.splitlines()[0] for prompt in calls],
                ["/project-bootstrap", "/tailwind-theme", "/frontend-ui-ux"],
            )

            resumed_calls: list[dict] = []

            async def resumed_brand_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                resumed_calls.append({"prompt": prompt, **kwargs})
                self.assertTrue(prompt.startswith("/frontend-ui-ux\n"))
                self.assertEqual(kwargs["resume_session_id"], "session-brand")
                current = agent_result_for_prompt(
                    prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            outcome = self.run_step(
                run_dir,
                read_state(run_dir),
                agent_runner=resumed_brand_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(resumed_calls), 1)

    def test_historical_frontend_success_does_not_create_or_claim_brand_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
            intake_path = run_dir / "steps/02.json"
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            intake.pop("prototype")
            write_json(intake_path, intake)
            (workspace / "docs/prototype/index.html").unlink()
            historical = result(
                "success",
                "历史基础工程成功。",
                outputs=["frontend"],
                tailwind_theme=True,
            )
            write_json(run_dir / "steps/06.json", historical)
            state.update(
                {
                    "status": "success",
                    "step": 7,
                    "current_step": 7,
                    "current_node": NEXT_NODE,
                }
            )
            write_state(run_dir, state)
            before = (run_dir / "steps/06.json").read_bytes()

            async def unexpected(*args, **kwargs):
                raise AssertionError("历史成功不应调用 Agent 或负责人")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(outcome["status"], "success")
            self.assertNotIn("品牌", outcome["summary"])
            self.capabilities.assert_not_called()
            self.assertEqual((run_dir / "steps/06.json").read_bytes(), before)
            self.assertFalse((run_dir / "conversations/brand_assets.json").exists())
            saved = read_state(run_dir)
            self.assertNotIn("brand_assets", saved)
            self.assertNotIn("brand_assets", saved.get("claude_sessions", {}))

    def test_brand_blocked_resumes_brand_without_rerunning_previous_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")
            calls: list[dict] = []

            async def first_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append({"prompt": prompt, **kwargs})
                current = agent_result_for_prompt(
                    prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            decision_calls = 0

            async def block_brand(messages, config, *, system_prompt):
                nonlocal decision_calls
                decision_calls += 1
                if decision_calls == 3:
                    return decision(
                        "blocked",
                        reason="缺少不可替代的品牌决定",
                        required_inputs=["提供品牌决定"],
                    )
                return decision("completed")

            with self.assertRaises(ProjectBootstrapBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=first_agent,
                    decision_runner=block_brand,
                    config_loader=lambda: object(),
                )
            self.assertEqual(
                [call["prompt"].splitlines()[0] for call in calls],
                ["/project-bootstrap", "/tailwind-theme", "/frontend-ui-ux"],
            )
            self.assertEqual(decision_calls, 3)

            resumed_state = read_state(run_dir)
            resumed_state.update(
                {
                    "status": "blocked",
                    "blocked": {
                        "reason": "缺少不可替代的品牌决定",
                        "required_inputs": ["提供品牌决定"],
                    },
                }
            )
            write_state(run_dir, resumed_state)
            resumed_calls: list[dict] = []

            async def resumed_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                resumed_calls.append({"prompt": prompt, **kwargs})
                self.assertEqual(kwargs["resume_session_id"], "session-brand")
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    session="session-brand",
                    text="品牌资产恢复完成",
                    skills=["frontend-ui-ux"],
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            resume_message = ResumeMessage("brand_assets", "使用负责人提供的品牌决定")
            outcome = self.run_step(
                run_dir,
                resumed_state,
                agent_runner=resumed_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
                resume_message=resume_message,
            )
            self.assertEqual(outcome["status"], "success")
            self.assertTrue(resume_message.consumed)
            self.assertEqual(len(resumed_calls), 1)
            self.assertEqual(resumed_calls[0]["prompt"], "使用负责人提供的品牌决定")

    def test_bootstrap_manual_resume_is_consumed_before_new_theme_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / "README.md").write_text("# 项目\n", encoding="utf-8")

            async def first_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                current = agent_result_for_prompt(
                    prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def blocked_bootstrap(messages, config, *, system_prompt):
                return decision(
                    "blocked",
                    reason="缺少负责人决定",
                    required_inputs=["负责人决定"],
                )

            with self.assertRaises(ProjectBootstrapBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=first_agent,
                    decision_runner=blocked_bootstrap,
                    config_loader=lambda: object(),
                )

            resumed_state = read_state(run_dir)
            resumed_state.update(
                {
                    "status": "blocked",
                    "blocked": {
                        "reason": "缺少负责人决定",
                        "required_inputs": ["负责人决定"],
                    },
                }
            )
            write_state(run_dir, resumed_state)
            resume_message = ResumeMessage("project_bootstrap", "负责人决定原文")
            calls: list[str] = []

            async def resumed_agent(prompt: str, **kwargs: object) -> ClaudeRunResult:
                calls.append(prompt)
                current = agent_result_for_prompt(
                    prompt, cwd=kwargs["cwd"]  # type: ignore[arg-type, index]
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def completed(messages, config, *, system_prompt):
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                resumed_state,
                agent_runner=resumed_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
                resume_message=resume_message,
            )

            self.assertEqual(outcome["status"], "success")
            self.assertTrue(resume_message.consumed)
            self.assertEqual(calls[0], "负责人决定原文")
            self.assertTrue(calls[1].startswith("/tailwind-theme\n"))
            self.assertEqual(calls.count("负责人决定原文"), 1)

    def test_prototype_handoff_validation_precedes_agent_and_state_writes(self) -> None:
        for invalid in ("missing", "wrong-entry", "empty-file", "missing-file", "symlink"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                intake_path = run_dir / "steps/02.json"
                intake = json.loads(intake_path.read_text(encoding="utf-8"))
                entry = workspace / "docs/prototype/index.html"
                if invalid == "missing":
                    intake.pop("prototype")
                elif invalid == "wrong-entry":
                    intake["prototype"]["entry"] = "docs/other.html"
                elif invalid == "empty-file":
                    entry.write_text("  ", encoding="utf-8")
                elif invalid == "missing-file":
                    entry.unlink()
                else:
                    entry.unlink()
                    entry.symlink_to(workspace / intake["outputs"][0])
                write_json(intake_path, intake)
                before = (run_dir / "state.json").read_bytes()

                async def unexpected(*args, **kwargs):
                    raise AssertionError("非法原型不得创建 Agent 或决策会话")

                expected_error = LegacyFrontendContractError if invalid == "missing" else (RuntimeError, ValueError)
                with self.assertRaises(expected_error):
                    self.run_step(run_dir, state, agent_runner=unexpected, decision_runner=unexpected)
                self.assertEqual((run_dir / "state.json").read_bytes(), before)
                self.assertFalse((run_dir / "conversations").exists())
                self.assertFalse((run_dir / "steps/06.json").exists())
        self.capabilities.assert_not_called()

    def test_inapplicable_prototype_uses_reason_not_html_presence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, _ = self.make_run(Path(directory))
            intake_path = run_dir / "steps/02.json"
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            intake["prototype"] = {"applicable": False, "entry": None, "reason": "此产品无交互原型"}
            write_json(intake_path, intake)
            self.assertTrue((workspace / "docs/prototype/index.html").is_file())
            self.assertEqual(load_prototype(run_dir, workspace), intake["prototype"])

    def test_prototype_does_not_relax_two_document_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            intake_path = run_dir / "steps/02.json"
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            intake["outputs"].append("docs/prototype/index.html")
            write_json(intake_path, intake)
            with self.assertRaisesRegex(RuntimeError, "两份"):
                self.run_step(run_dir, state)
            self.capabilities.assert_not_called()

    def test_missing_frontend_capability_fails_before_agent_or_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            before = (run_dir / "state.json").read_bytes()
            self.capabilities.side_effect = RuntimeError("缺少 ui-ux-pro-max 插件")
            with self.assertRaisesRegex(RuntimeError, "ui-ux-pro-max"):
                self.run_step(run_dir, state)
            self.capabilities.assert_called_once_with(workspace.resolve())
            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            self.assertFalse((run_dir / "conversations").exists())

    def test_success_marker_is_strict_and_matches_frontend_applicability(self) -> None:
        cases = (
            (["frontend"], None, False),
            (["frontend"], 1, False),
            (["frontend"], False, False),
            (["frontend"], True, True),
            (["backend"], True, False),
            (["backend"], False, True),
            ([], False, True),
        )
        for outputs, marker, accepted in cases:
            with self.subTest(outputs=outputs, marker=marker), tempfile.TemporaryDirectory() as directory:
                run_dir = Path(directory)
                (run_dir / "steps").mkdir()
                payload = {
                    "step": 6,
                    "status": "success",
                    "applicable": bool(outputs),
                    "outputs": outputs,
                }
                if marker is not None:
                    payload["tailwind_theme"] = marker
                write_json(run_dir / "steps/06.json", payload)
                if accepted:
                    self.assertEqual(
                        verify_existing_bootstrap_success(run_dir, outputs), payload
                    )
                else:
                    with self.assertRaisesRegex(RuntimeError, "不可复用"):
                        verify_existing_bootstrap_success(run_dir, outputs)

    def test_no_applicable_foundation_skips_without_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, state = self.make_run(Path(directory), applicable=False)

            async def unexpected(*args, **kwargs):
                raise AssertionError("无适用工程不应调用 Agent 或决策模型")

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=unexpected,
                decision_runner=unexpected,
            )
            self.assertEqual(outcome["status"], "success")
            self.assertFalse(outcome["applicable"])
            self.assertEqual(outcome["outputs"], [])
            self.assertIs(outcome["tailwind_theme"], False)
            self.capabilities.assert_not_called()

    def test_cli_requires_run_id_and_handles_corrupt_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo_root = Path(directory)
            script = f"""
from pathlib import Path
import run_step
run_step.DEMO_ROOT = Path({directory!r})
raise SystemExit(run_step.retrying_main())
"""

            def execute(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-c", script, *args],
                    cwd=DEMO_ROOT,
                    text=True,
                    capture_output=True,
                )

            completed = execute("--step", "6")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("第 6 步执行失败", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

            run_dir = demo_root / "runs" / "corrupt-step-six-test"
            (run_dir / "steps").mkdir(parents=True)
            state_path = run_dir / "state.json"
            state_path.write_text("{invalid", encoding="utf-8")
            before_state = state_path.read_bytes()
            result_path = run_dir / "steps/06.json"
            for existing in (False, True):
                with self.subTest(existing=existing):
                    if existing:
                        write_json(result_path, result("failed", "保留先前失败结果"))
                        before_result = result_path.read_bytes()
                    broken = execute("--step", "6", "--run-id", run_dir.name)
                    self.assertEqual(broken.returncode, 1)
                    self.assertIn("步骤 6 failed", broken.stderr)
                    self.assertNotIn("Traceback", broken.stderr)
                    self.assertEqual(state_path.read_bytes(), before_state)
                    if existing:
                        self.assertEqual(result_path.read_bytes(), before_result)
                    else:
                        self.assertFalse(result_path.exists())


if __name__ == "__main__":
    unittest.main()
