from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from common.error_diagnostics import exception_projection, write_diagnostic
from common.files import resolve_workspace_output
from common.openai_responses import parse_response
from common.state import write_state, write_step_result
from config import LLMConfig, load_template_catalog

STEP = 3
NAME = "基础工程选型"
PHASE = "project_initialization"
CURRENT_NODE = "project:03_foundation_selection"
NEXT_NODE = "project:04_assemble_foundation"
SYSTEM_PROMPT = """<task>
根据产品定义和候选模板，为产品选择适用的前端与后端基础工程。
</task>

<selection_rules>
- 产品需求和产品功能是判断交付面的权威依据。
- frontend 只能从 frontend_candidates 中选择，backend 只能从 backend_candidates 中选择。
- 产品明确需要某个交付面时，为该交付面选择最匹配的一个候选。
- 产品明确不需要某个交付面时，对应结果返回 null。
- candidate_id 必须原样来自对应候选列表，不得发明、改写或跨交付面选择候选。
- reason 必须简短说明候选与产品需求的匹配关系，不得只复述候选名称。
</selection_rules>

<output>
只返回以下结构的严格 JSON 对象：

{
  "frontend": {
    "candidate_id": "frontend_candidates 中的候选 id",
    "reason": "选择该前端候选的简短理由"
  },
  "backend": {
    "candidate_id": "backend_candidates 中的候选 id",
    "reason": "选择该后端候选的简短理由"
  }
}

字段限制：
- frontend 和 backend 必须始终存在，每个字段只能是上述对象或 null。
- 非 null 对象只能包含 candidate_id 和 reason，两个字段都必须是非空字符串。
- candidate_id 必须与对应候选的 id 完全一致。
- 禁止增加、删除或重命名字段，不得返回候选的 git_url、default_branch、path、name 或 description。
- 首字符必须是 {，末字符必须是 }。字段名和字符串值必须使用双引号。
- 只返回 JSON 对象；不要返回 Markdown、代码围栏、YAML、注释、分析过程或 JSON 之外的任何文本。
</output>"""


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
    id: str = Field(min_length=1, description="候选模板的稳定标识。")
    git_url: str = Field(min_length=1, description="候选模板所属 Git 仓库地址。")
    default_branch: str = Field(min_length=1, description="候选模板仓库的默认分支。")
    path: str = Field(min_length=1, description="候选模板在仓库中的相对路径。")
    name: str = Field(min_length=1, description="候选模板名称。")
    description: str = Field(min_length=1, description="候选模板能力说明。")


class FoundationSelectionInput(BaseModel):
    product_requirements: str = Field(
        min_length=1,
        description="用于判断产品交付面的项目需求说明。",
    )
    product_features: str = Field(
        min_length=1,
        description="用于判断模板适配性的产品功能说明。",
    )
    frontend_candidates: list[TemplateCandidate] = Field(
        description="允许选择的全部前端基础工程候选。"
    )
    backend_candidates: list[TemplateCandidate] = Field(
        description="允许选择的全部后端基础工程候选。"
    )


class TemplateSelectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(
        min_length=1,
        description="原样引用对应候选列表中的 id。",
    )
    reason: str = Field(
        min_length=1,
        description="说明该候选与产品需求匹配关系的简短理由。",
    )

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("选择理由不能为空")
        return value


class FoundationSelectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frontend: TemplateSelectionDecision | None = Field(
        description="前端基础工程选择；产品明确不需要前端时为 null。"
    )
    backend: TemplateSelectionDecision | None = Field(
        description="后端基础工程选择；产品明确不需要后端时为 null。"
    )


class TemplateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    git_url: str = Field(min_length=1)
    default_branch: str = Field(min_length=1)
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class FoundationSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frontend: TemplateSelection | None
    backend: TemplateSelection | None


def result(
    status: str,
    summary: str,
    *,
    template_selection: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selection = (
        FoundationSelectionResult.model_validate(template_selection)
        if template_selection is not None
        else None
    )
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": (
            bool(selection.frontend is not None or selection.backend is not None)
            if status == "success" and selection is not None
            else True
        ),
        "outputs": [],
        "blocked": None,
        "error": error,
        "template_selection": template_selection,
    }


def verify_existing_success(result_path: Path) -> dict[str, Any]:
    try:
        existing = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 3 步成功结果不可读取") from error
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
        "template_selection",
    }
    if (
        not isinstance(existing, dict)
        or set(existing) != expected_keys
        or existing.get("step") != STEP
        or existing.get("name") != NAME
        or existing.get("status") != "success"
        or not isinstance(existing.get("summary"), str)
        or not existing["summary"].strip()
        or existing.get("outputs") != []
        or existing.get("blocked") is not None
        or existing.get("error") is not None
        or not isinstance(existing.get("template_selection"), dict)
    ):
        raise RuntimeError("第 3 步成功结果不可复用")
    try:
        selection = FoundationSelectionResult.model_validate(existing["template_selection"])
    except ValidationError as error:
        raise RuntimeError("第 3 步成功结果模板选择无效") from error
    applicable = selection.frontend is not None or selection.backend is not None
    if existing.get("applicable") is not applicable:
        raise RuntimeError("第 3 步成功结果适用性不一致")
    return existing


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


def _is_legacy_current(state: dict[str, Any]) -> bool:
    if state.get("phase") is not None or state.get("step") is not None or state.get("current_node") is not None:
        return False
    current_step = state.get("current_step")
    if current_step == STEP - 1:
        return state.get("status") == "success"
    return current_step == STEP and state.get("status") in {"running", "failed", "blocked"}


def _advance_state(state: dict[str, Any]) -> None:
    state.update(
        {
            "status": "success",
            "phase": PHASE,
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "blocked": None,
            "error": None,
        }
    )


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


def _candidate_index(
    candidates: list[TemplateCandidate], delivery: str
) -> dict[str, TemplateCandidate]:
    index: dict[str, TemplateCandidate] = {}
    for candidate in candidates:
        if candidate.id in index:
            raise RuntimeError(f"{delivery}候选模板 ID 不唯一")
        index[candidate.id] = candidate
    return index


def _resolve_selection(
    decision: TemplateSelectionDecision | None,
    candidates: dict[str, TemplateCandidate],
    delivery: str,
) -> TemplateSelection | None:
    if decision is None:
        return None
    candidate = candidates.get(decision.candidate_id)
    if candidate is None:
        raise RuntimeError(f"模型选择了不存在的{delivery}候选模板")
    return TemplateSelection(
        id=candidate.id,
        git_url=candidate.git_url,
        default_branch=candidate.default_branch,
        path=candidate.path,
        reason=decision.reason,
    )


async def select_foundations(
    selection_input: FoundationSelectionInput,
    config: LLMConfig,
    *,
    model_runner=parse_response,
) -> FoundationSelectionResult:
    frontend_candidates = _candidate_index(
        selection_input.frontend_candidates, "前端"
    )
    backend_candidates = _candidate_index(
        selection_input.backend_candidates, "后端"
    )
    decision = await model_runner(
        config,
        system_prompt=SYSTEM_PROMPT,
        input_model=selection_input,
        output_model=FoundationSelectionDecision,
        max_retries=0,
    )
    return FoundationSelectionResult(
        frontend=_resolve_selection(
            decision.frontend,
            frontend_candidates,
            "前端",
        ),
        backend=_resolve_selection(
            decision.backend,
            backend_candidates,
            "后端",
        ),
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
    position = _position(state)
    current = state.get("phase") == PHASE and position == (STEP, STEP, CURRENT_NODE)
    advanced = state.get("phase") == PHASE and position == (STEP + 1, STEP + 1, NEXT_NODE)
    legacy_current = _is_legacy_current(state)

    if advanced:
        return verify_existing_success(result_path)
    if not current and not legacy_current:
        raise RuntimeError("运行状态不位于第 3 步恢复锚点")
    if result_path.is_file():
        try:
            existing = verify_existing_success(result_path)
        except RuntimeError:
            existing = None
        if existing is not None:
            _advance_state(state)
            write_state(run_dir, state)
            return existing

    state.update(
        {
            "status": "running",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "blocked": None,
            "error": None,
        }
    )
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
        completed = result(
            "success",
            "基础工程模板选择已完成。",
            template_selection=template_selection,
        )
        write_step_result(run_dir, STEP, completed)
        _advance_state(state)
        write_state(run_dir, state)
        return completed
    except Exception as error:  # noqa: BLE001 - 步骤入口统一保存脱敏失败结果。
        diagnostic_path = write_diagnostic(
            run_dir,
            "step-03-error.json",
            source="foundation_selection",
            kind="response",
            context={"step": STEP, "component": "foundation_selection", "operation": "select_foundations"},
            error=error,
        )
        failed = result(
            "failed",
            "基础工程模板选择失败。",
            error=exception_projection(error, diagnostic_path=diagnostic_path),
        )
        write_step_result(run_dir, STEP, failed)
        state.update(
            {
                "status": "failed",
                "phase": PHASE,
                "step": STEP,
                "current_step": STEP,
                "current_node": CURRENT_NODE,
                "blocked": None,
                "error": failed["error"],
            }
        )
        write_state(run_dir, state)
        return failed
