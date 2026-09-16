"""Process definition and version endpoints."""

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
from app.contracts.common import Page
from app.contracts.schemas import (
    ProcessCreate,
    ProcessResponse,
    ProcessSummaryResponse,
    ProcessVersionCreate,
    ProcessVersionResponse,
)
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.repositories.memory_repos import ProcessRepository
from app.repositories.query import ListParams, apply_list, list_params
from app.security.jwt import AuthenticatedUser

router = APIRouter(prefix="/processes", tags=["processes"])

_RISK_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _risk_level_from_snapshot(snapshot: dict[str, Any]) -> str | None:
    """Map Agent 3 output to frontend risk levels (low|medium|high|critical)."""
    items = snapshot.get("risk_items") or []
    best: str | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "low").lower()
        if severity not in _RISK_LEVEL_ORDER:
            continue
        if best is None or _RISK_LEVEL_ORDER[severity] > _RISK_LEVEL_ORDER[best]:
            best = severity
    if best:
        return best
    decision = str(snapshot.get("decision") or "").lower()
    if decision == "blocked":
        return "critical"
    if decision == "approval_required":
        return "high"
    if decision == "insufficient_information":
        return "medium"
    if decision == "clear":
        return "low"
    return None


def _build_process_summary(p: Any, org_id: UUID) -> ProcessSummaryResponse:
    from app.database.memory import get_memory_store

    store = get_memory_store()
    versions = ProcessRepository(org_id).list_versions(p.id)
    latest_version = max(versions, key=lambda v: v.version_number) if versions else None
    plan_snapshot = (latest_version.plan_snapshot if latest_version else {}) or {}

    missing_info = [
        m.get("question") if isinstance(m, dict) else str(m)
        for m in (plan_snapshot.get("missing_information") or [])
    ]

    risk_records = [
        r
        for r in store.risk_results.values()
        if r.organization_id == org_id and r.process_id == p.id
    ]
    latest_risk = max(risk_records, key=lambda r: r.updated_at) if risk_records else None
    risk_level = None
    if latest_risk:
        risk_snap = latest_risk.result_snapshot or {}
        risk_level = _risk_level_from_snapshot(risk_snap)

    approvals = [
        a
        for a in store.approvals.values()
        if a.organization_id == org_id and getattr(a, "process_id", None) == p.id
    ]
    latest_app = max(approvals, key=lambda a: a.updated_at) if approvals else None
    approval_status = (
        latest_app.status.value
        if latest_app and hasattr(latest_app.status, "value")
        else (str(latest_app.status) if latest_app else None)
    )

    runs = [
        r
        for r in store.process_runs.values()
        if r.organization_id == org_id and r.process_id == p.id
    ]
    latest_run = max(runs, key=lambda r: r.updated_at) if runs else None
    exec_status = (
        latest_run.status.value
        if latest_run and hasattr(latest_run.status, "value")
        else None
    )

    alloc_records = [
        a
        for a in store.allocations.values()
        if a.organization_id == org_id and a.process_id == p.id
    ]
    latest_alloc = max(alloc_records, key=lambda a: a.updated_at) if alloc_records else None
    unresolved: list[str] = []
    recommendations: list[str] = []
    if latest_alloc and latest_alloc.result_snapshot:
        snap = latest_alloc.result_snapshot
        for item in snap.get("unresolved") or snap.get("unresolved_assignments") or []:
            if isinstance(item, dict):
                unresolved.append(str(item.get("reason") or item.get("requirement") or item.get("question") or item.get("step_id") or item))
            else:
                unresolved.append(str(item))
        for item in snap.get("recommendations") or []:
            recommendations.append(str(item))
        for item in snap.get("assignments") or []:
            if isinstance(item, dict):
                name = item.get("display_name") or item.get("resource_id")
                req = item.get("requirement") or item.get("resource_type") or "resource"
                if name:
                    recommendations.append(f"{req} → {name}")

    policy_evidence: list[str] = []
    if latest_risk and latest_risk.result_snapshot:
        for item in latest_risk.result_snapshot.get("policy_evidence") or []:
            policy_evidence.append(str(item))

    source_refs: list[dict[str, str]] = []
    for ref in plan_snapshot.get("source_refs") or []:
        if isinstance(ref, dict):
            source_refs.append(
                {
                    "type": str(ref.get("type") or "document"),
                    "id": str(ref.get("id") or ""),
                    "label": str(ref.get("label") or ref.get("title") or ref.get("id") or ""),
                }
            )

    human_decision = None
    if latest_app and latest_app.decision:
        human_decision = str(latest_app.decision)

    return ProcessSummaryResponse(
        id=p.id,
        name=p.name,
        status=p.status,
        risk_level=risk_level,
        approval_status=approval_status,
        execution_status=exec_status,
        missing_information=missing_info,
        unresolved_assignments=unresolved,
        policy_evidence=policy_evidence,
        source_refs=source_refs,
        recommendations=recommendations,
        human_decision=human_decision,
        has_allocation=latest_alloc is not None,
        has_risk=latest_risk is not None,
        has_execution=latest_run is not None,
        updated_at=p.updated_at,
    )


@router.get("/summaries", response_model=list[ProcessSummaryResponse])
async def list_process_summaries(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> list[ProcessSummaryResponse]:
    """Return all processes as flat summary list for the frontend dashboard."""
    items = ProcessRepository(org.organization_id).list_all()
    return [_build_process_summary(p, org.organization_id) for p in items]


@router.get("/summaries/{process_id}", response_model=ProcessSummaryResponse)
async def get_process_summary(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> ProcessSummaryResponse:
    """Return a single process as summary for the frontend."""
    record = ProcessRepository(org.organization_id).get(process_id)
    return _build_process_summary(record, org.organization_id)


@router.post("", response_model=ProcessSummaryResponse, status_code=201)
async def create_process(
    body: ProcessCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> ProcessSummaryResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    from app.billing.service import EntitlementService

    active = sum(
        1
        for p in ProcessRepository(org.organization_id).list_all()
        if p.status not in {"archived", "deleted"}
    )
    EntitlementService().assert_within_limit(
        org.organization_id,
        "process.max_active_definitions",
        current_usage=active,
        increment=1,
    )
    record = ProcessRepository(org.organization_id).create(
        name=body.name,
        description=body.description,
        created_by_user_id=user.id,
    )
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="process.created",
        resource_type="process",
        resource_id=record.id,
        correlation_id=get_correlation_id(request),
    )
    return _build_process_summary(record, org.organization_id)


@router.get("", response_model=Page[ProcessResponse])
async def list_processes(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[ProcessResponse]:
    items = ProcessRepository(org.organization_id).list_all()
    page = apply_list(
        items,
        params,
        search_fields=[lambda p: p.name, lambda p: p.description],
        status_getter=lambda p: p.status,
        sort_fields={"name": lambda p: p.name, "created_at": lambda p: p.created_at},
    )
    return Page(
        items=[ProcessResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )


@router.get("/{process_id}", response_model=ProcessResponse)
async def get_process(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> ProcessResponse:
    record = ProcessRepository(org.organization_id).get(process_id)
    return ProcessResponse.model_validate(record, from_attributes=True)


@router.post("/{process_id}/versions", response_model=ProcessVersionResponse, status_code=201)
async def create_process_version(
    process_id: UUID,
    body: ProcessVersionCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> ProcessVersionResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = ProcessRepository(org.organization_id).create_version(
        process_id,
        plan_snapshot=body.plan_snapshot,
    )
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="process_version.created",
        resource_type="process_version",
        resource_id=record.id,
        correlation_id=get_correlation_id(request),
        payload={"process_id": str(process_id), "version_number": record.version_number},
    )
    return ProcessVersionResponse.model_validate(record, from_attributes=True)


@router.get("/{process_id}/versions", response_model=Page[ProcessVersionResponse])
async def list_process_versions(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[ProcessVersionResponse]:
    items = ProcessRepository(org.organization_id).list_versions(process_id)
    page = apply_list(
        items,
        params,
        status_getter=lambda v: v.status,
        sort_fields={
            "version_number": lambda v: v.version_number,
            "created_at": lambda v: v.created_at,
        },
    )
    return Page(
        items=[ProcessVersionResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )
