"""Tenant-scoped repository base utilities."""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from app.security.errors import NotFoundError
from app.security.jwt import TenantMismatchError

T = TypeVar("T")


class TenantScopedRepository:
    """Base helpers ensuring every access is bound to organization_id."""

    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id

    def ensure_same_tenant(self, record_organization_id: UUID) -> None:
        if record_organization_id != self.organization_id:
            raise TenantMismatchError(
                "Resource does not belong to the authenticated organization context"
            )

    def require(
        self,
        record: T | None,
        *,
        record_organization_id: UUID | None = None,
        message: str = "Resource not found",
    ) -> T:
        if record is None:
            raise NotFoundError(message)
        if record_organization_id is not None and record_organization_id != self.organization_id:
            # Do not leak cross-tenant existence.
            raise NotFoundError(message)
        return record
