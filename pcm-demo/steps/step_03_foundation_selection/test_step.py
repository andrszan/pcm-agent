from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

DEMO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DEMO_ROOT))

from common.files import write_json
from common.state import read_state, write_state
from steps.step_03_foundation_selection.step import (
    FoundationSelectionDecision,
    FoundationSelectionInput,
    SYSTEM_PROMPT,
    TemplateCandidate,
    TemplateSelectionDecision,
    load_selection_input,
    run,
    select_foundations,
)

CATALOG = {
    "schema_version": 1,
    "repositories": {
        "web": {
            "git_url": "https://example.invalid/web.git",
            "default_branch": "main",
            "templates": [
                {
                    "id": "web-next",
                    "path": "templates/web-next",
                    "project_type": "frontend",
                    "name": "Next.js Web",
                    "description": "Web 基础工程",
                }
            ],
        },
        "api": {
            "git_url": "https://example.invalid/api.git",
            "default_branch": "main",
            "templates": [
                {
                    "id": "api-fastapi",
                    "path": "templates/api-fastapi",
                    "project_type": "backend",
                    "name": "FastAPI API",
                    "description": "API 基础工程",
                    "applicability": "仅在产品明确要求 Python 后端时适用。",
                }
            ],
        },
    },
}


class FoundationSelectionTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, dict, Path]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace = root / "workspace"
        requirements = workspace / "docs" / "requirements"
        requirements.mkdir(parents=True)
        (requirements / "项目需求说明.md").write_text("需要 Web 和 API。", encoding="utf-8")
        (requirements / "产品功能说明.md").write_text(
            "用户通过浏览器完成任务。", encoding="utf-8"
        )
        write_json(
            run_dir / "steps" / "02.json",
            {
                "step": 2,
                "status": "success",
                "outputs": [
                    "docs/requirements/项目需求说明.md",
                    "docs/requirements/产品功能说明.md",
                ],
            },
        )
        state = {
            "run_id": "test-run",
            "status": "success",
            "current_step": 2,
            "workspace": {"final_path": str(workspace)},
        }
        write_state(run_dir, state)
        catalog_path = root / "catalog.json"
        catalog_path.write_text(json.dumps(CATALOG, ensure_ascii=False), encoding="utf-8")
        return run_dir, state, catalog_path

    def selection(self) -> FoundationSelectionDecision:
        return FoundationSelectionDecision(
            frontend=TemplateSelectionDecision(
                candidate_id="web-next",
                reason="产品需要浏览器界面。",
            ),
            backend=TemplateSelectionDecision(
                candidate_id="api-fastapi",
                reason="产品需要业务 API。",
            ),
        )

    def saved_result(self) -> dict[str, object]:
        return {
            "step": 3,
            "name": "基础工程选型",
            "status": "success",
            "summary": "基础工程模板选择已完成。",
            "applicable": True,
            "outputs": [],
            "blocked": None,
            "error": None,
            "template_selection": {
                "frontend": {
                    "id": "web-next",
                    "git_url": "https://example.invalid/web.git",
                    "default_branch": "main",
                    "path": "templates/web-next",
                    "reason": "产品需要浏览器界面。",
                },
                "backend": {
                    "id": "api-fastapi",
                    "git_url": "https://example.invalid/api.git",
                    "default_branch": "main",
                    "path": "templates/api-fastapi",
                    "reason": "产品需要业务 API。",
                },
            },
        }

    def test_loads_pydantic_input_from_products_and_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, state, catalog_path = self.make_run(Path(directory))
            selection_input = load_selection_input(run_dir, state, catalog_path)
            self.assertIsInstance(selection_input, FoundationSelectionInput)
            self.assertEqual(selection_input.frontend_candidates[0].id, "web-next")
            self.assertIsNone(selection_input.frontend_candidates[0].applicability)
            self.assertEqual(
                selection_input.backend_candidates[0].git_url,
                "https://example.invalid/api.git",
            )
            self.assertEqual(
                selection_input.backend_candidates[0].applicability,
                "仅在产品明确要求 Python 后端时适用。",
            )

    def test_uses_inline_system_prompt_and_pydantic_output(self) -> None:
        calls: list[dict] = []

        async def fake_runner(config, **kwargs):
            calls.append(kwargs)
            return self.selection()

        selection_input = FoundationSelectionInput(
            product_requirements="需要 Web 和 API。",
            product_features="用户通过浏览器完成任务。",
            frontend_candidates=[
                TemplateCandidate(
                    id="web-next",
                    git_url="https://example.invalid/web.git",
                    default_branch="main",
                    path="templates/web-next",
                    name="Next.js Web",
                    description="Web 基础工程",
                )
            ],
            backend_candidates=[
                TemplateCandidate(
                    id="api-fastapi",
                    git_url="https://example.invalid/api.git",
                    default_branch="main",
                    path="templates/api-fastapi",
                    name="FastAPI API",
                    description="API 基础工程",
                    applicability="仅在产品明确要求 Python 后端时适用。",
                )
            ],
        )
        result = asyncio.run(
            select_foundations(
                selection_input,
                SimpleNamespace(model="test-model"),
                model_runner=fake_runner,
            )
        )
        self.assertEqual(result.frontend.id, "web-next")
        self.assertEqual(result.frontend.git_url, "https://example.invalid/web.git")
        self.assertIs(calls[0]["input_model"], selection_input)
        self.assertEqual(
            calls[0]["input_model"].backend_candidates[0].applicability,
            "仅在产品明确要求 Python 后端时适用。",
        )
        self.assertIs(calls[0]["output_model"], FoundationSelectionDecision)
        self.assertEqual(
            set(FoundationSelectionDecision.model_fields), {"frontend", "backend"}
        )
        self.assertEqual(
            set(TemplateSelectionDecision.model_fields), {"candidate_id", "reason"}
        )
        self.assertNotIn("applicability", result.backend.model_dump())
        self.assertEqual(calls[0]["system_prompt"], SYSTEM_PROMPT)

    def test_rejects_unknown_and_duplicate_candidate_ids(self) -> None:
        candidate = TemplateCandidate(
            id="web-next",
            git_url="https://example.invalid/web.git",
            default_branch="main",
            path="templates/web-next",
            name="Next.js Web",
            description="Web 基础工程",
        )
        selection_input = FoundationSelectionInput(
            product_requirements="需要 Web。",
            product_features="用户通过浏览器完成任务。",
            frontend_candidates=[candidate],
            backend_candidates=[],
        )

        async def unknown_runner(config, **kwargs):
            return FoundationSelectionDecision(
                frontend=TemplateSelectionDecision(
                    candidate_id="unknown",
                    reason="错误候选。",
                ),
                backend=None,
            )

        with self.assertRaisesRegex(RuntimeError, "不存在的前端候选模板"):
            asyncio.run(
                select_foundations(
                    selection_input,
                    SimpleNamespace(model="test-model"),
                    model_runner=unknown_runner,
                )
            )

        called = False

        async def unexpected_runner(config, **kwargs):
            nonlocal called
            called = True
            return FoundationSelectionDecision(frontend=None, backend=None)

        duplicate_input = selection_input.model_copy(
            update={"frontend_candidates": [candidate, candidate.model_copy()]}
        )
        with self.assertRaisesRegex(RuntimeError, "前端候选模板 ID 不唯一"):
            asyncio.run(
                select_foundations(
                    duplicate_input,
                    SimpleNamespace(model="test-model"),
                    model_runner=unexpected_runner,
                )
            )
        self.assertFalse(called)

    def test_run_saves_parsed_result_and_advances_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, state, catalog_path = self.make_run(Path(directory))

            async def fake_runner(config, **kwargs):
                return self.selection()

            result = asyncio.run(
                run(
                    run_dir,
                    state,
                    catalog_loader=lambda _: (catalog_path, "cli"),
                    config_loader=lambda: SimpleNamespace(model="test-model"),
                    model_runner=fake_runner,
                )
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["template_selection"]["frontend"]["id"], "web-next")
            saved_state = read_state(run_dir)
            self.assertEqual(
                (
                    saved_state["phase"],
                    saved_state["step"],
                    saved_state["current_step"],
                    saved_state["current_node"],
                ),
                ("project_initialization", 4, 4, "project:04_assemble_foundation"),
            )
            saved = json.loads((run_dir / "steps" / "03.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, result)

    def test_api_failure_is_saved_without_leaking_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, state, catalog_path = self.make_run(Path(directory))

            async def failing_runner(config, **kwargs):
                raise RuntimeError("api_key=super-secret")

            result = asyncio.run(
                run(
                    run_dir,
                    state,
                    catalog_loader=lambda _: (catalog_path, "cli"),
                    config_loader=lambda: SimpleNamespace(model="test-model"),
                    model_runner=failing_runner,
                )
            )
            self.assertEqual(result["status"], "failed")
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertNotIn("super-secret", serialized)
            self.assertEqual(result["error"]["message"], "api_key=[REDACTED]")
            self.assertEqual(result["error"]["diagnostic_path"], "logs/step-03-error.json")
            self.assertTrue((run_dir / "logs/step-03-error.json").is_file())
            saved_state = read_state(run_dir)
            self.assertEqual(
                (
                    saved_state["step"],
                    saved_state["current_step"],
                    saved_state["current_node"],
                ),
                (3, 3, "project:03_foundation_selection"),
            )

    def test_existing_success_advances_state_without_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, state, _catalog_path = self.make_run(Path(directory))
            existing = self.saved_result()
            write_json(run_dir / "steps/03.json", existing)

            async def unexpected_runner(*_args, **_kwargs):
                raise AssertionError("已有成功结果不应再次调用模型")

            outcome = asyncio.run(
                run(
                    run_dir,
                    state,
                    catalog_loader=lambda _: (_ for _ in ()).throw(
                        AssertionError("已有成功结果不应重新加载目录")
                    ),
                    model_runner=unexpected_runner,
                )
            )

            self.assertEqual(outcome, existing)
            saved = read_state(run_dir)
            self.assertEqual(
                (saved["step"], saved["current_step"], saved["current_node"]),
                (4, 4, "project:04_assemble_foundation"),
            )

    def test_advanced_state_is_not_downgraded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, state, catalog_path = self.make_run(Path(directory))
            state.update(
                {
                    "phase": "project_initialization",
                    "step": 5,
                    "current_step": 5,
                    "current_node": "project:05_verify_readiness",
                }
            )
            write_state(run_dir, state)
            before = (run_dir / "state.json").read_bytes()

            with self.assertRaisesRegex(RuntimeError, "第 3 步恢复锚点"):
                asyncio.run(run(run_dir, state, catalog_path=catalog_path))

            self.assertEqual((run_dir / "state.json").read_bytes(), before)
            self.assertFalse((run_dir / "steps/03.json").exists())


if __name__ == "__main__":
    unittest.main()
