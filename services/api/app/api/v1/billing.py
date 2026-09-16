"""Billing, subscriptions, entitlements, and webhook endpoints."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import Field

from app.audit import AuditService
from app.auth.deps import OrganizationContext, get_current_user, require_permission
from app.billing.catalog import PLAN_CATALOG
from app.billing.service import BillingService, EntitlementService
from app.billing.usage import UsageService
from app.billing.webhooks import BillingWebhookHandler
from app.contracts.common import APIModel
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.security.errors import AppError, ValidationAppError
from app.security.jwt import AuthenticatedUser

router = APIRouter(tags=["billing"])


class PlanChangeRequest(APIModel):
    plan_code: str


class CancelSubscriptionRequest(APIModel):
    at_period_end: bool = True


class WebhookIngestRequest(APIModel):
    provider: str = "mock"
    provider_event_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class UsageRecordRequest(APIModel):
    meter_code: str
    quantity: float = 1
    idempotency_key: str | None = None


@router.get("/billing/plans")
async def list_plans() -> dict[str, Any]:
    svc = EntitlementService()
    plans = []
    for code, definition in sorted(PLAN_CATALOG.items(), key=lambda x: x[1].sort_order):
        ents = svc.list_entitlements(code)
        plans.append(
            {
                "plan_code": code,
                "display_name": definition.display_name,
                "description": definition.description,
                "sort_order": definition.sort_order,
                "highlights": list(definition.highlights),
                "entitlements": [
                    {
                        "feature_code": e.feature_code,
                        "numeric_limit": e.numeric_limit,
                        "boolean_value": e.boolean_value,
                        "text_value": e.text_value,
                    }
                    for e in ents
                ],
            }
        )
    return {"plans": plans}


@router.get("/billing/subscription")
async def get_subscription(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.BILLING_MANAGE))],
) -> dict[str, Any]:
    return EntitlementService().snapshot_for_org(org.organization_id)


@router.get("/billing/entitlements")
async def get_entitlements(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> dict[str, Any]:
    """Any member can read entitlements for UI gating (server still enforces)."""
    return EntitlementService().snapshot_for_org(org.organization_id)


@router.get("/billing/usage")
async def get_usage(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.BILLING_MANAGE))],
) -> dict[str, Any]:
    svc = EntitlementService()
    usage = UsageService().summary(org.organization_id)
    limits = svc.snapshot_for_org(org.organization_id)["limits"]
    return {
        "organization_id": str(org.organization_id),
        "period_usage": usage,
        "limits": limits,
    }


@router.post("/billing/usage", status_code=201)
async def record_usage(
    body: UsageRecordRequest,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.BILLING_MANAGE))],
) -> dict[str, Any]:
    EntitlementService().assert_meter(
        org.organization_id, body.meter_code, increment=body.quantity
    )
    return UsageService().record(
        organization_id=org.organization_id,
        meter_code=body.meter_code,
        quantity=body.quantity,
        idempotency_key=body.idempotency_key,
    )


@router.post("/billing/subscription/upgrade")
async def upgrade_subscription(
    body: PlanChangeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.BILLING_MANAGE))],
) -> dict[str, Any]:
    if not BillingService().can_manage_billing(org.role):
        raise AppError("Billing management denied", code="FORBIDDEN", status_code=403)
    sub = EntitlementService().upgrade(
        org.organization_id, body.plan_code, actor_user_id=user.id
    )
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="billing.upgraded",
        resource_type="subscription",
        resource_id=UUID(sub["id"]),
        correlation_id=get_correlation_id(request),
        payload={"plan_code": body.plan_code},
    )
    return EntitlementService().snapshot_for_org(org.organization_id)


@router.post("/billing/subscription/downgrade")
async def downgrade_subscription(
    body: PlanChangeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.BILLING_MANAGE))],
) -> dict[str, Any]:
    sub = EntitlementService().downgrade(
        org.organization_id, body.plan_code, actor_user_id=user.id
    )
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="billing.downgraded",
        resource_type="subscription",
        resource_id=UUID(sub["id"]),
        correlation_id=get_correlation_id(request),
        payload={"plan_code": body.plan_code},
    )
    return EntitlementService().snapshot_for_org(org.organization_id)


@router.post("/billing/subscription/cancel")
async def cancel_subscription(
    body: CancelSubscriptionRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.BILLING_MANAGE))],
) -> dict[str, Any]:
    sub = EntitlementService().cancel(
        org.organization_id,
        at_period_end=body.at_period_end,
        actor_user_id=user.id,
    )
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="billing.cancelled",
        resource_type="subscription",
        resource_id=UUID(sub["id"]),
        correlation_id=get_correlation_id(request),
        payload={"at_period_end": body.at_period_end},
    )
    return EntitlementService().snapshot_for_org(org.organization_id)


@router.post("/billing/webhooks", status_code=202)
async def ingest_billing_webhook(
    body: WebhookIngestRequest,
    x_billing_webhook_secret: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """
    Provider webhook ingress. Idempotent on (provider, provider_event_id).
    Secret header is optional in mock mode; required when BILLING_WEBHOOK_SECRET is set.
    """
    from app.config import get_settings

    settings = get_settings()
    expected = getattr(settings, "billing_webhook_secret", None)
    if expected and x_billing_webhook_secret != expected:
        raise AppError("Invalid webhook secret", code="WEBHOOK_UNAUTHORIZED", status_code=401)
    if not body.provider_event_id.strip():
        raise ValidationAppError("provider_event_id is required")
    return BillingWebhookHandler().handle(
        provider=body.provider,
        provider_event_id=body.provider_event_id,
        event_type=body.event_type,
        payload=body.payload,
    )
