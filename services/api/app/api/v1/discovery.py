"""Agent 1 discovery API — chat, draft plans, confirm, SSE."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.agents.discovery.service import DiscoveryService
from app.auth.deps import (
    OrganizationContext,
    get_current_user,
    ignore_client_organization_id,
    require_permission,
)
from app.contracts.common import APIModel
from app.contracts.schemas import (
    ConfirmPlanResponse,
    DiscoveryChatHistoryResponse,
    DiscoveryChatMessageResponse,
    DiscoveryChatRequest,
    DraftPlanRequest,
    DraftPlanResponse,
)
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.security.jwt import AuthenticatedUser

router = APIRouter(prefix="/processes", tags=["discovery"])


def _message_response(msg: Any) -> DiscoveryChatMessageResponse:
    if hasattr(msg, "model_dump"):
        data = msg.model_dump(mode="json")
        return DiscoveryChatMessageResponse.model_validate(data)
    return DiscoveryChatMessageResponse(
        id=msg.id,
        organization_id=msg.organization_id,
        process_id=msg.process_id,
        session_id=msg.session_id,
        role=msg.role,
        content=msg.content,
        document_ids=list(msg.document_ids),
        clarifying_questions=list(msg.clarifying_questions),
        intent=msg.intent,
        plan_draft=msg.plan_draft,
        source_refs=list(msg.source_refs),
        suspicious_flags=list(msg.suspicious_flags),
        created_by_user_id=msg.created_by_user_id,
        created_at=msg.created_at,
    )


@router.post("/{process_id}/chat", response_model=DiscoveryChatMessageResponse)
async def discovery_chat(
    process_id: UUID,
    body: DiscoveryChatRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> DiscoveryChatMessageResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    service = DiscoveryService(org.organization_id)
    message = service.chat(
        process_id,
        message=body.message,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
        document_ids=body.document_ids,
        permissions=org.permissions,
    )
    return _message_response(message)


@router.get("/{process_id}/chat", response_model=DiscoveryChatHistoryResponse)
async def get_discovery_chat(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> DiscoveryChatHistoryResponse:
    service = DiscoveryService(org.organization_id)
    session = service.get_or_create_session(process_id, user_id=user.id)
    messages = service.list_messages(process_id)
    return DiscoveryChatHistoryResponse(
        session_id=session.id,
        messages=[_message_response(m) for m in messages],
    )


@router.get("/{process_id}/chat/stream")
async def stream_discovery_chat(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> StreamingResponse:
    service = DiscoveryService(org.organization_id)

    async def event_generator() -> Any:
        for chunk in service.iter_sse(process_id):
            yield chunk
            await asyncio.sleep(0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{process_id}/draft-plan", response_model=DraftPlanResponse, status_code=201)
async def draft_plan(
    process_id: UUID,
    body: DraftPlanRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> DraftPlanResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    service = DiscoveryService(org.organization_id)
    result = service.draft_plan(
        process_id,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
        permissions=org.permissions,
        revision_of_version_id=body.revision_of_version_id,
        document_ids=body.document_ids,
        instructions=body.instructions,
    )
    plan = result["plan"]
    plan_dict = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
    return DraftPlanResponse(
        version_id=result["version_id"],
        version_number=result["version_number"],
        status=result["status"],
        plan=plan_dict,
        plan_snapshot_hash=result["plan_snapshot_hash"],
    )


@router.post("/{process_id}/plan", response_model=DraftPlanResponse, status_code=201, include_in_schema=False)
async def draft_plan_legacy(
    process_id: UUID,
    body: DraftPlanRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> DraftPlanResponse:
    """Backward-compatible alias for older clients."""
    return await draft_plan(process_id, body, request, user, org)


@router.post(
    "/{process_id}/versions/{version_id}/confirm",
    response_model=ConfirmPlanResponse,
)
async def confirm_plan_version(
    process_id: UUID,
    version_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> ConfirmPlanResponse:
    service = DiscoveryService(org.organization_id)
    result = service.confirm_version(
        process_id,
        version_id,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    plan = result["plan"]
    plan_dict = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
    return ConfirmPlanResponse(
        version_id=result["version_id"],
        version_number=result["version_number"],
        status=result["status"],
        confirmed_at=result["confirmed_at"],
        plan=plan_dict,
    )


class _LegacyConfirmPlanRequest(APIModel):
    version_id: UUID


@router.post("/{process_id}/plan/confirm", response_model=ConfirmPlanResponse, include_in_schema=False)
async def confirm_plan_legacy(
    process_id: UUID,
    body: _LegacyConfirmPlanRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CREATE))],
) -> ConfirmPlanResponse:
    """Backward-compatible alias for older clients."""
    return await confirm_plan_version(process_id, body.version_id, request, user, org)
