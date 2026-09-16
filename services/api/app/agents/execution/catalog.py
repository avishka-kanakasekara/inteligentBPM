"""Allowlisted tool catalog for Agent 4."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.execution.models import (
    ApprovalRequirement,
    ApprovalType,
    IdempotencyBehavior,
    IdempotencyPolicy,
    ProviderSupport,
    RetryBehavior,
    SideEffectStatus,
    ToolAuthorizationPolicy,
    ToolDefinition,
    ToolRiskLevel,
)
from app.permissions import codes as perm


class EmployeeLookupIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class ManagerLookupIn(BaseModel):
    employee_id: str = Field(min_length=1)


class SupplierSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    approved_only: bool = True


class SupplierContactLookupIn(BaseModel):
    supplier_id: str = Field(min_length=1)


class SupplierApprovedStatusIn(BaseModel):
    supplier_id: str = Field(min_length=1)


class PolicySearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class DocumentSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class EmailDraftIn(BaseModel):
    to_employee_id: str
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class EmailSendIn(BaseModel):
    draft_id: str | None = None
    to_employee_id: str
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SupplierRequestQuoteIn(BaseModel):
    supplier_id: str
    product_sku: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, le=100000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    subject: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=8000)
    contact_email: str | None = Field(default=None, max_length=200)


class SupplierCollectQuoteIn(BaseModel):
    request_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)


class QuotationExtractIn(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20000)
    supplier_id: str | None = None


class QuotationNormalizeIn(BaseModel):
    quotation: dict[str, Any]


class QuotationCompareIn(BaseModel):
    quotation_ids: list[str] = Field(min_length=1)
    explain: bool = True


class PurchaseOrderDraftIn(BaseModel):
    supplier_id: str
    amount_total: float = Field(gt=0)
    currency_code: str = Field(default="USD", min_length=3, max_length=3)
    lines: list[dict[str, Any]] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=8, max_length=128)


class PurchaseOrderSubmitIn(BaseModel):
    purchase_order_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)


class ApprovalRequestIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    required_roles: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=8, max_length=128)


class NotificationSendIn(BaseModel):
    user_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class CalendarCreateEventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_at: str = Field(min_length=1, max_length=64)
    end_at: str | None = None
    attendees: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class TaskAssignIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    assignee_id: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    due_at: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)


class DocumentGenerateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    doc_type: str = Field(default="memo", max_length=64)
    content: str = Field(min_length=1, max_length=50000)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _def(
    *,
    name: str,
    description: str,
    args: type[BaseModel],
    permission: str,
    risk: ToolRiskLevel,
    side_effect: SideEffectStatus,
    approval: ApprovalType,
    idempotency: IdempotencyBehavior,
    timeout: float = 30.0,
    irreversible: bool = False,
) -> ToolDefinition:
    requires_snapshot = approval in {
        ApprovalType.EXPLICIT,
        ApprovalType.SNAPSHOT,
        ApprovalType.FINANCE,
    } or side_effect in {SideEffectStatus.EXTERNAL, SideEffectStatus.IRREVERSIBLE}
    return ToolDefinition(
        name=name,
        description=description,
        input_schema=args.model_json_schema(),
        output_schema={"type": "object"},
        required_permission=permission,
        risk_level=risk,
        side_effect_status=side_effect,
        required_approval_type=approval,
        idempotency_behavior=idempotency,
        organization_scope=True,
        provider_support=ProviderSupport.BOTH,
        retry_behavior=(
            RetryBehavior.SAFE_RETRY
            if side_effect == SideEffectStatus.NONE
            else RetryBehavior.NO_DUPLICATE
        ),
        timeout_seconds=timeout,
        authorization=ToolAuthorizationPolicy(
            required_permission=permission,
            organization_scoped=True,
            allow_without_approval_if_readonly=side_effect == SideEffectStatus.NONE,
        ),
        idempotency_policy=IdempotencyPolicy(
            behavior=idempotency,
            scope_prefix=f"tool:{name}",
            replay_on_duplicate=True,
        ),
        approval_requirement=ApprovalRequirement(
            approval_type=approval,
            requires_approved_snapshot=requires_snapshot,
            irreversible=irreversible or side_effect == SideEffectStatus.IRREVERSIBLE,
        ),
    )


TOOL_ARGS: dict[str, type[BaseModel]] = {
    "company.employee_lookup": EmployeeLookupIn,
    "company.manager_lookup": ManagerLookupIn,
    "supplier.search": SupplierSearchIn,
    "supplier.contact_lookup": SupplierContactLookupIn,
    "supplier.approved_status": SupplierApprovedStatusIn,
    "policy.search": PolicySearchIn,
    "document.search": DocumentSearchIn,
    "email.create_draft": EmailDraftIn,
    "email.send": EmailSendIn,
    "supplier.request_quote": SupplierRequestQuoteIn,
    "supplier.collect_quote": SupplierCollectQuoteIn,
    "quotation.extract": QuotationExtractIn,
    "quotation.normalize": QuotationNormalizeIn,
    "quotation.compare": QuotationCompareIn,
    "purchase_order.create_draft": PurchaseOrderDraftIn,
    "purchase_order.submit": PurchaseOrderSubmitIn,
    "approval.request": ApprovalRequestIn,
    "notification.send": NotificationSendIn,
    "calendar.create_event": CalendarCreateEventIn,
    "task.assign": TaskAssignIn,
    "document.generate": DocumentGenerateIn,
}


def build_tool_catalog() -> dict[str, ToolDefinition]:
    tools = [
        _def(
            name="company.employee_lookup",
            description="Look up employees in the organization directory (read-only).",
            args=EmployeeLookupIn,
            permission=perm.DIRECTORY_READ,
            risk=ToolRiskLevel.LOW,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="company.manager_lookup",
            description="Resolve manager hierarchy for an employee (read-only).",
            args=ManagerLookupIn,
            permission=perm.DIRECTORY_READ,
            risk=ToolRiskLevel.LOW,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="supplier.search",
            description="Search suppliers in the organization directory (read-only).",
            args=SupplierSearchIn,
            permission=perm.SUPPLIERS_READ,
            risk=ToolRiskLevel.LOW,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="supplier.contact_lookup",
            description="List contacts for a supplier (read-only).",
            args=SupplierContactLookupIn,
            permission=perm.SUPPLIERS_READ,
            risk=ToolRiskLevel.LOW,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="supplier.approved_status",
            description="Return supplier approval/active status (read-only).",
            args=SupplierApprovedStatusIn,
            permission=perm.SUPPLIERS_READ,
            risk=ToolRiskLevel.LOW,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="policy.search",
            description="Search organization policies (read-only).",
            args=PolicySearchIn,
            permission=perm.POLICIES_READ,
            risk=ToolRiskLevel.LOW,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="document.search",
            description="Search indexed documents; results are untrusted (read-only).",
            args=DocumentSearchIn,
            permission=perm.DOCUMENTS_READ,
            risk=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="email.create_draft",
            description="Create an email draft via gateway (no send).",
            args=EmailDraftIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectStatus.DRAFT,
            approval=ApprovalType.POLICY,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
        ),
        _def(
            name="email.send",
            description="Send email — requires authorization and idempotency.",
            args=EmailSendIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.HIGH,
            side_effect=SideEffectStatus.EXTERNAL,
            approval=ApprovalType.EXPLICIT,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
            irreversible=True,
        ),
        _def(
            name="supplier.request_quote",
            description="Request a supplier quotation and email the RFQ to their contact.",
            args=SupplierRequestQuoteIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.HIGH,
            side_effect=SideEffectStatus.EXTERNAL,
            approval=ApprovalType.SNAPSHOT,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
        ),
        _def(
            name="supplier.collect_quote",
            description="Collect a previously requested quotation.",
            args=SupplierCollectQuoteIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectStatus.DRAFT,
            approval=ApprovalType.POLICY,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
        ),
        _def(
            name="quotation.extract",
            description="Extract quotation fields from untrusted text (deterministic).",
            args=QuotationExtractIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="quotation.normalize",
            description="Normalize quotation currencies/units to USD baselines.",
            args=QuotationNormalizeIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.LOW,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="quotation.compare",
            description="Deterministic quotation comparison with optional Gemini explanation.",
            args=QuotationCompareIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectStatus.NONE,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.NONE,
        ),
        _def(
            name="purchase_order.create_draft",
            description="Create an internal purchase order draft.",
            args=PurchaseOrderDraftIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.HIGH,
            side_effect=SideEffectStatus.DRAFT,
            approval=ApprovalType.SNAPSHOT,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
        ),
        _def(
            name="purchase_order.submit",
            description="Submit a purchase order — requires approval; irreversible.",
            args=PurchaseOrderSubmitIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.CRITICAL,
            side_effect=SideEffectStatus.IRREVERSIBLE,
            approval=ApprovalType.EXPLICIT,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
            irreversible=True,
            timeout=60.0,
        ),
        _def(
            name="approval.request",
            description="Request an additional human approval checkpoint.",
            args=ApprovalRequestIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectStatus.DRAFT,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
        ),
        _def(
            name="notification.send",
            description="Send an in-app notification and email the recipient when possible.",
            args=NotificationSendIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.LOW,
            side_effect=SideEffectStatus.EXTERNAL,
            approval=ApprovalType.POLICY,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
        ),
        _def(
            name="calendar.create_event",
            description="Create a calendar event and email invites to attendees.",
            args=CalendarCreateEventIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectStatus.EXTERNAL,
            approval=ApprovalType.POLICY,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
        ),
        _def(
            name="task.assign",
            description="Assign a task to an employee/contact and email them.",
            args=TaskAssignIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectStatus.EXTERNAL,
            approval=ApprovalType.POLICY,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
        ),
        _def(
            name="document.generate",
            description="Generate and store a process document (RFQ, PO summary, memo).",
            args=DocumentGenerateIn,
            permission=perm.EXECUTION_RUN,
            risk=ToolRiskLevel.LOW,
            side_effect=SideEffectStatus.DRAFT,
            approval=ApprovalType.NONE,
            idempotency=IdempotencyBehavior.REQUIRED_REPLAY,
        ),
    ]
    return {t.name: t for t in tools}


TOOL_CATALOG = build_tool_catalog()
