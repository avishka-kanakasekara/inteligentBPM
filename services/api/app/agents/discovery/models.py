"""Typed models for Agent 1 — Process Discovery and Execution Planning."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionType(StrEnum):
    COLLECT_INFO = "collect_info"
    HUMAN_TASK = "human_task"
    REVIEW = "review"
    APPROVAL = "approval"
    NOTIFY = "notify"
    INTEGRATION = "integration"
    DECISION = "decision"
    WAIT = "wait"
    OTHER = "other"


class StatementKind(StrEnum):
    FACT = "fact"
    ASSUMPTION = "assumption"
    RECOMMENDATION = "recommendation"


class PlanSourceReference(BaseModel):
    type: Literal["document", "chunk", "message", "policy", "user"]
    id: str
    label: str | None = None
    page_number: int | None = None
    section_heading: str | None = None
    excerpt: str | None = None


class PlanAssumption(BaseModel):
    id: str
    text: str
    kind: StatementKind = StatementKind.ASSUMPTION
    source_refs: list[PlanSourceReference] = Field(default_factory=list)


class MissingInformation(BaseModel):
    id: str
    field: str
    question: str
    blocking: bool = True
    related_step_ids: list[str] = Field(default_factory=list)


class ProcessStep(BaseModel):
    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z][a-zA-Z0-9_\-]*$")
    action_type: ActionType
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    dependencies: list[str] = Field(default_factory=list)
    required_resources: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    allowed_tools: list[str] = Field(default_factory=list)
    approval_requirements: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    retry_behavior: str = "none"
    failure_behavior: str = "block_and_escalate"
    source_refs: list[PlanSourceReference] = Field(default_factory=list)
    is_decision_point: bool = False
    is_exception_path: bool = False
    sla: str | None = None


class ProcessEdge(BaseModel):
    edge_id: str
    from_step_id: str
    to_step_id: str
    edge_type: Literal["sequence", "conditional", "parallel", "exception"] = "sequence"
    condition: str | None = None


class ProcessIntent(BaseModel):
    goal: str
    actors: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    decision_points: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    slas: list[str] = Field(default_factory=list)
    exception_paths: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    source_refs: list[PlanSourceReference] = Field(default_factory=list)


class ProcessPlan(BaseModel):
    schema_version: str = "1"
    goal: str = Field(min_length=1)
    intent: ProcessIntent | None = None
    assumptions: list[PlanAssumption] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    steps: list[ProcessStep] = Field(min_length=1)
    edges: list[ProcessEdge] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning_summary: str = ""
    source_refs: list[PlanSourceReference] = Field(default_factory=list)
    # Explicit safety: Agent 1 must never claim these
    claims_process_safe: bool = False
    bypasses_risk_agent: bool = False
    executes_side_effects: bool = False


class DiscoveryChatSession(BaseModel):
    id: UUID
    organization_id: UUID
    process_id: UUID
    status: Literal["active", "closed"] = "active"
    created_by_user_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DiscoveryMessage(BaseModel):
    id: UUID
    organization_id: UUID
    process_id: UUID
    session_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    document_ids: list[UUID] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    intent: ProcessIntent | None = None
    plan_draft: ProcessPlan | None = None
    source_refs: list[PlanSourceReference] = Field(default_factory=list)
    suspicious_flags: list[str] = Field(default_factory=list)
    created_by_user_id: UUID | None = None
    created_at: datetime


# LLM structured outputs (subset / wrappers)


class ChatAgentOutput(BaseModel):
    reply: str
    clarifying_questions: list[str] = Field(default_factory=list)
    intent: ProcessIntent | None = None
    missing_information: list[MissingInformation] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    source_refs: list[PlanSourceReference] = Field(default_factory=list)
    claims_process_safe: bool = False
    bypasses_risk_agent: bool = False
    executes_side_effects: bool = False


class PlanAgentOutput(ProcessPlan):
    """LLM must emit a full ProcessPlan-shaped payload."""


def plan_to_snapshot(plan: ProcessPlan) -> dict[str, Any]:
    return plan.model_dump(mode="json")
