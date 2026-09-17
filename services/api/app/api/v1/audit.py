"""Audit event listing endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.deps import OrganizationContext, require_permission
from app.contracts.common import APIModel, Page, PageMeta
from app.permissions import codes as perm
from app.repositories.memory_repos import AuditRepository

router = APIRouter(prefix="/audit-events", tags=["audit"])


class AuditEventResponse(APIModel):
    id: UUID
    organization_id: UUID
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    correlation_id: str | None
    payload: dict[str, Any]
    created_at: datetime
    result: str | None = None


def _result_from_payload(payload: dict[str, Any]) -> str | None:
    for key in ("result", "status", "decision", "outcome"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


@router.get("", response_model=Page[AuditEventResponse])
async def list_audit_events(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.AUDIT_READ))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: Annotated[str | None, Query()] = None,
) -> Page[AuditEventResponse]:
    events = AuditRepository().list_for_org(org.organization_id)
    events = sorted(events, key=lambda e: e.created_at, reverse=True)
    if action:
        needle = action.strip().lower()
        events = [e for e in events if needle in e.action.lower()]
    total = len(events)
    page_items = events[offset : offset + limit]
    return Page(
        items=[
            AuditEventResponse(
                id=event.id,
                organization_id=event.organization_id,
                actor_user_id=event.actor_user_id,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                correlation_id=event.correlation_id,
                payload=event.payload,
                created_at=event.created_at,
                result=_result_from_payload(event.payload),
            )
            for event in page_items
        ],
        meta=PageMeta(total=total, limit=limit, offset=offset, order="desc"),
    )
