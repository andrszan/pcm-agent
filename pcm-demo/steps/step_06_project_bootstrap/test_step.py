from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.files import write_json
from common.state import read_state, write_state
from steps.step_01_create_workspace import initialize_root_repository
from steps.step_03_foundation_selection.step import TemplateSelection
from steps.step_05_project_readiness.step import (
    readiness_baseline,
    result as readiness_result,
)
from steps.step_06_project_bootstrap.step import (
    COVERAGE_ARTIFACT_REPAIR_PROMPT,
    CURRENT_NODE,
    DECISION_LOOP_SPEC,
    LEGACY_COMPLETION_MESSAGES,
    NEXT_NODE,
    PROJECT_BOOTSTRAP_MAX_TURNS,
    README_REPAIR_PROMPT,
    TAILWIND_THEME_DECISION_LOOP_SPEC,
    TAILWIND_THEME_MAX_TURNS,
    ProjectBootstrapBlocked,
    result,
    run,
    tailwind_theme_initial_prompt,
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
    is_theme = prompt.startswith("/tailwind-theme\n")
    return agent_result(
        cwd=cwd,
        session="session-theme" if is_theme else "session-bootstrap",
        text=text or ("主题完整回复" if is_theme else "项目化完整回复"),
        skills=["tailwind-theme"] if is_theme else ["project-bootstrap"],
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
        for output in (requirements, features, checklist):
            (workspace / output).write_text(f"# {Path(output).stem}\n", encoding="utf-8")

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

        write_json(
            run_dir / "steps/02.json",
            {"step": 2, "status": "success", "outputs": [requirements, features]},
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

            outcome = self.run_step(
                run_dir,
                state,
                agent_runner=fake_agent,
                decision_runner=completed,
                config_loader=lambda: object(),
            )
            self.assertEqual(outcome["outputs"], ["frontend"])
            self.assertIs(outcome["tailwind_theme"], True)
            self.assertEqual(len(calls), 3)
            self.assertIsNone(calls[0]["resume_session_id"])
            self.assertEqual(calls[1]["resume_session_id"], "session-bootstrap")
            self.assertEqual(calls[1]["prompt"], README_REPAIR_PROMPT)
            self.assertIsNone(calls[2]["resume_session_id"])
            self.assertEqual(TAILWIND_THEME_MAX_TURNS, 9999)
            self.assertEqual(calls[2]["max_turns"], TAILWIND_THEME_MAX_TURNS)

            bootstrap_prompt = calls[0]["prompt"]
            self.assertTrue(bootstrap_prompt.startswith("/project-bootstrap\n"))
            self.assertIn("docs/requirements/项目需求说明.md", bootstrap_prompt)
            self.assertIn("@./frontend", bootstrap_prompt)
            self.assertIn("产品根 README", bootstrap_prompt)
            self.assertIn("真实浏览器", bootstrap_prompt)
            self.assertIn("实际 `.env`", bootstrap_prompt)
            self.assertIn("@./.pcm/runtime.json", bootstrap_prompt)
            self.assertIn("不得自行递增、随机选择", bootstrap_prompt)
            self.assertIn("环境变量改名", bootstrap_prompt)
            self.assertIn("配置结构迁移", bootstrap_prompt)
            self.assertIn("同一既有资源绑定和真实值", bootstrap_prompt)
            self.assertIn("资源身份、endpoint 与权限范围", bootstrap_prompt)
            self.assertIn("不得重新选择、创建、派生、轮换或替换", bootstrap_prompt)
            self.assertIn("工程接线无法继续修复", bootstrap_prompt)
            self.assertIn("不得修改权威产品定义或项目准备清单", bootstrap_prompt)
            self.assertIn("不得初始化、暂存、提交", bootstrap_prompt)
            self.assertIn("不要选择或生成项目专属主题配色", bootstrap_prompt)
            for forbidden in ("git_url", "origin", "第 6 步", "PCM", "节点", "阶段", "调用Skill"):
                self.assertNotIn(forbidden, bootstrap_prompt)
            self.assertEqual(calls[0]["max_turns"], PROJECT_BOOTSTRAP_MAX_TURNS)
            self.assertNotIn("max_budget_usd", calls[0])

            theme_prompt = calls[2]["prompt"]
            self.assertEqual(theme_prompt, tailwind_theme_initial_prompt([
                "docs/requirements/项目需求说明.md",
                "docs/requirements/产品功能说明.md",
            ]))
            self.assertTrue(theme_prompt.startswith("/tailwind-theme\n"))
            for required in (
                "Tailwind CSS v4 CSS-first",
                "@./frontend",
                "完整 light/dark",
                "tweakcn",
                "不得修改字体",
                "真实浏览器",
                "不得初始化、暂存、提交",
            ):
                self.assertIn(required, theme_prompt)
            for forbidden in ("git_url", "origin", "第 6 步", "PCM", "节点", "阶段", "session"):
                self.assertNotIn(forbidden, theme_prompt)

            self.assertEqual(len(system_prompts), 3)
            for system_prompt in system_prompts:
                for tag in ("role", "project_context", "responsibility", "completion", "output"):
                    self.assertIn(f"<{tag}>", system_prompt)
                    self.assertIn(f"</{tag}>", system_prompt)
                self.assertNotIn("file:///templates.git", system_prompt)
                self.assertNotIn("git_url", system_prompt)
                self.assertNotIn("origin", system_prompt)
            for bootstrap_system_prompt in system_prompts[:2]:
                for required in (
                    "产品根 README 和各适用工程的项目身份",
                    "已完成的项目准备基线",
                    "配置迁移与既有资源边界",
                    "不把模板默认主题认定为项目专属主题",
                ):
                    self.assertIn(required, bootstrap_system_prompt)
                self.assertNotEqual(
                    bootstrap_system_prompt, DECISION_LOOP_SPEC.decision_system_prompt
                )
            theme_system_prompt = system_prompts[2]
            for required in (
                "Tailwind CSS v4 CSS-first",
                "完整落实并验证项目专属 light/dark",
                "tweakcn 网络不可用必须回退到自定义配色",
                '"frontend"',
            ):
                self.assertIn(required, theme_system_prompt)
            self.assertNotEqual(
                theme_system_prompt,
                TAILWIND_THEME_DECISION_LOOP_SPEC.decision_system_prompt,
            )

            saved = read_state(run_dir)
            self.assertEqual((saved["step"], saved["current_node"]), (7, NEXT_NODE))
            self.assertEqual(
                saved["claude_sessions"],
                {
                    "project_bootstrap": "session-bootstrap",
                    "tailwind_theme": "session-theme",
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

            saved.pop("project_bootstrap", None)
            saved.pop("tailwind_theme", None)
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
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[1]["resume_session_id"], "session-bootstrap")
            self.assertEqual(calls[1]["prompt"], COVERAGE_ARTIFACT_REPAIR_PROMPT)
            self.assertTrue(calls[2]["prompt"].startswith("/tailwind-theme\n"))

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

    def test_theme_blocked_resumes_theme_without_rerunning_bootstrap_agent(self) -> None:
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

            async def first_decision(messages, config, *, system_prompt):
                if "项目专属 light/dark" in system_prompt:
                    return decision(
                        "blocked",
                        reason="缺少不可替代的授权品牌资料",
                        required_inputs=["提供授权品牌资料"],
                    )
                return decision("completed")

            with self.assertRaises(ProjectBootstrapBlocked):
                self.run_step(
                    run_dir,
                    state,
                    agent_runner=first_agent,
                    decision_runner=first_decision,
                    config_loader=lambda: object(),
                )
            self.assertEqual(len(calls), 2)
            self.assertTrue(calls[0]["prompt"].startswith("/project-bootstrap\n"))
            self.assertTrue(calls[1]["prompt"].startswith("/tailwind-theme\n"))

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
                self.assertEqual(kwargs["resume_session_id"], "session-theme")
                current = agent_result(
                    cwd=kwargs["cwd"],  # type: ignore[arg-type, index]
                    session="session-theme",
                    text="主题恢复完成",
                    skills=["tailwind-theme"],
                )
                kwargs["on_update"](current)  # type: ignore[index, operator]
                return current

            async def resumed_decision(messages, config, *, system_prompt):
                self.assertIn("项目专属 light/dark", system_prompt)
                return decision("completed")

            outcome = self.run_step(
                run_dir,
                resumed_state,
                agent_runner=resumed_agent,
                decision_runner=resumed_decision,
                config_loader=lambda: object(),
            )
            self.assertIs(outcome["tailwind_theme"], True)
            self.assertEqual(len(resumed_calls), 1)
            self.assertFalse(resumed_calls[0]["prompt"].startswith("/project-bootstrap\n"))

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
            (run_dir / "state.json").write_text("{invalid", encoding="utf-8")
            broken = execute("--step", "6", "--run-id", run_dir.name)
            self.assertEqual(broken.returncode, 1)
            self.assertNotIn("Traceback", broken.stderr)
            saved = json.loads((run_dir / "steps/06.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "failed")
            self.assertIs(saved["tailwind_theme"], False)


if __name__ == "__main__":
    unittest.main()
