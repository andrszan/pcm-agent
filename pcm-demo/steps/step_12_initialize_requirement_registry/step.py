from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.openai_responses import parse_response
from common.state import is_valid_requirement_id, write_state, write_step_result
from config import LLMConfig
from steps.step_11_requirement_breakdown.step import BACKLOG_PATH, verify_existing_success

STEP = 12
NAME = "解析 Backlog 并初始化需求注册表"
CURRENT_NODE = "phase_1:initialize_requirement_registry"
NEXT_NODE = "phase_1:select_requirement"
PHASE = "phase_1_requirement_development"
SYSTEM_PROMPT = """<task>
从提供的 Backlog 中提取全部且仅有的正式需求。

Backlog 是自由格式的自然语言文档。标题、表格、列表、详情卡、章节和排版方式都只是表达方式，不是识别正式需求的前提。
</task>

<extraction_rules>
- 只提取文档明确纳入正式交付范围的需求。目录、背景、说明、示例、风险、非目标、历史记录、候选项、未来设想和普通引用都不是正式需求。
- 必须覆盖文档中的全部正式需求，每项只输出一次。不得遗漏、合并、拆分、虚构或补充需求；同一需求在多处被引用时不能重复输出。
- id 和 title 必须忠实使用文档明确给出的正式值，不得翻译、改写、缩写、补全、替换或重新编号。
- 优先遵循文档明确给出的正式顺序；没有单独声明顺序时，按各正式需求在文档中首次被完整定义的顺序排列。
- requirements 数组的物理顺序就是正式顺序。order 必须等于数组位置，从 1 开始连续编号到需求总数，不得按依赖、优先级、实现难度或你的判断重新排序。
- depends_on 只能包含文档明确声明为前置依赖的正式需求 ID，并保留文档给出的顺序。
- 未明确声明的前置依赖必须返回空数组。不得根据正文关联、出现先后、业务常识、实现关系或隐含含义猜测依赖。
- 依赖必须使用本次输出中对应需求的准确 id；不得重复、不得引用自身，也不得引用未输出的需求。
- 返回前在内部复核：每个正式需求恰好出现一次，正式需求没有遗漏，order 连续且与数组位置一致，所有依赖都使用输出中的准确 id。不要输出复核过程。
</extraction_rules>

<output>
只返回一个严格 JSON 对象，首字符必须是 {，末字符必须是 }。

顶层必须且只能包含 requirements。requirements 必须是非空数组。
数组中的每一项必须且只能包含以下字段：
- id：非空字符串，格式为 [A-Za-z0-9][A-Za-z0-9_-]*。
- title：文档中的完整非空标题字符串。
- order：从 1 开始且与数组位置相同的连续整数。
- depends_on：前置需求 ID 字符串数组；没有明确依赖时必须是空数组。

禁止增加、删除、重命名或重复字段。禁止返回需求开发状态、完成信息或其它动态字段。
禁止返回 null、Markdown、代码围栏、YAML、注释、解释、分析过程或 JSON 对象之外的任何文本。
</output>"""


class BacklogExtractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backlog_markdown: str = Field(min_length=1)


class RequirementStatic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    order: int = Field(gt=0, strict=True)
    depends_on: list[str]

    @field_validator("id", "title")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("id")
    @classmethod
    def requirement_id_is_safe_path_segment(cls, value: str) -> str:
        if not is_valid_requirement_id(value):
            raise ValueError("需求 ID 不符合路径约定")
        return value

    @field_validator("depends_on")
    @classmethod
    def strip_dependencies(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("依赖 ID 不能为空")
        if any(not is_valid_requirement_id(value) for value in normalized):
            raise ValueError("依赖 ID 不符合路径约定")
        return normalized


class RequirementCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[RequirementStatic] = Field(min_length=1)


def result(
    status: str,
    summary: str,
    *,
    source: dict[str, str] | None = None,
    requirement_catalog: list[dict[str, Any]] | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": [],
        "blocked": None,
        "error": error,
        "source": source,
        "requirement_catalog": requirement_catalog or [],
    }


def _position(state: dict[str, Any]) -> tuple[Any, Any, Any]:
    return state.get("step"), state.get("current_step"), state.get("current_node")


def _workspace_from_state(state: dict[str, Any]) -> Path:
    try:
        root_value = state["workspace"]["root"]
        workspace_value = state["workspace"]["final_path"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    if not isinstance(root_value, str) or not isinstance(workspace_value, str):
        raise RuntimeError("工作区状态记录不完整")
    root = Path(root_value)
    workspace = Path(workspace_value)
    if not root.is_absolute() or not workspace.is_absolute():
        raise RuntimeError("工作区状态路径必须为绝对路径")
    if workspace.is_symlink():
        raise RuntimeError("产品工作区不得是符号链接")
    root = root.resolve()
    workspace = workspace.resolve()
    if workspace.parent != root or not workspace.is_dir():
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    return workspace


def _safe_workspace_output(workspace: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RuntimeError("Backlog 输出路径不符合约定")
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError("Backlog 输出路径不能包含符号链接")
    path = workspace / relative
    try:
        path.resolve().relative_to(workspace.resolve())
    except ValueError as error:
        raise RuntimeError("Backlog 输出路径越出产品工作区") from error
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Backlog 必须是非符号链接普通文件")
    return path


def _read_backlog(workspace: Path) -> tuple[dict[str, str], str]:
    path = _safe_workspace_output(workspace, BACKLOG_PATH.as_posix())
    try:
        content = path.read_bytes()
        markdown = content.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError("Backlog 不可读取") from error
    if not markdown.strip():
        raise RuntimeError("Backlog 不能为空")
    return {
        "path": BACKLOG_PATH.as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
    }, markdown


def _validate_static_rules(requirements: list[RequirementStatic]) -> None:
    identifiers = [requirement.id for requirement in requirements]
    orders = [requirement.order for requirement in requirements]
    if len(set(identifiers)) != len(identifiers):
        raise RuntimeError("需求 ID 不唯一")
    if len({identifier.casefold() for identifier in identifiers}) != len(identifiers):
        raise RuntimeError("需求 ID 忽略大小写后不唯一")
    if orders != list(range(1, len(requirements) + 1)):
        raise RuntimeError("需求顺序必须与数组位置一致并从 1 连续编号")
    known = set(identifiers)
    graph: dict[str, list[str]] = {}
    for requirement in requirements:
        if len(set(requirement.depends_on)) != len(requirement.depends_on):
            raise RuntimeError("需求依赖不能重复")
        if any(dependency not in known for dependency in requirement.depends_on):
            raise RuntimeError("需求依赖引用不存在")
        if requirement.id in requirement.depends_on:
            raise RuntimeError("需求不能依赖自身")
        graph[requirement.id] = requirement.depends_on

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise RuntimeError("需求依赖存在环")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in graph[identifier]:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in graph:
        visit(identifier)


def validate_catalog(
    value: RequirementCatalog | list[dict[str, Any]] | dict[str, Any],
) -> list[dict[str, Any]]:
    catalog = value if isinstance(value, RequirementCatalog) else RequirementCatalog.model_validate(
        value if isinstance(value, dict) and set(value) == {"requirements"} else {"requirements": value}
    )
    _validate_static_rules(catalog.requirements)
    return [requirement.model_dump(mode="json") for requirement in catalog.requirements]


def _source(value: Any) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or value.get("path") != BACKLOG_PATH.as_posix()
        or not isinstance(value.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
    ):
        raise RuntimeError("需求注册表来源不符合约定")
    return {"path": value["path"], "sha256": value["sha256"]}


def _success_payload(value: Any) -> tuple[dict[str, str], list[dict[str, Any]]]:
    expected_keys = {
        "step",
        "name",
        "status",
        "summary",
        "applicable",
        "outputs",
        "blocked",
        "error",
        "source",
        "requirement_catalog",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or type(value.get("step")) is not int
        or value.get("step") != STEP
        or value.get("name") != NAME
        or value.get("status") != "success"
        or not isinstance(value.get("summary"), str)
        or not value["summary"].strip()
        or value.get("applicable") is not True
        or value.get("outputs") != []
        or value.get("blocked") is not None
        or value.get("error") is not None
        or not isinstance(value.get("requirement_catalog"), list)
    ):
        raise RuntimeError("第 12 步成功结果不可复用")
    source = _source(value["source"])
    catalog = validate_catalog(value["requirement_catalog"])
    if catalog != value["requirement_catalog"]:
        raise RuntimeError("第 12 步成功结果需求目录不符合约定")
    return source, catalog


def has_complete_success(value: Any) -> bool:
    try:
        _success_payload(value)
    except (RuntimeError, ValueError, TypeError):
        return False
    return True


def _read_optional_result(run_dir: Path) -> Any | None:
    path = run_dir / "steps" / f"{STEP:02d}.json"
    if not path.exists() and not path.is_symlink():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _pending_registry(source: dict[str, str], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": source,
        "requirements": [
            {**requirement, "status": "pending", "completion": None}
            for requirement in catalog
        ],
    }


def _advance_success(
    run_dir: Path,
    state: dict[str, Any],
    source: dict[str, str],
    catalog: list[dict[str, Any]],
    *,
    saved: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if saved is None:
        saved = result(
            "success",
            "Backlog 静态需求已解析，需求注册表已初始化。",
            source=source,
            requirement_catalog=catalog,
        )
        write_step_result(run_dir, STEP, saved)
    state.update(
        {
            "status": "success",
            "phase": PHASE,
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "requirement_registry": _pending_registry(source, catalog),
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }
    )
    write_state(run_dir, state)
    return saved


def _verify_advanced_state(
    state: dict[str, Any], source: dict[str, str], catalog: list[dict[str, Any]]
) -> None:
    if (
        state.get("status") != "success"
        or state.get("phase") != PHASE
        or _position(state) != (STEP + 1, STEP + 1, NEXT_NODE)
        or state.get("active_requirement") is not None
        or state.get("requirement_cycle") is not None
        or state.get("blocked") is not None
        or state.get("error") is not None
        or state.get("requirement_registry") != _pending_registry(source, catalog)
    ):
        raise RuntimeError("第 12 步成功状态与需求注册表不一致")


def _verify_saved_success(
    saved: Any, source: dict[str, str]
) -> list[dict[str, Any]]:
    saved_source, catalog = _success_payload(saved)
    if saved_source != source:
        raise RuntimeError("第 12 步成功后的 Backlog 来源发生漂移")
    return catalog


async def extract_requirements(
    backlog_markdown: str,
    config: LLMConfig,
    *,
    model_runner=parse_response,
) -> RequirementCatalog:
    return await model_runner(
        config,
        system_prompt=SYSTEM_PROMPT,
        input_model=BacklogExtractionInput(backlog_markdown=backlog_markdown),
        output_model=RequirementCatalog,
        max_retries=0,
    )


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    config_loader=LLMConfig.load,
    model_runner=parse_response,
) -> dict[str, Any]:
    position = _position(state)
    if state.get("phase") != PHASE or position not in {
        (STEP, STEP, CURRENT_NODE),
        (STEP + 1, STEP + 1, NEXT_NODE),
    }:
        raise RuntimeError("运行状态不位于需求注册表初始化锚点")
    if state.get("active_requirement") is not None or state.get("requirement_cycle") is not None:
        raise RuntimeError("需求注册表初始化前不得存在活动需求")

    existing = _read_optional_result(run_dir)
    complete_success = has_complete_success(existing)
    if "requirement_registry" in state and not complete_success:
        raise RuntimeError("需求注册表存在但第 12 步没有完整成功结果")

    verify_existing_success(run_dir)
    workspace = _workspace_from_state(state)
    source, markdown = _read_backlog(workspace)

    if complete_success:
        catalog = _verify_saved_success(existing, source)
        if position == (STEP + 1, STEP + 1, NEXT_NODE):
            _verify_advanced_state(state, source, catalog)
            return result(
                "success",
                "Backlog 静态需求已解析，确认既有需求注册表成功。",
                source=source,
                requirement_catalog=catalog,
            )
        if "requirement_registry" in state:
            raise RuntimeError("第 12 步中断状态包含冲突的需求注册表")
        return _advance_success(run_dir, state, source, catalog, saved=existing)

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("第 12 步缺少可复用的完整成功结果")

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
    extracted = await extract_requirements(
        markdown,
        config_loader(),
        model_runner=model_runner,
    )
    catalog = validate_catalog(extracted)

    verified_source, _ = _read_backlog(workspace)
    if source != verified_source:
        raise RuntimeError("需求注册表初始化期间 Backlog 发生变化")
    return _advance_success(run_dir, state, source, catalog)
