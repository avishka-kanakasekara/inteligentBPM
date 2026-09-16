"""Agent 3 risk analysis API."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.agents.risk.models import AnalyzeRiskRequest, OverrideRequest
from app.agents.risk.service import RiskAnalysisService
from app.auth.deps import (
    OrganizationContext,
    get_current_user,
    require_permission,
)
from app.contracts.schemas import (
    ApprovalResponse,
    RiskAnalyzeRequest,
    RiskResultResponse,
)
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.security.errors import NotFoundError
from app.security.jwt import AuthenticatedUser

router = APIRouter(prefix="/processes", tags=["risk"])

_NOT_RUN_VERSION = UUID("00000000-0000-0000-0000-000000000000")


def _risk_response(result: Any) -> RiskResultResponse:
    return RiskResultResponse.model_validate(result.model_dump(mode="json"))


def _empty_risk(org_id: UUID, process_id: UUID) -> RiskResultResponse:
    return RiskResultResponse(
        organization_id=org_id,
        process_id=process_id,
        process_version_id=_NOT_RUN_VERSION,
        decision="INSUFFICIENT_INFORMATION",
        overall_status="not_run",
        plan_snapshot_hash="",
        risk_snapshot_hash="",
        reasoning_summary="Agent 3 has not been run yet.",
        valid=False,
        invalidated_reason="not_run",
    )


@router.post("/{process_id}/analyze-risk", response_model=RiskResultResponse)
async def analyze_risk(
    process_id: UUID,
    body: RiskAnalyzeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> RiskResultResponse:
    service = RiskAnalysisService(org.organization_id)
    result = service.analyze(
        process_id,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
        permissions=org.permissions,
        request=AnalyzeRiskRequest(
            process_version_id=body.process_version_id,
            allocation_id=body.allocation_id,
            spending_amount=body.spending_amount,
            quotation_count=body.quotation_count,
            geographic_region=body.geographic_region,
            handles_restricted_data=body.handles_restricted_data,
            notes=body.notes,
        ),
    )
    return _risk_response(result)


@router.get("/{process_id}/risk", response_model=RiskResultResponse)
async def get_risk(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> RiskResultResponse:
    service = RiskAnalysisService(org.organization_id)
    try:
        return _risk_response(service.get_risk(process_id))
    except NotFoundError:
        return _empty_risk(org.organization_id, process_id)

@router.post("/{process_id}/approvals", response_model=ApprovalResponse, status_code=201)
async def create_process_approval(
    process_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.APPROVALS_DECIDE))],
) -> ApprovalResponse:
    service = RiskAnalysisService(org.organization_id)
    record = service.create_approval_package(
        process_id,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return ApprovalResponse.model_validate(record, from_attributes=True)


@router.post("/{process_id}/risk/analyze", response_model=RiskResultResponse, include_in_schema=False)
async def analyze_risk_legacy(
    process_id: UUID,
    body: RiskAnalyzeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> RiskResultResponse:
    """Backward-compatible alias for older clients."""
    return await analyze_risk(process_id, body, request, user, org)


@router.post("/{process_id}/approval", response_model=ApprovalResponse, status_code=201, include_in_schema=False)
async def create_process_approval_legacy(
    process_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.APPROVALS_DECIDE))],
) -> ApprovalResponse:
    """Backward-compatible alias for older clients."""
    return await create_process_approval(process_id, request, user, org)


@router.post(
    "/{process_id}/approvals/override",
    response_model=ApprovalResponse,
    status_code=201,
)
async def request_blocked_override(
    process_id: UUID,
    body: OverrideRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.ORG_CONFIGURE))],
) -> ApprovalResponse:
    """Audited override for BLOCKED decisions — requires org.configure authorization."""
    service = RiskAnalysisService(org.organization_id)
    record = service.request_override(
        process_id,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
        justification=body.justification,
        acknowledged_risk_item_ids=body.acknowledged_risk_item_ids,
        authorized=True,
    )
    return ApprovalResponse.model_validate(record, from_attributes=True)
