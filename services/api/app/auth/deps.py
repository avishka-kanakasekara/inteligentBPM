"""Auth dependencies: current user, organization context, permissions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.domain.enums import OrgRole
from app.permissions.codes import permissions_for_role
from app.repositories.memory_repos import MembershipRepository, OrganizationRepository
from app.security.errors import AppError
from app.security.jwt import (
    AuthenticatedUser,
    AuthenticationError,
    AuthorizationError,
    TenantMismatchError,
    validate_supabase_jwt,
)

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class OrganizationContext:
    organization_id: UUID
    role: OrgRole
    permissions: frozenset[str]
    membership_id: UUID

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise AuthorizationError(f"Missing permission: {permission}")


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    # Do not treat invalid/expired API bearer tokens as login-abuse failures.
    # That incorrectly lockouts local IP after a stale browser session refresh storm.
    token: str | None = None
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    elif request.query_params.get("access_token"):
        # EventSource/SSE cannot send Authorization headers.
        token = request.query_params.get("access_token")

    if not token:
        raise AuthenticationError()
    return validate_supabase_jwt(token, settings)


async def get_optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser | None:
    if credentials is None:
        return None
    return await get_current_user(request, credentials, settings)


def _resolve_org_id(
    settings: Settings,
    x_organization_id: str | None,
    client_organization_id: UUID | None,
) -> UUID | None:
    header_value = x_organization_id
    if header_value:
        try:
            header_org = UUID(header_value)
        except ValueError as exc:
            raise AppError(
                "Invalid X-Organization-Id header",
                code="VALIDATION_ERROR",
                status_code=422,
            ) from exc
        if client_organization_id is not None and client_organization_id != header_org:
            raise TenantMismatchError(
                "Client-provided organization_id does not match authenticated organization context"
            )
        return header_org
    return client_organization_id


async def get_current_organization(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_organization_id: Annotated[str | None, Header(alias="X-Organization-Id")] = None,
) -> OrganizationContext:
    # Ignore body/query organization_id unless it matches header/context.
    query_org = request.query_params.get("organization_id")
    client_org: UUID | None = None
    if query_org:
        try:
            client_org = UUID(query_org)
        except ValueError as exc:
            raise AppError(
                "Invalid organization_id query parameter",
                code="VALIDATION_ERROR",
                status_code=422,
            ) from exc

    if client_org is None and request.path_params.get("organization_id"):
        try:
            client_org = UUID(str(request.path_params["organization_id"]))
        except ValueError as exc:
            raise AppError(
                "Invalid organization_id path parameter",
                code="VALIDATION_ERROR",
                status_code=422,
            ) from exc

    org_id = _resolve_org_id(settings, x_organization_id, client_org)
    if org_id is None:
        raise AppError(
            "Organization context required via X-Organization-Id",
            code="TENANT_CONTEXT_REQUIRED",
            status_code=400,
        )

    membership = MembershipRepository().get_active(org_id, user.id)
    if membership is None:
        raise AuthorizationError("Not a member of this organization")

    org = OrganizationRepository().get(org_id)
    if org is None:
        raise AuthorizationError("Organization not found or inaccessible")

    return OrganizationContext(
        organization_id=org_id,
        role=membership.role,
        permissions=permissions_for_role(membership.role),
        membership_id=membership.id,
    )


def require_permission(permission: str) -> Callable[..., Any]:
    async def _dependency(
        org: Annotated[OrganizationContext, Depends(get_current_organization)],
    ) -> OrganizationContext:
        org.require(permission)
        return org

    return _dependency


def ignore_client_organization_id(
    authenticated_org_id: UUID,
    client_organization_id: UUID | None,
) -> UUID:
    """Return authenticated org id; reject mismatched client-provided values."""
    if client_organization_id is not None and client_organization_id != authenticated_org_id:
        raise TenantMismatchError(
            "Client-provided organization_id does not match authenticated organization context"
        )
    return authenticated_org_id
