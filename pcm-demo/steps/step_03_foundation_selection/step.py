from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from common.files import resolve_workspace_output
from common.openai_responses import parse_response
from common.state import write_state, write_step_result
from config import LLMConfig, load_template_catalog

STEP = 3
NAME = "基础工程选型"
NEXT_NODE = "project:04_assemble_foundation"
SYSTEM_PROMPT = """根据产品定义和候选模板，为产品选择适用的前端与后端基础工程。

每个选择必须来自对应候选列表，并原样返回候选中的 id、git_url、default_branch 和 path，同时给出简短选择理由。产品明确不需要某个交付面时，对应字段返回 null。不得发明候选、修改候选来源字段或输出候选列表之外的方案。"""


class PreviousStepResult(BaseModel):
    status: Literal["success"]
    outputs: list[str] = Field(min_length=2)


class CatalogTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    path: str
    project_type: Literal["frontend", "backend"]
    name: str
    description: str


class CatalogRepository(BaseModel):
    model_config = ConfigDict(extra="ignore")

    git_url: str
    default_branch: str
    templates: list[CatalogTemplate]


class TemplateCatalog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal[1]
    repositories: dict[str, CatalogRepository]


class TemplateCandidate(BaseModel):
    id: str
    git_url: str
    default_branch: str
    path: str
    name: str
    description: str


class FoundationSelectionInput(BaseModel):
    product_requirements: str
    product_features: str
    frontend_candidates: list[TemplateCandidate]
    backend_candidates: list[TemplateCandidate]


class TemplateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    git_url: str
    default_branch: str
    path: str
    reason: str


class FoundationSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frontend: TemplateSelection | None
    backend: TemplateSelection | None


def load_selection_input(
    run_dir: Path, state: dict[str, Any], catalog_path: Path
) -> FoundationSelectionInput:
    workspace = Path(state["workspace"]["final_path"]).resolve()
    previous = PreviousStepResult.model_validate_json(
        (run_dir / "steps" / "02.json").read_text(encoding="utf-8")
    )
    documents = {
        Path(output).name: resolve_workspace_output(workspace, output).read_text(
            encoding="utf-8"
        )
        for output in previous.outputs
    }
    catalog = TemplateCatalog.model_validate_json(catalog_path.read_text(encoding="utf-8"))
    candidates: dict[str, list[TemplateCandidate]] = {"frontend": [], "backend": []}
    for repository in catalog.repositories.values():
        for template in repository.templates:
            candidates[template.project_type].append(
                TemplateCandidate(
                    id=template.id,
                    git_url=repository.git_url,
                    default_branch=repository.default_branch,
                    path=template.path,
                    name=template.name,
                    description=template.description,
                )
            )
    return FoundationSelectionInput(
        product_requirements=documents["项目需求说明.md"],
        product_features=documents["产品功能说明.md"],
        frontend_candidates=candidates["frontend"],
        backend_candidates=candidates["backend"],
    )


async def select_foundations(
    selection_input: FoundationSelectionInput,
    config: LLMConfig,
    *,
    model_runner=parse_response,
) -> FoundationSelectionResult:
    return await model_runner(
        config,
        system_prompt=SYSTEM_PROMPT,
        input_model=selection_input,
        output_model=FoundationSelectionResult,
        max_output_tokens=1024,
        max_retries=0,
    )


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    catalog_path: Path | None = None,
    catalog_loader=load_template_catalog,
    config_loader=LLMConfig.load,
    model_runner=parse_response,
) -> dict[str, Any]:
    result_path = run_dir / "steps" / "03.json"
    if state.get("current_step") == 4 and result_path.is_file():
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        if existing.get("status") == "success":
            return existing

    state.update({"status": "running", "current_step": STEP, "blocked": None, "error": None})
    write_state(run_dir, state)
    try:
        resolved_catalog, _ = catalog_loader(catalog_path)
        selection_input = load_selection_input(run_dir, state, resolved_catalog)
        selection = await select_foundations(
            selection_input,
            config_loader(),
            model_runner=model_runner,
        )
        template_selection = selection.model_dump(mode="json")
        result = {
            "step": STEP,
            "name": NAME,
            "status": "success",
            "summary": "基础工程模板选择已完成。",
            "applicable": selection.frontend is not None or selection.backend is not None,
            "outputs": [],
            "blocked": None,
            "error": None,
            "template_selection": template_selection,
        }
        write_step_result(run_dir, STEP, result)
        state.update(
            {
                "status": "success",
                "phase": "project_initialization",
                "current_node": NEXT_NODE,
                "step": 4,
                "current_step": 4,
                "blocked": None,
                "error": None,
            }
        )
        write_state(run_dir, state)
        return result
    except Exception as error:  # noqa: BLE001 - 步骤入口统一保存脱敏失败结果。
        result = {
            "step": STEP,
            "name": NAME,
            "status": "failed",
            "summary": "基础工程模板选择失败。",
            "applicable": True,
            "outputs": [],
            "blocked": None,
            "error": {
                "type": type(error).__name__,
                "message": "基础工程模板选择未完成。",
            },
            "template_selection": None,
        }
        write_step_result(run_dir, STEP, result)
        state.update(
            {
                "status": "failed",
                "current_step": STEP,
                "blocked": None,
                "error": result["error"],
            }
        )
        write_state(run_dir, state)
        return result
