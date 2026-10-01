from __future__ import annotations

from typing import Any


def phase_for(state: dict[str, Any]) -> str:
    """按受控工作流确定需求循环阶段，兼容没有 workflow 的旧状态。"""
    if "workflow" not in state:
        return "phase_1_requirement_development"
    if state["workflow"] == "product_quality":
        return "product_quality_iteration"
    if state["workflow"] == "product_feedback":
        return "product_feedback_iteration"
    raise RuntimeError("未知需求工作流")


def selection_node_for(state: dict[str, Any]) -> str:
    phase = phase_for(state)
    if phase == "product_quality_iteration":
        return "quality:select_requirement"
    if phase == "product_feedback_iteration":
        return "feedback:select_requirement"
    return "phase_1:select_requirement"
