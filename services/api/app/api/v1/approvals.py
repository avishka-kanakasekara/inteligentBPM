"""Approval endpoints."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.audit import AuditService
from app.auth.deps import (
    OrganizationContext,
    get_current_user,
    ignore_client_organization_id,
    require_permission,
)
from app.contracts.common import Page, utcnow
from app.contracts.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    ApprovalSummaryResponse,
    RiskItem,
    SourceRef,
)
from app.database.memory import ApprovalRecord, get_memory_store, new_id
from app.domain.enums import ApprovalStatus
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.repositories.memory_repos import ApprovalRepository, ProcessRepository
from app.repositories.query import ListParams, apply_list, list_params
from app.security.jwt import AuthenticatedUser

router = APIRouter(prefix="/approvals", tags=["approvals"])


def seed_approval(
    *,
    organization_id: UUID,
    snapshot_hash: str = "snap",
    snapshot_payload: dict[str, Any] | None = None,
) -> ApprovalRecord:
    store = get_memory_store()
    now = utcnow()
    record = ApprovalRecord(
        id=new_id(),
        organization_id=organization_id,
        process_run_id=None,
        status=ApprovalStatus.PENDING,
        snapshot_hash=snapshot_hash,
        snapshot_payload=snapshot_payload or {},
        decided_by_user_id=None,
        decision_note=None,
        row_version=1,
        created_at=now,
        updated_at=now,
    )
    store.approvals[record.id] = record
    return record


def _as_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _risk_level_from_items(items: list[dict[str, Any]], decision: str | None) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    best = "low"
    for item in items:
        severity = str(item.get("severity") or "low").lower()
        if order.get(severity, 0) > order.get(best, 0):
            best = severity
    if decision == "BLOCKED" and order.get(best, 0) < order["critical"]:
        return "critical"
    if decision == "APPROVAL_REQUIRED" and best == "low":
        return "medium"
    return best


def _build_approval_summary(a: ApprovalRecord, org_id: UUID) -> ApprovalSummaryResponse:
    payload = a.snapshot_payload if isinstance(a.snapshot_payload, dict) else {}
    process_id = a.process_id or _as_uuid(payload.get("process_id"))
    process_name = ""
    if process_id is not None:
        try:
            process_name = ProcessRepository(org_id).get(process_id).name
        except Exception:
            process_name = f"Process {str(process_id)[:8]}"

    risk_decision = None
    if payload.get("decision"):
        risk_decision = str(payload["decision"]).upper()
    elif a.decision:
        risk_decision = str(a.decision).upper()

    plan_hash = a.plan_snapshot_hash or payload.get("plan_snapshot_hash")
    risk_hash = a.risk_snapshot_hash or payload.get("risk_snapshot_hash")
    required_roles = list(a.required_roles or payload.get("required_roles") or [])

    raw_items = payload.get("risk_items") or []
    risk_items: list[RiskItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        policy_ref = item.get("policy_reference") if isinstance(item.get("policy_reference"), dict) else {}
        risk_items.append(
            RiskItem(
                id=str(item.get("id") or "risk"),
                category=str(item.get("category") or "general"),
                severity=str(item.get("severity") or "medium"),
                description=str(item.get("description") or ""),
                blocking=bool(item.get("blocking")),
                required_remediation=str(
                    item.get("required_remediation") or item.get("remediation") or "Review required"
                ),
                required_approver=(
                    str(item["required_approver"]) if item.get("required_approver") else None
                ),
                policy_code=(
                    str(policy_ref.get("policy_code") or item.get("policy_code") or "")
                    or None
                ),
            )
        )

    policy_evidence: list[str] = []
    for ev in payload.get("policy_evidence") or []:
        if isinstance(ev, dict):
            label = ev.get("label") or ev.get("title") or ev.get("policy_code") or ev.get("id")
            if label:
                policy_evidence.append(str(label))
        else:
            policy_evidence.append(str(ev))

    source_refs: list[SourceRef] = []
    for ref in payload.get("source_refs") or []:
        if isinstance(ref, dict):
            source_refs.append(
                SourceRef(
                    type=str(ref.get("type") or "document"),
                    id=str(ref.get("id") or ""),
                    label=str(ref.get("label") or ref.get("title") or ref.get("id") or ""),
                )
            )

    blocking = payload.get("blocking_issues") or []
    blocking_explanation = None
    if risk_decision == "BLOCKED":
        if blocking and isinstance(blocking[0], dict):
            blocking_explanation = str(blocking[0].get("description") or "Blocked by policy")
        else:
            blocking_explanation = a.decision_note or "Blocked by deterministic policy rules"

    if risk_decision:
        risk_summary = (
            f"Deterministic decision: {risk_decision}"
            + (f" — {len(risk_items)} risk item(s)" if risk_items else "")
            + (f"; roles: {', '.join(required_roles)}" if required_roles else "")
        )
    elif a.decision_note:
        risk_summary = a.decision_note
    else:
        risk_summary = "Risk analysis pending or unavailable."

    return ApprovalSummaryResponse(
        id=a.id,
        process_id=process_id,
        process_name=process_name or "Unknown process",
        status=a.status.value if hasattr(a.status, "value") else str(a.status),
        risk_level=_risk_level_from_items(
            [i.model_dump() for i in risk_items],
            risk_decision,
        ),
        risk_decision=risk_decision,
        required_roles=required_roles,
        snapshot_hash=a.snapshot_hash,
        plan_snapshot_hash=str(plan_hash) if plan_hash else a.snapshot_hash,
        risk_snapshot_hash=str(risk_hash) if risk_hash else a.snapshot_hash,
        policy_evidence=policy_evidence,
        source_refs=source_refs,
        decision_note=a.decision_note,
        risk_summary=risk_summary,
        risk_items=risk_items,
        blocking_explanation=blocking_explanation,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


@router.get("/summaries", response_model=list[ApprovalSummaryResponse])
async def list_approval_summaries(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.APPROVALS_READ))],
) -> list[ApprovalSummaryResponse]:
    """Return all approvals as flat summary list for the frontend."""
    items = ApprovalRepository(org.organization_id).list_all()
    items.sort(key=lambda a: a.updated_at, reverse=True)
    return [_build_approval_summary(a, org.organization_id) for a in items]


@router.get("", response_model=Page[ApprovalResponse])
async def list_approvals(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.APPROVALS_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[ApprovalResponse]:
    items = ApprovalRepository(org.organization_id).list_all()
    page = apply_list(
        items,
        params,
        status_getter=lambda a: a.status.value,
        sort_fields={"created_at": lambda a: a.created_at},
    )
    return Page(
        items=[ApprovalResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.APPROVALS_READ))],
) -> ApprovalResponse:
    record = ApprovalRepository(org.organization_id).get(approval_id)
    return ApprovalResponse.model_validate(record, from_attributes=True)


@router.post("/{approval_id}/decision", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.APPROVALS_DECIDE))],
) -> ApprovalResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = ApprovalRepository(org.organization_id).decide(
        approval_id,
        decision=body.decision,
        decided_by_user_id=user.id,
        note=body.note,
        expected_row_version=body.row_version,
    )
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="approval.decided",
        resource_type="approval",
        resource_id=record.id,
        correlation_id=get_correlation_id(request),
        payload={"decision": body.decision, "note": body.note},
    )
    return ApprovalResponse.model_validate(record, from_attributes=True)
