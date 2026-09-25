from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1)]


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExtractionInput(Document):
    """report 保留完整交接材料，而非最后一条补证。"""

    report: str
    context: str


class Finding(Document):
    title: Text
    user_task: Text
    trigger: Text
    observed: Text
    expected: Text
    basis: Text
    impact: Text
    evidence: list[Text] = Field(min_length=1)
    priority: Literal["high", "medium", "low"]
    confidence: Literal["high", "medium", "low"]


class Coverage(Document):
    user_task: Text
    outcome: Literal["covered", "blocked_by_defect", "not_applicable", "gap"]
    reason: Text
    evidence: list[Text]
    blocking_findings: list[int]


class AuditReport(Document):
    summary: Text
    applicable: bool
    coverage: list[Coverage]
    findings: list[Finding]
    duplicates: list[str]
    high_impact: list[str]
    limitations: list[str]


def validate_audit(report: AuditReport) -> None:
    if report.applicable and not report.coverage:
        raise ValueError("适用审计必须记录用户任务覆盖")
    if not report.applicable and report.findings:
        raise ValueError("不适用审计不能同时产生修复候选")
    tasks = [row.user_task for row in report.coverage]
    if len(tasks) != len(set(tasks)):
        raise ValueError("用户任务覆盖不能重复")
    for row in report.coverage:
        if row.outcome == "covered" and not row.evidence:
            raise ValueError("已覆盖任务缺少观察证据")
        if row.outcome == "blocked_by_defect" and not row.blocking_findings:
            raise ValueError("缺陷阻断任务必须关联本次经核验发现")
        if row.outcome != "blocked_by_defect" and row.blocking_findings:
            raise ValueError(f"任务 {row.user_task} 的状态为 {row.outcome}，不能携带阻断发现 {row.blocking_findings}")
        if len(row.blocking_findings) != len(set(row.blocking_findings)):
            raise ValueError("任务阻断发现重复")
        if any(type(i) is not int or not 0 <= i < len(report.findings) for i in row.blocking_findings):
            raise ValueError(f"任务 {row.user_task} 的阻断发现索引越界：{row.blocking_findings}；发现数={len(report.findings)}")


class Disposition(Document):
    candidate_id: Text
    action: Literal["include", "covered", "exclude"]
    reason: Text
    covered_by: str | None


class DocumentChange(Document):
    path: Text
    reason: Text


class RoutingReport(Document):
    summary: Text
    decisions: list[Disposition]
    document_changes: list[DocumentChange]
    ready_to_complete: bool
    required_inputs: list[Text] = Field(default_factory=list)


def validate_routing(report: RoutingReport, audit: dict, requirements: list[dict]) -> None:
    candidates = {row["id"] for row in audit["candidates"]}
    decisions = {row.candidate_id: row for row in report.decisions}
    if len(decisions) != len(report.decisions) or set(decisions) != candidates:
        raise ValueError(f"候选处置集合不一致：输入={sorted(candidates)}；缺失={sorted(candidates - set(decisions))}；"
                         f"多出={sorted(set(decisions) - candidates)}；重复={len(decisions) != len(report.decisions)}")
    active = {row["id"] for row in requirements if row["status"] in {"pending", "active"}}
    for row in report.decisions:
        if row.action != "covered" and row.covered_by is not None:
            raise ValueError("只有 covered 可以指定已有归属")
        if row.action == "covered" and not row.covered_by:
            raise ValueError("covered 必须指明同轮候选或未完成正式修复项")

    def terminal(identifier: str, seen: set[str]) -> str:
        if identifier in active:
            return "include"
        if identifier not in decisions or identifier in seen:
            raise ValueError(f"候选归属 {identifier} 不存在、指向已完成历史或形成循环；已访问={sorted(seen)}")
        row = decisions[identifier]
        if row.action != "covered":
            return row.action
        return terminal(str(row.covered_by), seen | {identifier})

    for identifier in decisions:
        terminal(identifier, set())
    for row in audit["coverage"]:
        if row["outcome"] == "blocked_by_defect":
            for identifier in row["blocking_candidates"]:
                if terminal(identifier, set()) != "include":
                    raise ValueError("已复现且阻断任务的缺陷没有修复归属，不能排除后收口")
    has_work = any(row.action == "include" for row in report.decisions)
    gaps = any(row["outcome"] in {"blocked_by_defect", "gap"} for row in audit["coverage"])
    if report.ready_to_complete and (has_work or gaps or active or report.required_inputs):
        raise ValueError("存在应开发项、受阻任务或未完成正式项，不能收口")
    if not has_work and not report.ready_to_complete and not report.required_inputs:
        raise ValueError(f"没有可推进的修复且未满足收口，材料或本地现场需纠正：{report.summary}")


class RequirementBinding(Document):
    requirement_id: Text
    candidate_ids: list[Text] = Field(min_length=1)


class RegressionOwner(Document):
    candidate_id: Text
    requirement_id: Text


class PoolPlan(Document):
    summary: Text
    requirements: list[RequirementBinding] = Field(min_length=1)
    regression_owners: list[RegressionOwner] = Field(min_length=1)


def validate_pool_plan(plan: PoolPlan, routing: dict, historical_ids: set[str]) -> None:
    included = {row["candidate_id"] for row in routing["decisions"] if row["action"] == "include"}
    identifiers = [row.requirement_id for row in plan.requirements]
    folded = [identifier.lower() for identifier in identifiers]
    if len(set(folded)) != len(folded) or set(folded) & {i.lower() for i in historical_ids}:
        raise ValueError("本批正式 ID 重复或与历史冲突")
    from common.state import is_valid_requirement_id
    if any(not is_valid_requirement_id(i) for i in identifiers):
        raise ValueError("本批正式 ID 格式无效")
    covered: set[str] = set()
    for row in plan.requirements:
        if len(set(row.candidate_ids)) != len(row.candidate_ids) or not set(row.candidate_ids) <= included:
            raise ValueError("正式需求引用了重复或未纳入候选")
        covered.update(row.candidate_ids)
    if covered != included:
        raise ValueError("本批正式需求没有完整承接全部纳入候选")
    owners = {row.candidate_id: row.requirement_id for row in plan.regression_owners}
    if len(owners) != len(plan.regression_owners) or set(owners) != included:
        raise ValueError("每个纳入候选必须有且只有一个完整回归承接需求")
    bindings = {row.requirement_id: set(row.candidate_ids) for row in plan.requirements}
    if any(candidate not in bindings.get(owner, set()) for candidate, owner in owners.items()):
        raise ValueError("完整回归归属必须是实际承接该候选的正式需求")
