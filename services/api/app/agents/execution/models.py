"""Typed models for Agent 4 — Controlled Process Execution / Tool Gateway."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SideEffectStatus(StrEnum):
    NONE = "none"
    DRAFT = "draft"
    EXTERNAL = "external"
    IRREVERSIBLE = "irreversible"


class ToolRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalType(StrEnum):
    NONE = "none"
    POLICY = "policy"
    MANAGER = "manager"
    FINANCE = "finance"
    EXPLICIT = "explicit"
    SNAPSHOT = "snapshot"


class IdempotencyBehavior(StrEnum):
    NONE = "none"
    REQUIRED = "required"
    REQUIRED_REPLAY = "required_replay"


class RetryBehavior(StrEnum):
    NONE = "none"
    SAFE_RETRY = "safe_retry"
    NO_DUPLICATE = "no_duplicate"


class ProviderSupport(StrEnum):
    MOCK = "mock"
    LIVE = "live"
    BOTH = "both"


class ToolErrorCode(StrEnum):
    FORBIDDEN_TOOL = "FORBIDDEN_TOOL"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_INVALID = "APPROVAL_INVALID"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    IDEMPOTENCY_REQUIRED = "IDEMPOTENCY_REQUIRED"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    RUN_STATUS_INVALID = "RUN_STATUS_INVALID"
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
    RISK_NOT_CLEAR = "RISK_NOT_CLEAR"
    ALLOWLIST_DENIED = "ALLOWLIST_DENIED"
    URL_NOT_ALLOWED = "URL_NOT_ALLOWED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    DRY_RUN = "DRY_RUN"
    PAUSED = "PAUSED"
    MISSING_INFORMATION = "MISSING_INFORMATION"


class IdempotencyPolicy(BaseModel):
    behavior: IdempotencyBehavior = IdempotencyBehavior.NONE
    scope_prefix: str = "tool"
    replay_on_duplicate: bool = True


class ApprovalRequirement(BaseModel):
    approval_type: ApprovalType = ApprovalType.NONE
    requires_approved_snapshot: bool = False
    irreversible: bool = False


class ToolAuthorizationPolicy(BaseModel):
    required_permission: str
    organization_scoped: bool = True
    allow_without_approval_if_readonly: bool = True
    allowlist_only: bool = True


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permission: str
    risk_level: ToolRiskLevel
    side_effect_status: SideEffectStatus
    required_approval_type: ApprovalType
    idempotency_behavior: IdempotencyBehavior
    organization_scope: bool = True
    provider_support: ProviderSupport = ProviderSupport.BOTH
    retry_behavior: RetryBehavior = RetryBehavior.SAFE_RETRY
    timeout_seconds: float = 30.0
    authorization: ToolAuthorizationPolicy | None = None
    idempotency_policy: IdempotencyPolicy | None = None
    approval_requirement: ApprovalRequirement | None = None


class ToolContext(BaseModel):
    organization_id: UUID
    process_id: UUID
    process_run_id: UUID
    process_version_id: UUID | None = None
    actor_user_id: UUID | None = None
    correlation_id: str | None = None
    permissions: frozenset[str] = Field(default_factory=frozenset)
    plan_snapshot_hash: str | None = None
    risk_snapshot_hash: str | None = None
    approval_id: UUID | None = None
    approval_snapshot_hash: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    dry_run: bool = False
    current_step_id: str | None = None
    provider_mode: Literal["mock", "live"] = "mock"

    model_config = {"arbitrary_types_allowed": True}


class ToolError(BaseModel):
    code: ToolErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    ok: bool
    tool_name: str
    data: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    mock: bool = True
    untrusted: bool = True
    error: ToolError | None = None
    latency_ms: float | None = None


class ToolInvocation(BaseModel):
    id: UUID
    organization_id: UUID
    process_id: UUID
    process_run_id: UUID
    tool_name: str
    arguments: dict[str, Any]
    idempotency_key: str | None = None
    status: Literal["proposed", "denied", "executed", "replayed", "failed", "dry_run"]
    result: ToolResult | None = None
    error: ToolError | None = None
    plan_snapshot_hash: str | None = None
    risk_snapshot_hash: str | None = None
    approval_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NormalizedQuoteLine(BaseModel):
    sku: str | None = None
    description: str | None = None
    quantity: float
    unit: str
    unit_price_usd: float
    line_total_usd: float


class NormalizedQuotation(BaseModel):
    quotation_id: str
    supplier_id: str
    supplier_name: str | None = None
    currency_original: str
    fx_rate_to_usd: float
    subtotal_usd: float
    tax_usd: float
    shipping_usd: float
    total_cost_usd: float
    delivery_days: int | None = None
    warranty_months: int | None = None
    payment_terms_days: int | None = None
    supplier_risk_score: float = Field(ge=0.0, le=1.0, default=0.5)
    policy_compliance_score: float = Field(ge=0.0, le=1.0, default=0.5)
    lines: list[NormalizedQuoteLine] = Field(default_factory=list)
    mock: bool = True
    untrusted: bool = True


class QuotationScoreBreakdown(BaseModel):
    total_cost: float
    delivery_time: float
    warranty: float
    payment_terms: float
    supplier_risk: float
    policy_compliance: float
    weighted_total: float


class QuotationComparisonResult(BaseModel):
    quotations: list[NormalizedQuotation]
    scores: dict[str, QuotationScoreBreakdown]
    ranking: list[str]
    winner_quotation_id: str | None = None
    deterministic: bool = True
    explanation: str = ""
    llm_used: bool = False


class ExecutionState(BaseModel):
    process_id: UUID
    process_run_id: UUID
    status: str
    current_step_index: int = 0
    current_step_id: str | None = None
    pause_reason: str | None = None
    dry_run: bool = False
    plan_snapshot_hash: str | None = None
    risk_snapshot_hash: str | None = None
    approval_id: UUID | None = None
    tool_invocations: list[ToolInvocation] = Field(default_factory=list)
    human_checkpoints: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)


class ToolProposalOutput(BaseModel):
    """Structured tool proposal from Agent 4 (Gemini)."""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    requires_approval: bool = False
    approval_reason: str | None = None
    next_step_index: int | None = None

