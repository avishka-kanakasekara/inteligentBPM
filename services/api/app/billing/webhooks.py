"""Billing webhook handler with provider-event idempotency."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.billing.service import EntitlementService
from app.contracts.common import utcnow
from app.database.memory import get_memory_store
from app.security.errors import AppError


class BillingWebhookHandler:
    """
    Ingest provider webhooks. Duplicate provider_event_id deliveries are ignored
    (idempotent). Mutating events update subscriptions via EntitlementService.
    """

    def __init__(self, entitlements: EntitlementService | None = None) -> None:
        self.entitlements = entitlements or EntitlementService()

    def handle(
        self,
        *,
        provider: str,
        provider_event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        store = get_memory_store()
        dedupe_key = f"{provider}:{provider_event_id}"
        if dedupe_key in store.billing_webhook_events:
            existing = store.billing_webhook_events[dedupe_key]
            return {
                "status": "duplicate",
                "idempotent": True,
                "event": existing,
            }

        try:
            result = self._dispatch(event_type, payload)
            record = {
                "id": dedupe_key,
                "provider": provider,
                "provider_event_id": provider_event_id,
                "event_type": event_type,
                "payload": payload,
                "status": "processed",
                "error_message": None,
                "processed_at": utcnow().isoformat(),
                "created_at": utcnow().isoformat(),
                "result": result,
            }
            store.billing_webhook_events[dedupe_key] = record
            return {"status": "processed", "idempotent": False, "event": record, "result": result}
        except Exception as exc:  # noqa: BLE001
            record = {
                "id": dedupe_key,
                "provider": provider,
                "provider_event_id": provider_event_id,
                "event_type": event_type,
                "payload": payload,
                "status": "failed",
                "error_message": str(exc),
                "processed_at": utcnow().isoformat(),
                "created_at": utcnow().isoformat(),
            }
            store.billing_webhook_events[dedupe_key] = record
            raise

    def _dispatch(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        org_id_raw = payload.get("organization_id")
        if not org_id_raw and event_type not in {"ping", "test"}:
            raise AppError("organization_id required", code="WEBHOOK_INVALID", status_code=422)
        org_id = UUID(str(org_id_raw)) if org_id_raw else None

        if event_type in {"ping", "test"}:
            return {"ok": True}

        assert org_id is not None
        self.entitlements.ensure_subscription(org_id)

        if event_type in {"subscription.created", "customer.subscription.created"}:
            plan = str(payload.get("plan_code") or "pro")
            sub = self.entitlements._set_plan(org_id, plan, actor_user_id=None)
            return {"subscription_id": sub["id"], "plan_code": sub["plan_code"]}

        if event_type in {"subscription.updated", "customer.subscription.updated"}:
            plan = payload.get("plan_code")
            if plan:
                current = self.entitlements.plan_code_for_org(org_id)
                from app.billing.catalog import PLAN_RANK

                if PLAN_RANK.get(str(plan), 0) >= PLAN_RANK.get(current, 0):
                    sub = self.entitlements.upgrade(org_id, str(plan))
                else:
                    sub = self.entitlements.downgrade(org_id, str(plan))
                return {"subscription_id": sub["id"], "plan_code": sub["plan_code"]}
            return {"noop": True}

        if event_type in {"subscription.cancelled", "customer.subscription.deleted"}:
            at_period_end = bool(payload.get("at_period_end", False))
            sub = self.entitlements.cancel(org_id, at_period_end=at_period_end)
            return {"subscription_id": sub["id"], "status": sub["status"]}

        if event_type in {"invoice.paid", "invoice.payment_succeeded"}:
            sub = self.entitlements.get_subscription(org_id)
            sub["status"] = "active"
            sub["updated_at"] = utcnow().isoformat()
            return {"subscription_id": sub["id"], "status": "active"}

        if event_type in {"invoice.payment_failed"}:
            sub = self.entitlements.get_subscription(org_id)
            sub["status"] = "past_due"
            sub["updated_at"] = utcnow().isoformat()
            return {"subscription_id": sub["id"], "status": "past_due"}

        # Unknown types are recorded but ignored
        return {"ignored": True, "event_type": event_type}
