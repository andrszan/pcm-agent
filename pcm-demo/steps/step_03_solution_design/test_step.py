from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DEMO_ROOT))

from common.claude_agent import ClaudeRunResult
from common.state import read_state, write_state, write_step_result
from config import load_template_catalog_path
from run_step import main as run_step_main
from steps.step_03_solution_design.step import (
    OUTPUTS,
    SolutionDesignBlocked,
    normalize_template_selection,
    read_catalog,
    request_template_selection,
    result,
    run,
)

CATALOG = {
    "schema_version": 1,
    "repositories": {
        "frontend": {
            "git_url": "https://example.test/frontend.git",
            "default_branch": "main",
            "name": "frontend-templates",
            "description": "Frontend templates",
            "templates": [
                {
                    "id": "next-app",
                    "path": "templates/next-app",
                    "name": "Next.js App",
                    "description": "Next application",
                },
                {
                    "id": "vite-spa",
                    "path": "templates/vite-spa",
                    "name": "Vite SPA",
                    "description": "Vite single-page application",
                },
            ],
        },
        "python": {
            "git_url": "https://example.test/python.git",
            "default_branch": "main",
            "name": "python-templates",
            "description": "Python templates",
            "templates": [
                {
                    "id": "fastapi-api",
                    "path": "templates/fastapi-api",
                    "name": "FastAPI API",
                    "description": "FastAPI application",
                }
            ],
        },
    },
}


def selection_decision(
    *,
    action: str = "approve",
    frontend: dict | None = None,
    backend: dict | None = None,
    answer: str = "请明确报告合法的前后端模板。",
) -> dict:
    if action == "approve":
        frontend = frontend or {
            "repository_id": "frontend",
            "template_id": "next-app",
            "adoption": "direct",
            "evidence": "前端选择 frontend/next-app，采用直接继承。",
        }
        backend = backend or {
            "repository_id": "python",
            "template_id": "fastapi-api",
            "adoption": "trimmed",
            "evidence": "后端选择 python/fastapi-api，采用裁剪派生。",
        }
        return {
            "action": action,
            "frontend": frontend,
            "backend": backend,
        }
    return {
        "action": action,
        "frontend": None,
        "backend": None,
    }


def agent_result(
    *,
    session: str = "session-3",
    text: str = (
        "前端选择 frontend/next-app，采用直接继承。"
        "后端选择 python/fastapi-api，采用裁剪派生。"
    ),
    subtype: str = "success",
    is_error: bool = False,
    exception: str | None = None,
) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={"skills": ["solution-design"], "slash_commands": ["solution-design"]},
        text=text,
        result_subtype=subtype,
        is_error=is_error,
        session_id=session,
        stop_reason="end_turn",
        num_turns=1,
        total_cost_usd=0.1,
        exception=exception,
    )


class SolutionDesignTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        (run_dir / "logs").mkdir()
        workspace = root / "workspace"
        requirements = workspace / "docs/requirements"
        requirements.mkdir(parents=True)
        (requirements / "项目需求说明.md").write_text("# 项目需求\n", encoding="utf-8")
        (requirements / "产品功能说明.md").write_text("# 产品功能\n", encoding="utf-8")
        write_step_result(
            run_dir,
            2,
            {
                "step": 2,
                "name": "项目需求与产品定义",
                "status": "success",
                "summary": "完成",
                "applicable": True,
                "outputs": [
                    "docs/requirements/项目需求说明.md",
                    "docs/requirements/产品功能说明.md",
                ],
                "blocked": None,
                "error": None,
            },
        )
        catalog_path = root / "catalog.json"
        catalog_path.write_text(
            json.dumps(CATALOG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        state = {
            "run_id": "test",
            "status": "success",
            "current_step": 2,
            "workspace": {"final_path": str(workspace)},
        }
        write_state(run_dir, state)
        return run_dir, workspace, catalog_path, state

    def write_technical_output(self, workspace: Path) -> None:
        path = workspace / OUTPUTS[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 技术方案\n", encoding="utf-8")

    def test_catalog_is_required_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.json"
            with self.assertRaisesRegex(RuntimeError, "输入文件不存在"):
                read_catalog(missing)

            invalid = root / "invalid.json"
            invalid.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "不是合法 JSON"):
                read_catalog(invalid)

            malformed = root / "malformed.json"
            malformed.write_text(
                json.dumps({"schema_version": 1, "repositories": {}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "缺少 repositories"):
                read_catalog(malformed)

            wrong_version = root / "wrong-version.json"
            wrong_version.write_text(
                json.dumps({"schema_version": True, "repositories": CATALOG["repositories"]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "schema_version"):
                read_catalog(wrong_version)

            target = root / "target.json"
            target.write_text(json.dumps(CATALOG), encoding="utf-8")
            link = root / "catalog-link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "符号链接"):
                run_dir, _, _, state = self.make_run(root)
                asyncio.run(run(run_dir, state, link))

    def test_catalog_config_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "PCM_TEMPLATE_CATALOG=/from-file/catalog.json\n", encoding="utf-8"
            )
            previous = os.environ.get("PCM_TEMPLATE_CATALOG")
            try:
                os.environ["PCM_TEMPLATE_CATALOG"] = "/from-env/catalog.json"
                value, source = load_template_catalog_path(env_file=env_file)
                self.assertEqual(value, Path("/from-env/catalog.json"))
                self.assertEqual(source, "environment")
                value, source = load_template_catalog_path(
                    Path("~/from-cli/catalog.json"), env_file=env_file
                )
                self.assertEqual(value, Path.home() / "from-cli/catalog.json")
                self.assertEqual(source, "cli")
            finally:
                if previous is None:
                    os.environ.pop("PCM_TEMPLATE_CATALOG", None)
                else:
                    os.environ["PCM_TEMPLATE_CATALOG"] = previous

    def test_normalize_selection_uses_catalog_and_target_paths(self) -> None:
        normalized = normalize_template_selection(
            selection_decision(), CATALOG
        )
        self.assertEqual(normalized["frontend"]["target_path"], "frontend")
        self.assertEqual(normalized["backend"]["target_path"], "backend")
        self.assertEqual(normalized["backend"]["repository_id"], "python")
        self.assertEqual(
            normalized["backend"]["git_url"],
            "https://example.test/python.git",
        )
        self.assertEqual(normalized["frontend"]["template_path"], "templates/next-app")

    def test_invalid_repository_template_reference_is_rejected(self) -> None:
        decision = selection_decision(
            backend={
                "repository_id": "frontend",
                "template_id": "fastapi-api",
                "adoption": "direct",
            }
        )
        with self.assertRaisesRegex(ValueError, "不属于仓库 frontend"):
            normalize_template_selection(decision, CATALOG)

    def test_success_writes_selection_into_step_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, catalog_path, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs):
                calls.append({"prompt": prompt, **kwargs})
                current = agent_result()
                kwargs["on_update"](current)
                self.write_technical_output(workspace)
                return current

            async def fake_selection(text, catalog, config):
                self.assertIn("next-app", text)
                self.assertEqual(catalog, CATALOG)
                return selection_decision(), 1, json.dumps(
                    selection_decision(), ensure_ascii=False
                )

            with patch(
                "steps.step_03_solution_design.step.LLMConfig.load",
                return_value=object(),
            ):
                outcome = asyncio.run(
                    run(
                        run_dir,
                        state,
                        catalog_path,
                        agent_runner=fake_agent,
                        selection_runner=fake_selection,
                    )
                )

            self.assertEqual(outcome["status"], "success")
            self.assertEqual(outcome["outputs"], ["docs/design/技术方案.md"])
            self.assertEqual(outcome["template_selection"]["backend"]["repository_id"], "python")
            write_step_result(run_dir, 3, outcome)
            self.assertFalse((workspace / "docs/design/基础工程来源.json").exists())
            saved = json.loads((run_dir / "steps/03.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["template_selection"], outcome["template_selection"])
            saved_state = read_state(run_dir)
            self.assertEqual(saved_state["solution_design"]["catalog"]["schema_version"], 1)
            self.assertEqual(len(calls), 1)

    def test_selection_continue_resumes_same_agent_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, catalog_path, state = self.make_run(Path(directory))
            calls: list[dict] = []
            decisions = iter(
                [
                    selection_decision(
                        action="continue",
                        answer="请明确报告后端 repository_id、template_id 和采用方式。",
                    ),
                    selection_decision(),
                ]
            )

            async def fake_agent(prompt: str, **kwargs):
                calls.append({"prompt": prompt, **kwargs})
                current = agent_result(
                    text="前端选择 next-app，后端选择 fastapi-api。"
                )
                kwargs["on_update"](current)
                self.write_technical_output(workspace)
                return current

            async def fake_selection(text, catalog, config):
                decision = next(decisions)
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with patch(
                "steps.step_03_solution_design.step.LLMConfig.load",
                return_value=object(),
            ):
                outcome = asyncio.run(
                    run(
                        run_dir,
                        state,
                        catalog_path,
                        agent_runner=fake_agent,
                        selection_runner=fake_selection,
                    )
                )

            self.assertEqual(outcome["status"], "success")
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["resume_session_id"], "session-3")
            self.assertIn("只报告已经明确决定", calls[1]["prompt"])

    def test_blocked_selection_stops_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, catalog_path, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs):
                current = agent_result()
                kwargs["on_update"](current)
                self.write_technical_output(workspace)
                return current

            async def fake_selection(text, catalog, config):
                decision = selection_decision(action="blocked")
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with patch(
                "steps.step_03_solution_design.step.LLMConfig.load",
                return_value=object(),
            ), self.assertRaises(SolutionDesignBlocked) as raised:
                asyncio.run(
                    run(
                        run_dir,
                        state,
                        catalog_path,
                        agent_runner=fake_agent,
                        selection_runner=fake_selection,
                    )
                )
            self.assertEqual(raised.exception.required_inputs, ["SOLUTION_DESIGN_EXTERNAL_INPUT"])

    def test_incomplete_agent_result_uses_existing_decision_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, catalog_path, state = self.make_run(Path(directory))
            calls: list[dict] = []

            async def fake_agent(prompt: str, **kwargs):
                calls.append({"prompt": prompt, **kwargs})
                current = agent_result(
                    subtype="error_max_budget_usd",
                    is_error=True,
                    exception="budget",
                )
                kwargs["on_update"](current)
                return current

            async def fake_decision(messages, config):
                decision = {
                    "action": "continue",
                    "answer": "继续完成技术方案。",
                    "reason": "预算中断后恢复同一 session。",
                    "required_inputs": [],
                }
                return decision, 1, json.dumps(decision, ensure_ascii=False)

            with (
                patch(
                    "steps.step_03_solution_design.step.LLMConfig.load",
                    return_value=object(),
                ),
                self.assertRaisesRegex(RuntimeError, "达到上限"),
            ):
                asyncio.run(
                    run(
                        run_dir,
                        state,
                        catalog_path,
                        agent_runner=fake_agent,
                        decision_runner=fake_decision,
                    )
                )
            self.assertGreater(len(calls), 1)
            self.assertEqual(calls[1]["resume_session_id"], "session-3")

    def test_skill_must_be_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, catalog_path, state = self.make_run(Path(directory))

            async def fake_agent(prompt: str, **kwargs):
                return ClaudeRunResult(
                    init={"skills": [], "slash_commands": []},
                    text="",
                    result_subtype="success",
                    is_error=False,
                    session_id="session-3",
                    stop_reason="end_turn",
                    num_turns=1,
                    total_cost_usd=0.1,
                    exception=None,
                )

            with self.assertRaisesRegex(RuntimeError, "未加载 solution-design Skill"):
                asyncio.run(run(run_dir, state, catalog_path, agent_runner=fake_agent))

    def test_existing_success_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, catalog_path, state = self.make_run(Path(directory))
            self.write_technical_output(workspace)
            catalog, _ = read_catalog(catalog_path)
            selection = normalize_template_selection(selection_decision(), catalog)
            write_step_result(
                run_dir,
                3,
                result(
                    "success",
                    "完成",
                    outputs=["docs/design/技术方案.md"],
                    template_selection=selection,
                ),
            )
            state.update(
                {
                    "status": "success",
                    "current_step": 3,
                    "solution_design": {
                        "catalog": {
                            "path": str(catalog_path.resolve()),
                            "source": "argument",
                            "sha256": __import__("hashlib").sha256(
                                catalog_path.read_bytes()
                            ).hexdigest(),
                            "schema_version": 1,
                        },
                        "last_agent_result": {
                            "subtype": "success",
                            "is_error": False,
                        },
                    },
                }
            )
            write_state(run_dir, state)

            async def unexpected_agent(*args, **kwargs):
                raise AssertionError("幂等成功不应再次调用 Agent")

            async def unexpected_selection(*args, **kwargs):
                raise AssertionError("幂等成功不应再次调用 Responses")

            outcome = asyncio.run(
                run(
                    run_dir,
                    state,
                    catalog_path,
                    agent_runner=unexpected_agent,
                    selection_runner=unexpected_selection,
                )
            )
            self.assertEqual(outcome["status"], "success")
            self.assertEqual(outcome["template_selection"], selection)

    def test_malformed_catalog_identity_blocks_session_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, catalog_path, state = self.make_run(Path(directory))
            state["solution_design"] = {"catalog": {}}
            state["claude_sessions"] = {"solution_design": "session-3"}
            write_state(run_dir, state)
            with self.assertRaisesRegex(RuntimeError, "catalog 与已有运行记录不一致"):
                asyncio.run(run(run_dir, state, catalog_path))

    def test_catalog_change_does_not_reuse_old_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, catalog_path, state = self.make_run(Path(directory))
            self.write_technical_output(workspace)
            catalog, _ = read_catalog(catalog_path)
            selection = normalize_template_selection(selection_decision(), catalog)
            write_step_result(
                run_dir,
                3,
                result(
                    "success",
                    "完成",
                    outputs=["docs/design/技术方案.md"],
                    template_selection=selection,
                ),
            )
            state.update(
                {
                    "status": "success",
                    "current_step": 3,
                    "solution_design": {
                        "catalog": {
                            "path": str(catalog_path.resolve()),
                            "source": "argument",
                            "sha256": "old",
                            "schema_version": 1,
                        },
                        "last_agent_result": {
                            "subtype": "success",
                            "is_error": False,
                        },
                    },
                }
            )
            write_state(run_dir, state)
            with self.assertRaisesRegex(RuntimeError, "不一致"):
                asyncio.run(run(run_dir, state, catalog_path))

    def test_cli_accepts_catalog_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, catalog_path, state = self.make_run(Path(directory))
            expected = result("success", "完成")
            args = Namespace(
                step=3,
                product_draft=None,
                workspace_root=None,
                catalog_path=catalog_path,
                run_id="test",
            )
            with (
                patch("run_step.parse_args", return_value=args),
                patch("run_step.run_dir_for", return_value=run_dir),
                patch("run_step.read_state", return_value=state),
                patch("run_step.run_solution_design", return_value=expected) as mocked,
            ):
                exit_code = run_step_main()
            self.assertEqual(exit_code, 0)
            self.assertEqual(mocked.call_args.args[2], catalog_path.absolute())

    def test_selection_request_rejects_fabricated_evidence(self) -> None:
        async def fake_request(config, **kwargs):
            return json.dumps(selection_decision(), ensure_ascii=False)

        with patch(
            "steps.step_03_solution_design.step.request_json_response",
            side_effect=fake_request,
        ), self.assertRaisesRegex(ValueError, "持续无效"):
            asyncio.run(
                request_template_selection("Agent 尚未完成任何模板选择。", CATALOG, object())
            )

    def test_selection_request_uses_agent_text_and_catalog(self) -> None:
        responses: list[dict] = []

        async def fake_request(config, **kwargs):
            responses.append(kwargs)
            return json.dumps(
                selection_decision(
                    frontend={
                        "repository_id": "frontend",
                        "template_id": "next-app",
                        "adoption": "direct",
                        "evidence": "前端选择 frontend/next-app，采用直接继承",
                    },
                    backend={
                        "repository_id": "python",
                        "template_id": "fastapi-api",
                        "adoption": "trimmed",
                        "evidence": "后端选择 python/fastapi-api，采用裁剪派生",
                    },
                ),
                ensure_ascii=False,
            )

        with patch(
            "steps.step_03_solution_design.step.request_json_response",
            side_effect=fake_request,
        ):
            decision, attempts, _ = asyncio.run(
                request_template_selection(
                    "Agent 的自然语言选择：前端选择 frontend/next-app，采用直接继承；"
                    "后端选择 python/fastapi-api，采用裁剪派生。",
                    CATALOG,
                    object(),
                )
            )
        self.assertEqual(decision["action"], "approve")
        self.assertEqual(attempts, 1)
        self.assertEqual(responses[0]["schema_name"], "pcm_template_selection")
        payload = json.loads(responses[0]["input_text"])
        self.assertEqual(payload["agent_result"], "Agent 的自然语言选择：前端选择 frontend/next-app，采用直接继承；后端选择 python/fastapi-api，采用裁剪派生。")
        self.assertEqual(payload["catalog"], CATALOG)


if __name__ == "__main__":
    unittest.main()
