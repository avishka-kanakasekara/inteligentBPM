"""Auth endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.deps import get_current_user
from app.contracts.schemas import OrganizationSummary, UserMeResponse
from app.repositories.memory_repos import OrganizationRepository
from app.security.jwt import AuthenticatedUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserMeResponse)
async def get_me(user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> UserMeResponse:
    return UserMeResponse(id=user.id, email=user.email, role=user.role)


@router.get("/organizations", response_model=list[OrganizationSummary])
async def list_my_organizations(
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
