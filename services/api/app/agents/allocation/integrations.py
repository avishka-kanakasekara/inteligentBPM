"""Integration availability readout for Agent 2 (read-only, no side effects)."""

from __future__ import annotations

from app.agents.allocation.models import IntegrationAvailability
from app.billing.service import BillingService


def list_integration_availability(plan_code: str) -> list[IntegrationAvailability]:
    """Report which integrations the org plan may use. Never enables side effects."""
    features = BillingService().features_for_plan(plan_code)
    advanced = "integrations.advanced" in features

    return [
        IntegrationAvailability(
            key="email",
            available=True,
            mode="mock",
            reason="Email available via tool gateway (mock until credentials configured). Agent 2 must not send email.",
        ),
        IntegrationAvailability(
            key="suppliers",
            available=True,
            mode="mock",
            reason="Supplier channel available for later execution; Agent 2 only reads directory data.",
        ),
        IntegrationAvailability(
            key="purchasing",
            available=True,
            mode="mock",
            reason="Purchasing is draft-only until approved execution. Agent 2 must not create purchase orders.",
        ),
        IntegrationAvailability(
            key="billing_connector",
            available=advanced or plan_code in {"enterprise", "pro_max"},
            mode="disabled" if plan_code == "pro" else "mock",
            reason="Billing connector entitlement based on plan; Agent 2 does not mutate billing.",
        ),
        IntegrationAvailability(
            key="notifications",
            available=True,
            mode="mock",
            reason="In-app notifications available; Agent 2 does not notify.",
        ),
    ]
