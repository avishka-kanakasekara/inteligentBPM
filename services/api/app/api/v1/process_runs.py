"""Process run endpoints including SSE event stream and durable workflow controls."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from app.audit import AuditService
from app.auth.deps import (
    OrganizationContext,
    get_current_user,
    ignore_client_organization_id,
    require_permission,
)
from app.contracts.common import APIModel, Page
from app.contracts.schemas import ProcessRunCreate, ProcessRunResponse
from app.domain.enums import ProcessRunStatus
from app.events.service import EventService
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.repositories.memory_repos import ProcessRunRepository
from app.repositories.query import ListParams, apply_list, list_params
from app.security.jwt import AuthenticatedUser
from app.workflows.models import WorkflowStatus
from app.workflows.service import WorkflowOrchestrationService

router = APIRouter(prefix="/process-runs", tags=["process-runs"])


class WorkflowSignalBody(APIModel):
    decision: str | None = None
    reason: str | None = None
    event_id: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowDescribeResponse(APIModel):
    workflow_id: UUID
    process_run_id: UUID
    status: str
    wait_reason: str | None
    step_index: int
    trace_id: str
    workflow_version: str
    history: list[dict[str, Any]]
    context: dict[str, Any]


def _orch() -> WorkflowOrchestrationService:
    return WorkflowOrchestrationService()


def _workflow_for_run(org_id: UUID, run_id: UUID):
    ProcessRunRepository(org_id).get(run_id)
    instance = _orch().find_by_process_run(run_id)
    if instance is None:
        from app.security.errors import NotFoundError

        raise NotFoundError("Workflow not found for process run")
    return instance


@router.post("", response_model=ProcessRunResponse, status_code=201)
async def create_process_run(
    body: ProcessRunCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> ProcessRunResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    correlation_id = get_correlation_id(request)
    record = ProcessRunRepository(org.organization_id).create(
        process_id=body.process_id,
        process_version_id=body.process_version_id,
        initiated_by_user_id=user.id,
        correlation_id=correlation_id,
    )
    EventService().publish_outbox(
        organization_id=org.organization_id,
        event_type="process_run.created",
        aggregate_type="process_run",
        aggregate_id=record.id,
        payload={"status": record.status.value},
    )
    # Server-side usage metering (middleware already checked quota)
    from app.billing.limits import record_and_enforce_meter

    record_and_enforce_meter(
        org.organization_id,
        "process.monthly_runs",
        quantity=1,
        idempotency_key=f"process_run:{record.id}",
        resource_id=record.id,
    )
    try:
        from app.observability.metrics import M_PROCESS_RUNS, metrics

        metrics.incr(M_PROCESS_RUNS)
    except Exception:  # noqa: BLE001
        pass
    # Start durable workflow orchestration (Temporal Cloud or mock)
    try:
        wf = _orch().start_run(
            organization_id=org.organization_id,
            process_id=body.process_id,
            process_run_id=record.id,
            process_version_id=body.process_version_id,
            initiated_by_user_id=user.id,
            correlation_id=correlation_id,
            context={
                "_force_approval_required": False,
            },
        )
        record = ProcessRunRepository(org.organization_id).get(record.id)
        AuditService().record(
            organization_id=org.organization_id,
            actor_user_id=user.id,
            action="workflow.started",
            resource_type="workflow",
            resource_id=wf.id,
            correlation_id=correlation_id,
            payload={"trace_id": wf.trace_id, "status": wf.status.value},
        )
    except Exception:
        # Keep process run even if workflow cannot start (e.g. missing plan); surface via status
        pass

    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="process_run.created",
        resource_type="process_run",
        resource_id=record.id,
        correlation_id=correlation_id,
    )
    return ProcessRunResponse.model_validate(record, from_attributes=True)


@router.get("", response_model=Page[ProcessRunResponse])
async def list_process_runs(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[ProcessRunResponse]:
    items = ProcessRunRepository(org.organization_id).list_all()
    page = apply_list(
        items,
        params,
        status_getter=lambda r: r.status.value,
        sort_fields={"created_at": lambda r: r.created_at},
    )
    return Page(
        items=[ProcessRunResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )


@router.get("/{run_id}", response_model=ProcessRunResponse)
async def get_process_run(
    run_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> ProcessRunResponse:
    record = ProcessRunRepository(org.organization_id).get(run_id)
    return ProcessRunResponse.model_validate(record, from_attributes=True)


@router.get("/{run_id}/workflow", response_model=WorkflowDescribeResponse)
async def get_process_run_workflow(
    run_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> WorkflowDescribeResponse:
    instance = _workflow_for_run(org.organization_id, run_id)
    return WorkflowDescribeResponse(
        workflow_id=instance.id,
        process_run_id=instance.process_run_id,
        status=instance.status.value,
        wait_reason=instance.wait_reason.value if instance.wait_reason else None,
        step_index=instance.step_index,
        trace_id=instance.trace_id,
        workflow_version=instance.workflow_version,
        history=[
            {"event_type": h.event_type, "at": h.at, "step": h.step, "detail": h.detail}
            for h in instance.history
        ],
        context={k: v for k, v in instance.context.items() if not str(k).startswith("_")},
    )


@router.post("/{run_id}/cancel", response_model=ProcessRunResponse)
async def cancel_process_run(
    run_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_CANCEL))],
) -> ProcessRunResponse:
    instance = _orch().find_by_process_run(run_id)
    if instance and instance.status not in {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.FAILED,
        WorkflowStatus.TIMED_OUT,
    }:
        _orch().cancel(instance.id)
    record = ProcessRunRepository(org.organization_id).set_status(
        run_id, ProcessRunStatus.CANCELLED
    )
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="process_run.cancelled",
        resource_type="process_run",
        resource_id=run_id,
        correlation_id=get_correlation_id(request),
    )
    return ProcessRunResponse.model_validate(record, from_attributes=True)


@router.post("/{run_id}/pause", response_model=ProcessRunResponse)
async def pause_process_run(
    run_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> ProcessRunResponse:
    instance = _orch().find_by_process_run(run_id)
    if instance:
        _orch().pause(instance.id)
    record = ProcessRunRepository(org.organization_id).set_status(run_id, ProcessRunStatus.PAUSED)
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="process_run.paused",
        resource_type="process_run",
        resource_id=run_id,
        correlation_id=get_correlation_id(request),
    )
    return ProcessRunResponse.model_validate(record, from_attributes=True)


@router.post("/{run_id}/resume", response_model=ProcessRunResponse)
async def resume_process_run(
    run_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> ProcessRunResponse:
    instance = _orch().find_by_process_run(run_id)
    if instance:
        _orch().resume(instance.id)
    record = ProcessRunRepository(org.organization_id).get(run_id)
    if record.status == ProcessRunStatus.PAUSED:
        record = ProcessRunRepository(org.organization_id).set_status(
            run_id, ProcessRunStatus.EXECUTING
        )
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="process_run.resumed",
        resource_type="process_run",
        resource_id=run_id,
        correlation_id=get_correlation_id(request),
    )
    return ProcessRunResponse.model_validate(record, from_attributes=True)


@router.post("/{run_id}/retry", response_model=ProcessRunResponse)
async def retry_process_run(
    run_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> ProcessRunResponse:
    instance = _workflow_for_run(org.organization_id, run_id)
    _orch().retry(instance.id)
    record = ProcessRunRepository(org.organization_id).get(run_id)
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="process_run.retried",
        resource_type="process_run",
        resource_id=run_id,
        correlation_id=get_correlation_id(request),
    )
    return ProcessRunResponse.model_validate(record, from_attributes=True)


@router.post("/{run_id}/workflow/approval", response_model=WorkflowDescribeResponse)
async def workflow_approval_decision(
    run_id: UUID,
    body: WorkflowSignalBody,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> WorkflowDescribeResponse:
    instance = _workflow_for_run(org.organization_id, run_id)
    if not body.decision:
        from app.security.errors import ValidationAppError

        raise ValidationAppError("decision is required")
    updated = _orch().submit_approval_decision(
        instance.id,
        decision=body.decision,
        reason=body.reason,
        decided_by_user_id=user.id,
        event_id=body.event_id,
    )
    return WorkflowDescribeResponse(
        workflow_id=updated.id,
        process_run_id=updated.process_run_id,
        status=updated.status.value,
        wait_reason=updated.wait_reason.value if updated.wait_reason else None,
        step_index=updated.step_index,
        trace_id=updated.trace_id,
        workflow_version=updated.workflow_version,
        history=[
            {"event_type": h.event_type, "at": h.at, "step": h.step, "detail": h.detail}
            for h in updated.history
        ],
        context={k: v for k, v in updated.context.items() if not str(k).startswith("_")},
    )


@router.get("/{run_id}/events")
async def stream_process_run_events(
    run_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> StreamingResponse:
    repo = ProcessRunRepository(org.organization_id)
    repo.get(run_id)

    async def event_generator() -> Any:
        events = repo.events(run_id)
        for event in events:
            payload = json.dumps(event, default=str)
            yield f"event: process_run\ndata: {payload}\n\n"
            await asyncio.sleep(0)
        # Also stream durable workflow outbox events
        for event in _orch().events_for_run(run_id):
            if event in events:
                continue
            payload = json.dumps(event, default=str)
            yield f"event: workflow\ndata: {payload}\n\n"
            await asyncio.sleep(0)
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
