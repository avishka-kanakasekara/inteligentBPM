"""Entitlement resolution, limit enforcement, and subscription helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.billing.catalog import METER_TO_LIMIT, PLAN_CATALOG, PLAN_RANK
from app.contracts.common import utcnow
from app.database.memory import get_memory_store, new_id, seed_plan_entitlements
from app.domain.enums import OrgRole
from app.repositories.memory_repos import OrganizationRepository
from app.security.errors import AppError


class EntitlementDenied(AppError):
    def __init__(self, message: str, *, feature_code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="ENTITLEMENT_DENIED",
            status_code=403,
            details={"feature_code": feature_code, **(details or {})},
        )


class LimitExceeded(AppError):
    def __init__(
        self,
        message: str,
        *,
        feature_code: str,
        limit: float | int | None,
        usage: float | int | None = None,
    ) -> None:
        super().__init__(
            message,
            code="LIMIT_EXCEEDED",
            status_code=402,
            details={"feature_code": feature_code, "limit": limit, "usage": usage},
        )


@dataclass
class EntitlementValue:
    feature_code: str
    plan_code: str
    numeric_limit: float | int | None
    boolean_value: bool | None
    text_value: str | None

    @property
    def enabled(self) -> bool:
        if self.boolean_value is not None:
            return bool(self.boolean_value)
        # Numeric-only entitlements are considered "enabled" when present
        return True


def current_period_key(when: Any | None = None) -> str:
    dt = when or utcnow()
    return f"{dt.year:04d}-{dt.month:02d}"


class EntitlementService:
    """Server-side authority for plan features and numeric limits."""

    def __init__(self) -> None:
        seed_plan_entitlements()

    def ensure_subscription(
        self,
        organization_id: UUID,
        *,
        plan_code: str | None = None,
    ) -> dict[str, Any]:
        store = get_memory_store()
        for sub in store.subscriptions.values():
            if sub.get("organization_id") == str(organization_id):
                return sub
        org = OrganizationRepository().get(organization_id)
        code = plan_code or (org.plan_code if org else "pro")
        if code not in PLAN_CATALOG:
            code = "pro"
        now = utcnow()
        sub_id = new_id()
        record = {
            "id": str(sub_id),
            "organization_id": str(organization_id),
            "plan_code": code,
            "status": "active",
            "provider": "mock",
            "provider_subscription_id": f"mock_sub_{organization_id}",
            "current_period_start": now.isoformat(),
            "current_period_end": (now + timedelta(days=30)).isoformat(),
            "cancel_at_period_end": False,
            "cancelled_at": None,
            "seat_count": 1,
            "metadata": {},
            "row_version": 1,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        store.subscriptions[sub_id] = record
        return record

    def get_subscription(self, organization_id: UUID) -> dict[str, Any]:
        return self.ensure_subscription(organization_id)

    def plan_code_for_org(self, organization_id: UUID) -> str:
        sub = self.get_subscription(organization_id)
        if sub.get("status") == "cancelled":
            # Cancelled subscriptions fall back to pro after period end.
            end = sub.get("current_period_end")
            if end:
                end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                if utcnow() > end_dt:
                    return "pro"
        return str(sub.get("plan_code") or "pro")

    def list_entitlements(self, plan_code: str) -> list[EntitlementValue]:
        store = get_memory_store()
        rows: list[EntitlementValue] = []
        for (pcode, feature), data in store.plan_entitlements.items():
            if pcode != plan_code:
                continue
            rows.append(
                EntitlementValue(
                    feature_code=feature,
                    plan_code=pcode,
                    numeric_limit=data.get("numeric_limit"),
                    boolean_value=data.get("boolean_value"),
                    text_value=data.get("text_value"),
                )
            )
        return sorted(rows, key=lambda r: r.feature_code)

    def get_entitlement(self, plan_code: str, feature_code: str) -> EntitlementValue | None:
        store = get_memory_store()
        data = store.plan_entitlements.get((plan_code, feature_code))
        if not data:
            return None
        return EntitlementValue(
            feature_code=feature_code,
            plan_code=plan_code,
            numeric_limit=data.get("numeric_limit"),
            boolean_value=data.get("boolean_value"),
            text_value=data.get("text_value"),
        )

    def has_feature(self, organization_id: UUID, feature_code: str) -> bool:
        plan = self.plan_code_for_org(organization_id)
        ent = self.get_entitlement(plan, feature_code)
        if ent is None:
            return False
        if ent.boolean_value is not None:
            return bool(ent.boolean_value)
        return True

    def assert_feature(self, organization_id: UUID, feature_code: str) -> None:
        sub = self.get_subscription(organization_id)
        if sub.get("status") in {"incomplete"}:
            raise EntitlementDenied(
                "Subscription is incomplete",
                feature_code=feature_code,
                details={"subscription_status": sub.get("status")},
            )
        if not self.has_feature(organization_id, feature_code):
            raise EntitlementDenied(
                f"Plan entitlement denied: {feature_code}",
                feature_code=feature_code,
                details={"plan_code": self.plan_code_for_org(organization_id)},
            )

    def numeric_limit(self, organization_id: UUID, feature_code: str) -> float | int | None:
        plan = self.plan_code_for_org(organization_id)
        ent = self.get_entitlement(plan, feature_code)
        if ent is None:
            return None
        return ent.numeric_limit

    def assert_within_limit(
        self,
        organization_id: UUID,
        feature_code: str,
        *,
        current_usage: float | int,
        increment: float | int = 1,
    ) -> None:
        limit = self.numeric_limit(organization_id, feature_code)
        if limit is None:
            return
        if float(current_usage) + float(increment) > float(limit):
            raise LimitExceeded(
                f"Plan limit exceeded for {feature_code}",
                feature_code=feature_code,
                limit=limit,
                usage=current_usage,
            )

    def assert_meter(
        self,
        organization_id: UUID,
        meter_code: str,
        *,
        increment: float | int = 1,
    ) -> None:
        from app.billing.usage import UsageService

        limit_feature = METER_TO_LIMIT.get(meter_code, meter_code)
        usage = UsageService().aggregate(organization_id, meter_code)
        self.assert_within_limit(
            organization_id,
            limit_feature,
            current_usage=usage,
            increment=increment,
        )

    def upgrade(
        self,
        organization_id: UUID,
        new_plan_code: str,
        *,
        actor_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        if new_plan_code not in PLAN_CATALOG:
            raise AppError("Unknown plan", code="UNKNOWN_PLAN", status_code=422)
        sub = self.get_subscription(organization_id)
        current = str(sub["plan_code"])
        if PLAN_RANK.get(new_plan_code, 0) < PLAN_RANK.get(current, 0):
            raise AppError(
                "Use downgrade endpoint for lower plans",
                code="USE_DOWNGRADE",
                status_code=422,
            )
        return self._set_plan(organization_id, new_plan_code, actor_user_id=actor_user_id)

    def downgrade(
        self,
        organization_id: UUID,
        new_plan_code: str,
        *,
        actor_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        if new_plan_code not in PLAN_CATALOG:
            raise AppError("Unknown plan", code="UNKNOWN_PLAN", status_code=422)
        sub = self.get_subscription(organization_id)
        current = str(sub["plan_code"])
        if PLAN_RANK.get(new_plan_code, 0) > PLAN_RANK.get(current, 0):
            raise AppError(
                "Use upgrade endpoint for higher plans",
                code="USE_UPGRADE",
                status_code=422,
            )
        # Existing workflows continue; new actions enforce the lower plan.
        return self._set_plan(organization_id, new_plan_code, actor_user_id=actor_user_id)

    def cancel(
        self,
        organization_id: UUID,
        *,
        at_period_end: bool = True,
        actor_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        sub = self.get_subscription(organization_id)
        now = utcnow()
        sub["cancel_at_period_end"] = at_period_end
        if at_period_end:
            sub["status"] = "active"
            sub["cancelled_at"] = None
        else:
            sub["status"] = "cancelled"
            sub["cancelled_at"] = now.isoformat()
            sub["plan_code"] = "pro"
            OrganizationRepository().update(organization_id, plan_code="pro")
        sub["updated_at"] = now.isoformat()
        sub["row_version"] = int(sub.get("row_version") or 1) + 1
        sub["metadata"] = {
            **(sub.get("metadata") or {}),
            "cancelled_by": str(actor_user_id) if actor_user_id else None,
        }
        return sub

    def _set_plan(
        self,
        organization_id: UUID,
        plan_code: str,
        *,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        sub = self.get_subscription(organization_id)
        now = utcnow()
        previous = sub.get("plan_code")
        sub["plan_code"] = plan_code
        sub["status"] = "active"
        sub["cancel_at_period_end"] = False
        sub["cancelled_at"] = None
        sub["updated_at"] = now.isoformat()
        sub["row_version"] = int(sub.get("row_version") or 1) + 1
        sub["metadata"] = {
            **(sub.get("metadata") or {}),
            "previous_plan": previous,
            "changed_by": str(actor_user_id) if actor_user_id else None,
        }
        OrganizationRepository().update(organization_id, plan_code=plan_code)
        return sub

    def snapshot_for_org(self, organization_id: UUID) -> dict[str, Any]:
        plan = self.plan_code_for_org(organization_id)
        ents = self.list_entitlements(plan)
        return {
            "organization_id": str(organization_id),
            "plan_code": plan,
            "subscription": self.get_subscription(organization_id),
            "entitlements": [
                {
                    "feature_code": e.feature_code,
                    "numeric_limit": e.numeric_limit,
                    "boolean_value": e.boolean_value,
                    "text_value": e.text_value,
                }
                for e in ents
            ],
            "features": {
                e.feature_code: e.boolean_value
                for e in ents
                if e.boolean_value is not None
            },
            "limits": {
                e.feature_code: e.numeric_limit
                for e in ents
                if e.numeric_limit is not None
            },
        }


# Back-compat thin wrapper used by older call sites
class BillingService:
    def features_for_plan(self, plan_code: str) -> frozenset[str]:
        svc = EntitlementService()
        return frozenset(
            e.feature_code
            for e in svc.list_entitlements(plan_code)
            if e.boolean_value is True
        )

    def assert_feature(self, plan_code: str, feature_key: str) -> None:
        # Legacy API took plan_code; resolve via a synthetic org-less check
        svc = EntitlementService()
        ent = svc.get_entitlement(plan_code, feature_key)
        if ent is None or (ent.boolean_value is False):
            raise EntitlementDenied(
                f"Plan entitlement denied: {feature_key}",
                feature_code=feature_key,
                details={"plan_code": plan_code},
            )

    def can_manage_billing(self, role: OrgRole) -> bool:
        return role in {OrgRole.OWNER, OrgRole.ADMIN}
