"""Organization endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.audit import AuditService
from app.auth.deps import (
    OrganizationContext,
    get_current_organization,
    get_current_user,
    ignore_client_organization_id,
    require_permission,
)
from app.contracts.schemas import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationSummary,
    OrganizationUpdate,
)
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.repositories.memory_repos import OrganizationRepository
from app.security.errors import NotFoundError
from app.security.jwt import AuthenticatedUser, AuthorizationError
from app.services.org_management import OrganizationProfileService

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _to_response(org: object) -> OrganizationResponse:
    return OrganizationResponse.model_validate(org, from_attributes=True)


@router.post("", response_model=OrganizationSummary, status_code=201)
async def create_organization(
    body: OrganizationCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> OrganizationSummary:
    # Client organization_id on create is ignored (new org gets server id).
    org = OrganizationRepository().create(
        name=body.name,
        plan_code=body.plan_code,
        owner_user_id=user.id,
    )
    AuditService().record(
        organization_id=org.id,
        actor_user_id=user.id,
        action="organization.created",
        resource_type="organization",
        resource_id=org.id,
        correlation_id=get_correlation_id(request),
        payload={"name": org.name, "plan_code": org.plan_code},
    )
    return OrganizationSummary(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan_code=org.plan_code,
        status=org.status,
        membership_role="owner",
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


@router.get("", response_model=list[OrganizationSummary])
async def list_organizations(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[OrganizationSummary]:
    rows = OrganizationRepository().list_for_user(user.id)
    return [
        OrganizationSummary(
            id=org.id,
            name=org.name,
            slug=org.slug,
            plan_code=org.plan_code,
            status=org.status,
            membership_role=membership.role.value,
            created_at=org.created_at,
            updated_at=org.updated_at,
        )
        for org, membership in rows
    ]


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
    org_ctx: Annotated[OrganizationContext, Depends(get_current_organization)],
) -> OrganizationResponse:
    if organization_id != org_ctx.organization_id:
        raise AuthorizationError("Cannot access another organization")
    org = OrganizationProfileService().get(organization_id)
    return _to_response(org)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def patch_organization(
    organization_id: UUID,
    body: OrganizationUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org_ctx: Annotated[OrganizationContext, Depends(require_permission(perm.ORG_CONFIGURE))],
) -> OrganizationResponse:
    if organization_id != org_ctx.organization_id:
        raise AuthorizationError("Cannot modify another organization")
    ignore_client_organization_id(org_ctx.organization_id, body.organization_id)
    if body.row_version is not None:
        current = OrganizationRepository().get(organization_id)
        if current is None:
            raise NotFoundError("Organization not found")
        if current.row_version != body.row_version:
            from app.security.errors import ConflictError

            raise ConflictError(
                "Organization version conflict",
                code="PROCESS_VERSION_CONFLICT",
                details={"row_version": current.row_version},
            )
    payload = body.model_dump(exclude_unset=True, exclude={"organization_id", "row_version"})
    org = OrganizationProfileService().update_profile(
        organization_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
        **payload,
    )
    return _to_response(org)
