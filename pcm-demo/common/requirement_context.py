from __future__ import annotations

from typing import Any


def phase_for(state: dict[str, Any]) -> str:
    """按受控工作流确定需求循环阶段，兼容没有 workflow 的旧状态。"""
    if "workflow" not in state:
        return "phase_1_requirement_development"
    if state["workflow"] == "product_quality":
        return "product_quality_iteration"
    raise RuntimeError("未知需求工作流")


def selection_node_for(state: dict[str, Any]) -> str:
    return (
        "quality:select_requirement"
        if phase_for(state) == "product_quality_iteration"
        else "phase_1:select_requirement"
    )
