"""Usage event recording and period aggregation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.billing.service import current_period_key
from app.contracts.common import utcnow
from app.database.memory import get_memory_store, new_id


class UsageService:
    def record(
        self,
        *,
        organization_id: UUID,
        meter_code: str,
        quantity: float | int = 1,
        period_key: str | None = None,
        source: str = "system",
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        store = get_memory_store()
        if idempotency_key:
            for existing in store.usage_events.values():
                if (
                    existing.get("organization_id") == str(organization_id)
                    and existing.get("idempotency_key") == idempotency_key
                ):
                    return existing

        event_id = new_id()
        period = period_key or current_period_key()
        record = {
            "id": str(event_id),
            "organization_id": str(organization_id),
            "meter_code": meter_code,
            "quantity": float(quantity),
            "period_key": period,
            "source": source,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "idempotency_key": idempotency_key,
            "metadata": metadata or {},
            "created_at": utcnow().isoformat(),
        }
        store.usage_events[event_id] = record
        return record

    def aggregate(
        self,
        organization_id: UUID,
        meter_code: str,
        *,
        period_key: str | None = None,
    ) -> float:
        period = period_key or current_period_key()
        store = get_memory_store()
        total = 0.0
        for event in store.usage_events.values():
            if (
                event.get("organization_id") == str(organization_id)
                and event.get("meter_code") == meter_code
                and event.get("period_key") == period
            ):
                total += float(event.get("quantity") or 0)
        return total

    def summary(self, organization_id: UUID, *, period_key: str | None = None) -> dict[str, float]:
        period = period_key or current_period_key()
        store = get_memory_store()
        out: dict[str, float] = {}
        for event in store.usage_events.values():
            if (
                event.get("organization_id") == str(organization_id)
                and event.get("period_key") == period
            ):
                meter = str(event.get("meter_code"))
                out[meter] = out.get(meter, 0.0) + float(event.get("quantity") or 0)
        return out
