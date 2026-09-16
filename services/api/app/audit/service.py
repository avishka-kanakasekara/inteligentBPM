"""Audit event service."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.repositories.memory_repos import AuditRepository


class AuditService:
    def __init__(self, repo: AuditRepository | None = None) -> None:
        self.repo = repo or AuditRepository()

    def record(
        self,
        *,
        organization_id: UUID,
        actor_user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None = None,
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        # Never include secrets in payload.
        safe_payload = {
            key: value
            for key, value in (payload or {}).items()
            if key.lower() not in {"token", "secret", "password", "api_key", "authorization"}
        }
        self.repo.append(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            payload=safe_payload,
        )
