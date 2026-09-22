from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from common.openai_responses import parse_response
from common.requirement_registry import (
    SYSTEM_PROMPT,
    BacklogExtractionInput,
    RequirementCatalog,
    RequirementStatic,
    _validate_static_rules,
    extract_requirements,
    validate_catalog,
)
from common.state import write_state, write_step_result
from config import LLMConfig
from steps.step_11_requirement_breakdown.step import BACKLOG_PATH, verify_existing_success

STEP = 12
NAME = "解析 Backlog 并初始化需求注册表"
CURRENT_NODE = "phase_1:initialize_requirement_registry"
NEXT_NODE = "phase_1:select_requirement"
PHASE = "phase_1_requirement_development"

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
