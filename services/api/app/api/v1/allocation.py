"""Agent 2 allocation API — bind plan steps to org resources."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.agents.allocation.models import ClarificationChoice, ResourceAllocationRequest
from app.agents.allocation.service import AllocationService
from app.auth.deps import (
    OrganizationContext,
    get_current_user,
    ignore_client_organization_id,
    require_permission,
)
from app.contracts.schemas import AllocateResourcesRequest, AllocateResourcesResponse
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.security.errors import NotFoundError
from app.security.jwt import AuthenticatedUser

router = APIRouter(prefix="/processes", tags=["allocation"])

_NOT_RUN_VERSION = UUID("00000000-0000-0000-0000-000000000000")


def _to_response(result: object) -> AllocateResourcesResponse:
    data = result.model_dump(mode="json")  # type: ignore[attr-defined]
    return AllocateResourcesResponse.model_validate(data)


def _empty_allocation(org_id: UUID, process_id: UUID) -> AllocateResourcesResponse:
    return AllocateResourcesResponse(
        organization_id=org_id,
        process_id=process_id,
        process_version_id=_NOT_RUN_VERSION,
        status="not_run",
        reasoning_summary="Agent 2 has not been run yet.",
    )


@router.post("/{process_id}/allocate", response_model=AllocateResourcesResponse)
async def allocate_resources(
    process_id: UUID,
    body: AllocateResourcesRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> AllocateResourcesResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    choices = [ClarificationChoice.model_validate(c) for c in body.clarification_choices]
    alloc_request = ResourceAllocationRequest(
        process_id=process_id,
        process_version_id=body.process_version_id,
        clarification_choices=choices,
        notes=body.notes,
    )
    service = AllocationService(org.organization_id)
    result = service.allocate(
        process_id,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
        permissions=org.permissions,
        request=alloc_request,
    )
    return _to_response(result)


@router.get("/{process_id}/allocation", response_model=AllocateResourcesResponse)
async def get_allocation(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> AllocateResourcesResponse:
    service = AllocationService(org.organization_id)
    try:
        result = service.get_allocation(process_id)
    except NotFoundError:
        return _empty_allocation(org.organization_id, process_id)
    return _to_response(result)