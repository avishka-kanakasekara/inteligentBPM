"""Typed models for Agent 3 — Risk and Compliance Analysis."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RiskCategory(StrEnum):
    FINANCIAL = "financial"
    PROCUREMENT = "procurement"
    LEGAL = "legal"
    PRIVACY = "privacy"
    SECURITY = "security"
    OPERATIONAL = "operational"
    VENDOR = "vendor"
    FRAUD = "fraud"
    REPUTATIONAL = "reputational"
    DATA_RESIDENCY = "data_residency"
    SEGREGATION_OF_DUTIES = "segregation_of_duties"


class RiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Likelihood(StrEnum):
    RARE = "rare"
    UNLIKELY = "unlikely"
    POSSIBLE = "possible"
    LIKELY = "likely"
    ALMOST_CERTAIN = "almost_certain"


class Impact(StrEnum):
    NEGLIGIBLE = "negligible"
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    SEVERE = "severe"


class RiskDecision(StrEnum):
    CLEAR = "CLEAR"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class PolicyRuleType(StrEnum):
    SPENDING_THRESHOLD = "spending_threshold"
    REQUIRED_QUOTATION_COUNT = "required_quotation_count"
    APPROVED_SUPPLIER = "approved_supplier_requirement"
    MANAGER_APPROVAL = "manager_approval"
    FINANCE_APPROVAL = "finance_approval"
    RESTRICTED_DATA_HANDLING = "restricted_data_handling"
    SEGREGATION_OF_DUTIES = "segregation_of_duties"
    REQUIRED_DOCUMENTATION = "required_documentation"
    GEOGRAPHIC_RESTRICTION = "geographic_restrictions"
    DEADLINE_RESTRICTION = "deadline_restrictions"
    CONFLICT_OF_INTEREST = "conflict_of_interest"
    VENDOR_RISK = "vendor_risk"
    CONTRACT_EXPIRATION = "contract_expiration"
    EMPLOYEE_AUTHORITY_LIMIT = "employee_authority_limits"


class EvidenceReference(BaseModel):
    type: Literal["policy", "document", "chunk", "plan", "allocation", "rule", "user"]
    id: str
    label: str | None = None
    excerpt: str | None = None
    page_number: int | None = None


class PolicyReference(BaseModel):
    policy_id: str | None = None
    policy_code: str | None = None
    title: str | None = None
    rule_type: PolicyRuleType
    section: str | None = None


class RiskItem(BaseModel):
    id: str
    category: RiskCategory
    severity: RiskSeverity
    likelihood: Likelihood
    impact: Impact
    description: str
    policy_reference: PolicyReference
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    blocking: bool = False
    required_remediation: str
    required_approver: str | None = None
    review_or_expiration_date: date | None = None
    rule_type: PolicyRuleType
    step_ids: list[str] = Field(default_factory=list)
    deterministic: bool = True


class RequiredApproval(BaseModel):
    id: str
    role: str
    reason: str
    risk_item_ids: list[str] = Field(default_factory=list)
    authority_limit: float | None = None


class AmbiguousPolicyFinding(BaseModel):
    """LLM assist only — never an approval decision."""

    topic: str
    explanation: str
    related_policy_codes: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    cannot_approve: bool = True


class RiskAmbiguityAssistOutput(BaseModel):
    ambiguous_findings: list[AmbiguousPolicyFinding] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    # Explicit: Gemini must never independently approve
    independently_approves: bool = False
    proposed_decision: RiskDecision | None = None


class RiskComplianceResult(BaseModel):
    schema_version: str = "1"
    organization_id: UUID
    process_id: UUID
    process_version_id: UUID
    allocation_id: UUID | None = None
    decision: RiskDecision
    overall_status: Literal["pass", "pass_with_conditions", "fail", "needs_human_review"]
    risk_items: list[RiskItem] = Field(default_factory=list)
    blocking_issues: list[RiskItem] = Field(default_factory=list)
    required_approvals: list[RequiredApproval] = Field(default_factory=list)
    required_approver_roles: list[str] = Field(default_factory=list)
    policy_evidence: list[EvidenceReference] = Field(default_factory=list)
    ambiguous_findings: list[AmbiguousPolicyFinding] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    plan_snapshot_hash: str
    allocation_snapshot_hash: str | None = None
    risk_snapshot_hash: str
    reasoning_summary: str = ""
    llm_used: bool = False
    gemini_approved: bool = False
    valid: bool = True
    invalidated_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ApprovalPackage(BaseModel):
    id: UUID
    organization_id: UUID
    process_id: UUID
    process_version_id: UUID
    process_run_id: UUID | None = None
    risk_result_id: UUID
    status: str
    plan_snapshot_hash: str
    allocation_snapshot_hash: str | None
    risk_snapshot_hash: str
    approval_snapshot_hash: str
    required_roles: list[str] = Field(default_factory=list)
    decision: RiskDecision
    prohibited_action: bool = False
    override_required: bool = False
    snapshot_payload: dict[str, Any] = Field(default_factory=dict)
    decided_by_user_id: UUID | None = None
    decision_note: str | None = None
    row_version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AnalyzeRiskRequest(BaseModel):
    process_version_id: UUID | None = None
    allocation_id: UUID | None = None
    spending_amount: float | None = None
    quotation_count: int | None = None
    geographic_region: str | None = None
    handles_restricted_data: bool | None = None
    notes: str | None = None


class OverrideRequest(BaseModel):
    justification: str = Field(min_length=10, max_length=4000)
    acknowledged_risk_item_ids: list[str] = Field(default_factory=list)
