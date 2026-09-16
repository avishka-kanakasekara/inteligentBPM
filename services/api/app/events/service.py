"""Outbox/inbox event service for durable messaging and replay protection."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.contracts.common import utcnow
from app.database.memory import get_memory_store
from app.workflows.outbox import DuplicateEventError, InboxService, OutboxService


class EventService:
    def __init__(self) -> None:
        self.outbox = OutboxService()
        self.inbox = InboxService()

    def publish_outbox(
        self,
        *,
        organization_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
        trace_id: str | None = None,
        event_id: UUID | None = None,
    ) -> UUID:
        store = get_memory_store()
        eid = event_id or uuid4()
        record = {
            "id": str(eid),
            "organization_id": str(organization_id),
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "payload": payload,
            "at": utcnow().isoformat(),
            "channel": "outbox",
            "trace_id": trace_id,
            "status": "pending",
        }
        store.run_events.setdefault(aggregate_id, []).append(record)
        # Also persist in workflow outbox when aggregate is a process run / workflow
        store.workflow_outbox[eid] = {
            **record,
            "workflow_id": str(aggregate_id),
            "process_run_id": str(aggregate_id),
        }
        return eid

    def accept_inbox(
        self,
        *,
        event_id: str,
        organization_id: UUID,
        workflow_id: UUID,
        signal_type: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
        reject_duplicates: bool = True,
    ) -> bool:
        if reject_duplicates:
            self.inbox.accept_or_raise(
                event_id=event_id,
                organization_id=organization_id,
                workflow_id=workflow_id,
                signal_type=signal_type,
                payload=payload,
                trace_id=trace_id,
            )
            return True
        return self.inbox.accept(
            event_id=event_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            signal_type=signal_type,
            payload=payload,
            trace_id=trace_id,
        )


__all__ = ["EventService", "DuplicateEventError"]
