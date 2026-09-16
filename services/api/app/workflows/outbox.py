"""Outbox events, inbox deduplication, and event replay protection."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.contracts.common import utcnow
from app.database.memory import get_memory_store


class DuplicateEventError(Exception):
    """Inbound event already processed (replay protection)."""


class OutboxService:
    """Durable outbox — events are persisted before side effects are assumed delivered."""

    def publish(
        self,
        *,
        organization_id: UUID,
        workflow_id: UUID,
        process_run_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        trace_id: str,
        event_id: UUID | None = None,
    ) -> UUID:
        store = get_memory_store()
        eid = event_id or uuid4()
        record = {
            "id": str(eid),
            "organization_id": str(organization_id),
            "workflow_id": str(workflow_id),
            "process_run_id": str(process_run_id),
            "event_type": event_type,
            "payload": payload,
            "trace_id": trace_id,
            "channel": "outbox",
            "status": "pending",
            "at": utcnow().isoformat(),
        }
        store.workflow_outbox[eid] = record
        # Mirror onto process-run event stream for SSE consumers
        store.run_events.setdefault(process_run_id, []).append(
            {
                **record,
                "aggregate_type": "workflow",
                "aggregate_id": str(workflow_id),
            }
        )
        return eid

    def mark_delivered(self, event_id: UUID) -> None:
        store = get_memory_store()
        record = store.workflow_outbox.get(event_id)
        if record:
            record["status"] = "delivered"
            record["delivered_at"] = utcnow().isoformat()

    def list_pending(self, *, workflow_id: UUID | None = None) -> list[dict[str, Any]]:
        store = get_memory_store()
        items = [
            e
            for e in store.workflow_outbox.values()
            if e.get("status") == "pending"
            and (workflow_id is None or e.get("workflow_id") == str(workflow_id))
        ]
        return sorted(items, key=lambda e: e.get("at") or "")


class InboxService:
    """Inbox with idempotent acceptance keyed by event_id (replay protection)."""

    def accept(
        self,
        *,
        event_id: str,
        organization_id: UUID,
        workflow_id: UUID,
        signal_type: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> bool:
        """
        Returns True if newly accepted, False if duplicate (already processed).

        Raises DuplicateEventError when caller requires strict rejection of duplicates.
        """
        store = get_memory_store()
        key = f"{organization_id}:{event_id}"
        if key in store.workflow_inbox:
            return False
        store.workflow_inbox[key] = {
            "event_id": event_id,
            "organization_id": str(organization_id),
            "workflow_id": str(workflow_id),
            "signal_type": signal_type,
            "payload": payload,
            "trace_id": trace_id,
            "accepted_at": utcnow().isoformat(),
            "status": "accepted",
        }
        return True

    def accept_or_raise(
        self,
        *,
        event_id: str,
        organization_id: UUID,
        workflow_id: UUID,
        signal_type: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        if not self.accept(
            event_id=event_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            signal_type=signal_type,
            payload=payload,
            trace_id=trace_id,
        ):
            raise DuplicateEventError(f"Duplicate event delivery: {event_id}")

    def was_processed(self, *, organization_id: UUID, event_id: str) -> bool:
        store = get_memory_store()
        return f"{organization_id}:{event_id}" in store.workflow_inbox
