from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quality.git import validate_document_path
from quality.models import Document, ExtractionInput, PoolPlan, Text, validate_pool_plan


class FeedbackInput(BaseModel):
    """正文是原始 UTF-8 快照，不做 strip 或复制附件。"""

    model_config = ConfigDict(extra="forbid")
    source: str
    content: str
    attachments: list[str]
    intent: str = ""
    intent_source: str | None = None

    @model_validator(mode="after")
    def check_input(self) -> FeedbackInput:
        if not self.content.strip() and not self.attachments:
            raise ValueError("反馈正文与附件不能同时为空")
        paths = [self.source, *self.attachments]
        if self.intent_source is not None:
            paths.append(self.intent_source)
        if any(not Path(path).is_absolute() for path in paths):
            raise ValueError("反馈来源、意图来源和附件必须是绝对文件路径")
        return self


class Candidate(Document):
    title: Text
    kind: Literal["defect", "improvement", "new_capability"]
    user_task: Text
    trigger: Text
    observed: Text
    expected: Text
    basis: Text
    impact: Text
    evidence: list[Text]
    sources: list[Text] = Field(min_length=1)
    conclusion: Literal["verified", "needs_evidence", "needs_decision", "not_adopted", "covered"]
    mandatory: bool


class TriageReport(Document):
    summary: Text
    findings: list[Candidate]
    limitations: list[Text]


class Disposition(Document):
    candidate_id: Text
    action: Literal["include", "covered", "exclude", "defer", "satisfied"]
    reason: Text
    covered_by: str | None
    follow_up: str = ""


DESIGN_TASKS = ("project_intake", "solution_design", "engineering_architecture", "ui_ux_framework")


class DocumentChange(Document):
    path: Text
    reason: Text
    task: Literal["project_intake", "solution_design", "engineering_architecture", "ui_ux_framework"]


class RoutingReport(Document):
    summary: Text
    decisions: list[Disposition]
    document_changes: list[DocumentChange]
    ready_to_complete: bool
    required_inputs: list[Text] = Field(default_factory=list)


def validate_routing(report: RoutingReport, triage: dict, requirements: list[dict]) -> None:
    candidates = {row["id"]: row for row in triage["candidates"]}
    decisions = {row.candidate_id: row for row in report.decisions}
    if len(decisions) != len(report.decisions) or set(decisions) != set(candidates):
        raise ValueError("候选处置集合不一致或重复，不能新增、遗漏反馈")
    active = {row["id"] for row in requirements if row["status"] in {"pending", "active"}}
    for row in report.decisions:
        if (row.action != "covered" and row.covered_by is not None) or (row.action == "covered" and not row.covered_by):
            raise ValueError("只有 covered 必须且可以指定已有归属")
        if row.action == "defer" and not row.follow_up.strip():
            raise ValueError("暂不纳入必须说明后续条件")
        if row.action == "satisfied" and not candidates[row.candidate_id]["evidence"]:
            raise ValueError("已满足目标必须有核验事实，不能只凭处置标签")

    def terminal(identifier: str, seen: set[str]) -> str:
        if identifier in active:
            return "include"
        if identifier not in decisions or identifier in seen:
            raise ValueError("候选归属不存在、指向已完成历史或形成循环")
        row = decisions[identifier]
        return terminal(str(row.covered_by), seen | {identifier}) if row.action == "covered" else row.action

    for identifier, candidate in candidates.items():
        action = terminal(identifier, set())
        if candidate["mandatory"] and action not in {"include", "satisfied"} and not report.required_inputs:
            raise ValueError("本批必达事项不能延期或排除后宣布完成")
    included = any(row.action == "include" for row in report.decisions)
    if report.ready_to_complete and (included or active or report.required_inputs):
        raise ValueError("存在纳入项、活动需求或必要外部输入，不能直接收口")
    if not included and not report.ready_to_complete and not report.required_inputs:
        raise ValueError(f"当前分流没有可推进工作，本地材料或执行缺口需纠正：{report.summary}")
    if report.document_changes and not included:
        raise ValueError("没有纳入目标，不能修改产品定义或设计")
    paths = [validate_document_path(row.path) for row in report.document_changes]
    if len(set(paths)) != len(paths):
        raise ValueError("设计文件不能重复分配")
    if any(Path(path).parts[1] in {"backlog", "feedback"} for path in paths):
        raise ValueError("设计调整不能混入 Backlog 或反馈文档")
