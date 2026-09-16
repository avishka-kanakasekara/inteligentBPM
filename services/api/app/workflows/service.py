"""Orchestration service — start/pause/resume/cancel/retry and approval waits."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.workflows.client import WorkflowClient, get_workflow_client
from app.workflows.engine import get_mock_engine
from app.workflows.models import WorkflowInstance, WorkflowSignal, WorkflowStatus
from app.workflows.outbox import OutboxService


class WorkflowOrchestrationService:
    def __init__(self, client: WorkflowClient | None = None) -> None:
        self.client = client or get_workflow_client()
        self.outbox = OutboxService()

    def start_run(
        self,
        *,
        organization_id: UUID,
        process_id: UUID,
        process_run_id: UUID,
        process_version_id: UUID | None = None,
        initiated_by_user_id: UUID | None = None,
        correlation_id: str | None = None,
        context: dict[str, Any] | None = None,
        timeout_seconds: int | None = 86_400,
    ) -> WorkflowInstance:
        trace_id = correlation_id or f"trace-{uuid4()}"
        return self.client.start_process_workflow(
            organization_id=organization_id,
            process_id=process_id,
            process_run_id=process_run_id,
            process_version_id=process_version_id,
            initiated_by_user_id=initiated_by_user_id,
            trace_id=trace_id,
            context=context,
            timeout_seconds=timeout_seconds,
        )

    def pause(self, workflow_id: UUID, *, event_id: str | None = None) -> WorkflowInstance:
        return self.client.signal(
            workflow_id, signal_type=WorkflowSignal.PAUSE, event_id=event_id
        )

    def resume(self, workflow_id: UUID, *, event_id: str | None = None) -> WorkflowInstance:
        return self.client.signal(
            workflow_id, signal_type=WorkflowSignal.RESUME, event_id=event_id
        )

    def cancel(self, workflow_id: UUID, *, event_id: str | None = None) -> WorkflowInstance:
        return self.client.signal(
            workflow_id, signal_type=WorkflowSignal.CANCEL, event_id=event_id
        )

    def retry(self, workflow_id: UUID, *, event_id: str | None = None) -> WorkflowInstance:
        return self.client.signal(
            workflow_id, signal_type=WorkflowSignal.RETRY, event_id=event_id
        )

    def submit_approval_decision(
        self,
        workflow_id: UUID,
        *,
        decision: str,
        reason: str | None = None,
        decided_by_user_id: UUID | None = None,
        event_id: str | None = None,
    ) -> WorkflowInstance:
        return self.client.signal(
            workflow_id,
            signal_type=WorkflowSignal.APPROVAL_DECISION,
            payload={
                "decision": decision,
                "reason": reason,
                "decided_by_user_id": str(decided_by_user_id) if decided_by_user_id else None,
            },
            event_id=event_id,
        )

    def provide_missing_information(
        self,
        workflow_id: UUID,
        *,
        fields: dict[str, Any],
        event_id: str | None = None,
    ) -> WorkflowInstance:
        return self.client.signal(
            workflow_id,
            signal_type=WorkflowSignal.MISSING_INFO_PROVIDED,
            payload={"fields": fields},
            event_id=event_id,
        )

    def external_callback(
        self,
        workflow_id: UUID,
        *,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> WorkflowInstance:
        return self.client.signal(
            workflow_id,
            signal_type=WorkflowSignal.EXTERNAL_CALLBACK,
            payload=payload,
            event_id=event_id,
        )

    def clear_approval_gate(
        self,
        workflow_id: UUID,
        *,
        event_id: str | None = None,
    ) -> WorkflowInstance:
        return self.client.signal(
            workflow_id,
            signal_type="approval_gate_cleared",
            event_id=event_id,
        )

    def describe(self, workflow_id: UUID) -> WorkflowInstance:
        return self.client.describe(workflow_id)

    def history(self, workflow_id: UUID) -> list[dict[str, Any]]:
        return self.client.history(workflow_id)

    def find_by_process_run(self, process_run_id: UUID) -> WorkflowInstance | None:
        return get_mock_engine().get_by_process_run(process_run_id)

    def events_for_run(self, process_run_id: UUID) -> list[dict[str, Any]]:
        from app.database.memory import get_memory_store

        return list(get_memory_store().run_events.get(process_run_id, []))

    def is_terminal(self, instance: WorkflowInstance) -> bool:
        return instance.status in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.TIMED_OUT,
        }
