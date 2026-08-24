from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.files import sha256
from common.openai_responses import parse_response
from common.state import is_valid_requirement_id, write_state, write_step_result
from config import LLMConfig
from steps.step_11_requirement_breakdown.step import BACKLOG_PATH, verify_existing_success

STEP = 12
NAME = "解析 Backlog 并初始化需求注册表"
CURRENT_NODE = "phase_1:initialize_requirement_registry"
NEXT_NODE = "phase_1:select_requirement"
PHASE = "phase_1_requirement_development"
SYSTEM_PROMPT = """从提供的 Backlog Markdown 中提取正式需求详情卡的静态字段。

只提取正式需求详情卡，忽略目录、说明、示例和非正式标题。每一项都必须返回详情卡标题中的 id 与 title、详情卡出现顺序 order，以及该需求明确列出的 depends_on。id、title 和每个依赖 ID 必须保留其身份含义；没有依赖时 depends_on 返回空数组。不得遗漏正式需求、不得虚构需求或依赖。

输出只能包含 requirements 及其中每项的 id、title、order、depends_on；禁止增加其它字段。只返回符合所提供结构化输出格式的严格 JSON 对象；不要使用 Markdown、代码围栏、YAML 或 JSON 之外的文本。"""


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


@dataclass(frozen=True)
class FormalCard:
    id: str
    title: str
    order: int
    depends_on: tuple[str, ...]


_H2 = re.compile(r"^##(?!#)\s+(.+?)\s*$")
_H4 = re.compile(r"^####(?!#)\s+([^\s#]+)\s+(.+?)\s*$")
_H5 = re.compile(r"^#####(?!#)\s+(.+?)\s*$")
_H1_TO_H5 = re.compile(r"^#{1,5}(?!#)\s+")
_HEX_SHA = re.compile(r"^[0-9a-f]{40,64}$")


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


def _read_backlog(workspace: Path) -> tuple[Path, str]:
    path = _safe_workspace_output(workspace, BACKLOG_PATH.as_posix())
    try:
        markdown = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError("Backlog 不可读取") from error
    if not markdown.strip():
        raise RuntimeError("Backlog 不能为空")
    return path, markdown


def _git_run(path: Path, *args: str, allowed_returncodes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=path,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise RuntimeError("未安装 Git") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 命令超时") from error
    if completed.returncode not in allowed_returncodes:
        raise RuntimeError("无法读取产品根 Git 仓库状态")
    return completed


def _git_read(path: Path, *args: str) -> str:
    return _git_run(path, *args).stdout.rstrip("\n")


def _root_main_sha(workspace: Path, output: str) -> str:
    top_level = Path(_git_read(workspace, "rev-parse", "--show-toplevel")).resolve()
    if top_level != workspace.resolve():
        raise RuntimeError("产品根 Git 仓库顶层目录不一致")
    if _git_read(workspace, "branch", "--show-current") != "main":
        raise RuntimeError("产品根 Git 仓库分支不是 main")
    if _git_read(workspace, "status", "--porcelain=v1", "--untracked-files=all") != "":
        raise RuntimeError("产品根 Git 仓库必须 clean")
    tracked = _git_run(
        workspace,
        "ls-files",
        "--error-unmatch",
        "--",
        output,
        allowed_returncodes=(0, 1),
    )
    if tracked.returncode != 0:
        raise RuntimeError("Backlog 未被产品根 Git 仓库跟踪")
    head = _git_read(workspace, "rev-parse", "HEAD")
    if not _HEX_SHA.fullmatch(head):
        raise RuntimeError("产品根 Git 仓库 HEAD 不符合约定")
    return head


def _normalize_heading(value: str) -> str:
    return re.sub(r"[\s`*_：:()（）]", "", value).casefold()


def _heading_regions(markdown: str) -> list[tuple[int, str, int, int]]:
    lines = markdown.splitlines()
    headings = [(index, match.group(1).strip()) for index, line in enumerate(lines) if (match := _H2.match(line))]
    return [
        (index, title, start + 1, headings[position + 1][0] if position + 1 < len(headings) else len(lines))
        for position, (start, title) in enumerate(headings)
        for index in [position]
    ]


def _card_headings(lines: list[str], start: int, end: int) -> list[tuple[int, str, str]]:
    return [
        (index, match.group(1).strip(), match.group(2).strip())
        for index in range(start, end)
        if (match := _H4.match(lines[index]))
    ]


def _split_markdown_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [cell.strip() for cell in cells]


def _is_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _overview_column_indexes(cells: list[str]) -> tuple[int, int, int] | None:
    normalized = [_normalize_heading(cell).replace("_", "") for cell in cells]
    id_indexes = [
        index
        for index, value in enumerate(normalized)
        if value == "id" or "需求id" in value or value.endswith("需求编号")
    ]
    title_indexes = [
        index
        for index, value in enumerate(normalized)
        if value in {"需求", "大需求", "需求名称", "需求标题", "标题", "名称"}
        or "需求标题" in value
        or "需求名称" in value
    ]
    dependency_indexes = [
        index
        for index, value in enumerate(normalized)
        if value in {"前置依赖", "依赖", "dependson", "dependency", "dependencies"}
    ]
    indexes = [*id_indexes, *title_indexes, *dependency_indexes]
    if (
        len(id_indexes) == len(title_indexes) == len(dependency_indexes) == 1
        and len(set(indexes)) == 3
    ):
        return id_indexes[0], title_indexes[0], dependency_indexes[0]
    return None


def _parse_dependencies(value: str, known_ids: list[str]) -> tuple[str, ...]:
    text = value.strip()
    if text in {"", "无", "无。", "-"}:
        return ()
    matches = [
        (match.start(), match.end(), identifier)
        for identifier in known_ids
        for match in re.finditer(
            rf"(?<![A-Za-z0-9_-]){re.escape(identifier)}(?![A-Za-z0-9_-])", text
        )
    ]
    matches.sort()
    if not matches or any(matches[index][1] > matches[index + 1][0] for index in range(len(matches) - 1)):
        raise RuntimeError("Backlog 正式需求总览依赖不符合约定")
    dependencies = [identifier for _, _, identifier in matches]
    if len(set(dependencies)) != len(dependencies):
        raise RuntimeError("Backlog 正式需求总览依赖不能重复")
    cursor = 0
    residual: list[str] = []
    for start, end, _ in matches:
        residual.append(text[cursor:start])
        cursor = end
    residual.append(text[cursor:])
    if not re.fullmatch(r"[\s,，、;；|/()（）\[\]{}:：。-]*", "".join(residual)):
        raise RuntimeError("Backlog 正式需求总览依赖包含未知语义")
    return tuple(dependencies)


def _overview_cards(
    lines: list[str], regions: list[tuple[int, str, int, int]]
) -> list[tuple[str, str, tuple[str, ...]]]:
    overview_regions = [
        region
        for region in regions
        if "大需求总览" in _normalize_heading(region[1]) or "需求总览" in _normalize_heading(region[1])
    ]
    if len(overview_regions) != 1:
        raise RuntimeError("Backlog 必须有唯一正式需求总览区")
    _, _, start, end = overview_regions[0]
    tables: list[list[tuple[str, str, str]]] = []
    for index in range(start, end - 1):
        if "|" not in lines[index] or "|" not in lines[index + 1]:
            continue
        header = _split_markdown_row(lines[index])
        separator = _split_markdown_row(lines[index + 1])
        indexes = _overview_column_indexes(header)
        if indexes is None or len(header) != len(separator) or not _is_table_separator(separator):
            continue
        id_index, title_index, dependency_index = indexes
        rows: list[tuple[str, str, str]] = []
        row_index = index + 2
        while row_index < end and "|" in lines[row_index]:
            cells = _split_markdown_row(lines[row_index])
            if len(cells) != len(header):
                raise RuntimeError("Backlog 正式需求总览表格式不符合约定")
            identifier = cells[id_index].strip()
            title = cells[title_index].strip()
            if not identifier or not title or any(identifier == row[0] for row in rows):
                raise RuntimeError("Backlog 正式需求总览表内容不符合约定")
            rows.append((identifier, title, cells[dependency_index]))
            row_index += 1
        if not rows:
            raise RuntimeError("Backlog 正式需求总览表不能为空")
        tables.append(rows)
    if len(tables) != 1:
        raise RuntimeError("Backlog 必须有唯一含依赖列的正式需求总览表")
    rows = tables[0]
    known_ids = [identifier for identifier, _, _ in rows]
    return [
        (identifier, title, _parse_dependencies(dependency, known_ids))
        for identifier, title, dependency in rows
    ]


def _detail_dependencies(
    lines: list[str], start: int, end: int, known_ids: list[str]
) -> tuple[str, ...]:
    headings = [
        index
        for index in range(start, end)
        if (match := _H5.match(lines[index]))
        and _normalize_heading(match.group(1)) == "前置依赖"
    ]
    if len(headings) != 1:
        raise RuntimeError("Backlog 正式需求详情卡必须有唯一前置依赖章节")
    content_start = headings[0] + 1
    content_end = next(
        (
            index
            for index in range(content_start, end)
            if _H1_TO_H5.match(lines[index])
        ),
        end,
    )
    content = [line.strip() for line in lines[content_start:content_end] if line.strip()]
    if not content or (len(content) == 1 and content[0] in {"无", "无。", "-"}):
        return ()
    dependencies: list[str] = []
    for line in content:
        if not line.startswith("-") or len(line) == 1 or not line[1].isspace():
            raise RuntimeError("Backlog 正式需求详情卡前置依赖格式不符合约定")
        value = line[1:].strip()
        parsed = _parse_dependencies(value, known_ids)
        if (
            len(parsed) != 1
            or not re.fullmatch(rf"{re.escape(parsed[0])}。?", value)
        ):
            raise RuntimeError("Backlog 正式需求详情卡前置依赖格式不符合约定")
        dependencies.append(parsed[0])
    if len(set(dependencies)) != len(dependencies):
        raise RuntimeError("Backlog 正式需求详情卡前置依赖不能重复")
    return tuple(dependencies)


def formal_cards(markdown: str) -> list[FormalCard]:
    lines = markdown.splitlines()
    regions = _heading_regions(markdown)
    overview = _overview_cards(lines, regions)
    detail_regions = [region for region in regions if "需求详情" in _normalize_heading(region[1])]
    if len(detail_regions) != 1:
        raise RuntimeError("Backlog 必须有唯一正式需求详情区")
    _, _, start, end = detail_regions[0]
    candidates = _card_headings(lines, start, end)
    selected_ids = [identifier for _, identifier, _ in candidates]
    overview_ids = [identifier for identifier, _, _ in overview]
    if not candidates or len(set(selected_ids)) != len(selected_ids):
        raise RuntimeError("Backlog 正式需求详情卡 ID 不唯一")
    if selected_ids != overview_ids:
        raise RuntimeError("Backlog 正式需求详情卡与总览顺序或范围不一致")
    if any(
        overview[index][1].strip() != title.strip()
        for index, (_, _, title) in enumerate(candidates)
    ):
        raise RuntimeError("Backlog 正式需求详情卡标题与总览不一致")
    detail_dependencies = [
        _detail_dependencies(
            lines,
            card_start,
            candidates[index + 1][0] if index + 1 < len(candidates) else end,
            overview_ids,
        )
        for index, (card_start, _, _) in enumerate(candidates)
    ]
    if any(
        detail_dependencies[index] != overview[index][2]
        for index in range(len(candidates))
    ):
        raise RuntimeError("Backlog 正式需求详情卡依赖与总览不一致")
    return [
        FormalCard(
            id=identifier,
            title=title.strip(),
            order=index,
            depends_on=detail_dependencies[index - 1],
        )
        for index, (_, identifier, title) in enumerate(candidates, start=1)
    ]


def _validate_static_rules(requirements: list[RequirementStatic]) -> None:
    identifiers = [requirement.id for requirement in requirements]
    orders = [requirement.order for requirement in requirements]
    if len(set(identifiers)) != len(identifiers):
        raise RuntimeError("需求 ID 不唯一")
    if len({identifier.casefold() for identifier in identifiers}) != len(identifiers):
        raise RuntimeError("需求 ID 忽略大小写后不唯一")
    if len(set(orders)) != len(orders) or sorted(orders) != list(range(1, len(orders) + 1)):
        raise RuntimeError("需求 order 必须从 1 连续编号")
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
    cards: list[FormalCard] | None = None,
) -> list[dict[str, Any]]:
    catalog = value if isinstance(value, RequirementCatalog) else RequirementCatalog.model_validate(
        value if isinstance(value, dict) and set(value) == {"requirements"} else {"requirements": value}
    )
    requirements = catalog.requirements
    _validate_static_rules(requirements)
    if cards is not None:
        expected = {card.id: card for card in cards}
        actual = {requirement.id: requirement for requirement in requirements}
        if set(actual) != set(expected):
            raise RuntimeError("模型提取的需求 ID 与 Backlog 正式详情卡不一致")
        for identifier, card in expected.items():
            requirement = actual[identifier]
            if (
                requirement.title != card.title
                or requirement.order != card.order
                or requirement.depends_on != list(card.depends_on)
            ):
                raise RuntimeError("模型提取的需求静态字段与 Backlog 正式详情卡不一致")
    return [requirement.model_dump(mode="json") for requirement in requirements]


def _source(value: Any) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256", "root_main_sha"}
        or value.get("path") != BACKLOG_PATH.as_posix()
        or not isinstance(value.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
        or not isinstance(value.get("root_main_sha"), str)
        or not _HEX_SHA.fullmatch(value["root_main_sha"])
    ):
        raise RuntimeError("需求注册表来源不符合约定")
    return {
        "path": value["path"],
        "sha256": value["sha256"],
        "root_main_sha": value["root_main_sha"],
    }


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


def _current_source(workspace: Path) -> tuple[dict[str, str], list[FormalCard], str]:
    path, markdown = _read_backlog(workspace)
    source = {
        "path": BACKLOG_PATH.as_posix(),
        "sha256": sha256(path),
        "root_main_sha": _root_main_sha(workspace, BACKLOG_PATH.as_posix()),
    }
    return source, formal_cards(markdown), markdown


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
    state: dict[str, Any], saved: Any, source: dict[str, str], cards: list[FormalCard]
) -> list[dict[str, Any]]:
    saved_source, catalog = _success_payload(saved)
    catalog = validate_catalog(catalog, cards)
    if saved_source != source:
        raise RuntimeError("第 12 步成功后的 Backlog 或根仓基线发生漂移")
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
        max_output_tokens=4096,
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
    source, cards, markdown = _current_source(workspace)

    if complete_success:
        catalog = _verify_saved_success(state, existing, source, cards)
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
    catalog = validate_catalog(extracted, cards)

    verified_source, verified_cards, _ = _current_source(workspace)
    if source != verified_source or cards != verified_cards:
        raise RuntimeError("需求注册表初始化期间 Backlog 或根仓基线发生漂移")
    return _advance_success(run_dir, state, source, catalog)
