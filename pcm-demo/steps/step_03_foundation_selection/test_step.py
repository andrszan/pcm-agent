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
    FoundationSelectionInput,
    FoundationSelectionResult,
    SYSTEM_PROMPT,
    TemplateSelection,
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

    def selection(self) -> FoundationSelectionResult:
        return FoundationSelectionResult(
            frontend=TemplateSelection(
                id="web-next",
                git_url="https://example.invalid/web.git",
                default_branch="main",
                path="templates/web-next",
                reason="产品需要浏览器界面。",
            ),
            backend=TemplateSelection(
                id="api-fastapi",
                git_url="https://example.invalid/api.git",
                default_branch="main",
                path="templates/api-fastapi",
                reason="产品需要业务 API。",
            ),
        )

    def test_loads_pydantic_input_from_products_and_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, state, catalog_path = self.make_run(Path(directory))
            selection_input = load_selection_input(run_dir, state, catalog_path)
            self.assertIsInstance(selection_input, FoundationSelectionInput)
            self.assertEqual(selection_input.frontend_candidates[0].id, "web-next")
            self.assertEqual(
                selection_input.backend_candidates[0].git_url,
                "https://example.invalid/api.git",
            )

    def test_uses_inline_system_prompt_and_pydantic_output(self) -> None:
        calls: list[dict] = []

        async def fake_runner(config, **kwargs):
            calls.append(kwargs)
            return self.selection()

        selection_input = FoundationSelectionInput(
            product_requirements="需要 Web 和 API。",
            product_features="用户通过浏览器完成任务。",
            frontend_candidates=[],
            backend_candidates=[],
        )
        result = asyncio.run(
            select_foundations(
                selection_input,
                SimpleNamespace(model="test-model"),
                model_runner=fake_runner,
            )
        )
        self.assertEqual(result.frontend.id, "web-next")
        self.assertIs(calls[0]["input_model"], selection_input)
        self.assertIs(calls[0]["output_model"], FoundationSelectionResult)
        self.assertEqual(calls[0]["system_prompt"], SYSTEM_PROMPT)
        for forbidden in ("PCM", "Skill", "第 3 步", "编排"):
            self.assertNotIn(forbidden, SYSTEM_PROMPT)

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
            self.assertEqual(read_state(run_dir)["current_step"], 4)
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
            self.assertEqual(read_state(run_dir)["current_step"], 3)


if __name__ == "__main__":
    unittest.main()
