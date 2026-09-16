"""Mock BillingProvider and Identity/Calendar mock stubs behind interfaces."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.database.memory import get_memory_store
from app.integrations.protocols import BillingUsageEvent, CalendarEvent
from app.repositories.memory_repos import OrganizationRepository


class MockBillingProvider:
    name = "mock_billing"

    def record_usage(
        self,
        *,
        organization_id: UUID,
        meter: str,
        quantity: float,
        idempotency_key: str,
    ) -> BillingUsageEvent:
        store = get_memory_store()
        for existing in store.billing_usage.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
            ):
                return BillingUsageEvent(
                    id=str(existing["id"]),
                    organization_id=str(organization_id),
                    meter=str(existing["meter"]),
                    quantity=float(existing["quantity"]),
                    status=str(existing.get("status") or "recorded"),
                    mock=True,
                )
        event_id = uuid4()
        store.billing_usage[event_id] = {
            "id": str(event_id),
            "organization_id": str(organization_id),
            "meter": meter,
            "quantity": quantity,
            "idempotency_key": idempotency_key,
            "status": "recorded",
            "mock": True,
        }
        return BillingUsageEvent(
            id=str(event_id),
            organization_id=str(organization_id),
            meter=meter,
            quantity=quantity,
            status="recorded",
            mock=True,
        )

    def get_entitlements(self, *, organization_id: UUID, plan_code: str) -> dict[str, Any]:
        from app.billing.service import EntitlementService

        snap = EntitlementService().snapshot_for_org(organization_id)
        return {
            "organization_id": str(organization_id),
            "plan_code": plan_code or snap["plan_code"],
            "features": snap["features"],
            "limits": snap["limits"],
            "provider": self.name,
            "mock": True,
        }


class RealBillingProvider:
    name = "real_billing"

    def __init__(self, *, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url

    def record_usage(self, **kwargs: Any) -> BillingUsageEvent:
        raise NotImplementedError("Real billing API not wired")

    def get_entitlements(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Real billing API not wired")


class MockIdentityProvider:
    name = "mock_identity"

    def resolve_user(self, *, organization_id: UUID, user_id: str) -> dict[str, Any] | None:
        store = get_memory_store()
        for m in store.memberships.values():
            if m.organization_id == organization_id and str(m.user_id) == user_id:
                return {
                    "user_id": user_id,
                    "organization_id": str(organization_id),
                    "role": m.role.value,
                    "status": m.status.value,
                    "mock": True,
                }
        return None

    def list_memberships(self, *, organization_id: UUID) -> list[dict[str, Any]]:
        store = get_memory_store()
        return [
            {
                "user_id": str(m.user_id),
                "role": m.role.value,
                "status": m.status.value,
                "mock": True,
            }
            for m in store.memberships.values()
            if m.organization_id == organization_id
        ]


class MockCalendarProvider:
    name = "mock_calendar"

    def create_event(
        self,
        *,
        organization_id: UUID,
        title: str,
        start_at: str,
        end_at: str,
        attendees: list[str],
        idempotency_key: str,
    ) -> CalendarEvent:
        store = get_memory_store()
        for existing in store.calendar_events.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
            ):
                return CalendarEvent(**{k: existing[k] for k in CalendarEvent.__dataclass_fields__})
        event_id = uuid4()
        record = {
            "id": str(event_id),
            "organization_id": str(organization_id),
            "title": title,
            "start_at": start_at,
            "end_at": end_at,
            "attendees": attendees,
            "status": "confirmed",
            "provider": self.name,
            "mock": True,
            "idempotency_key": idempotency_key,
        }
        store.calendar_events[event_id] = record
        return CalendarEvent(
            id=str(event_id),
            organization_id=str(organization_id),
            title=title,
            start_at=start_at,
            end_at=end_at,
            attendees=attendees,
            status="confirmed",
            provider=self.name,
            mock=True,
        )

    def get_event(self, *, organization_id: UUID, event_id: str) -> CalendarEvent | None:
        store = get_memory_store()
        from uuid import UUID as _UUID

        record = store.calendar_events.get(_UUID(event_id))
        if record is None or record.get("organization_id") != str(organization_id):
            return None
        return CalendarEvent(
            id=str(record["id"]),
            organization_id=str(record["organization_id"]),
            title=str(record["title"]),
            start_at=str(record["start_at"]),
            end_at=str(record["end_at"]),
            attendees=list(record.get("attendees") or []),
            status=str(record.get("status") or "confirmed"),
            provider=str(record.get("provider") or self.name),
            mock=bool(record.get("mock", True)),
        )


def plan_code_for_org(organization_id: UUID) -> str:
    org = OrganizationRepository().get(organization_id)
    return org.plan_code if org else "pro"
