"""Subscriptions and entitlements tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.billing.service import EntitlementDenied, EntitlementService, LimitExceeded
from app.billing.usage import UsageService
from app.billing.webhooks import BillingWebhookHandler
from app.database.memory import get_memory_store
from app.domain.enums import ProcessRunStatus
from app.repositories.memory_repos import ProcessRepository, ProcessRunRepository
from app.workflows.engine import MockDurableWorkflowEngine, reset_mock_engine


def test_plan_feature_access(org_a: UUID, org_b: UUID) -> None:
    svc = EntitlementService()
    # pro org
    assert svc.has_feature(org_a, "process.discovery") is True
    assert svc.has_feature(org_a, "security.sso_enabled") is False
    assert svc.has_feature(org_a, "integrations.email_enabled") is True
    # enterprise org
    assert svc.has_feature(org_b, "security.sso_enabled") is True
    assert svc.has_feature(org_b, "audit.export_enabled") is True

    with pytest.raises(EntitlementDenied):
        svc.assert_feature(org_a, "security.sso_enabled")


def test_usage_limits_and_exceeded(org_a: UUID) -> None:
    svc = EntitlementService()
    usage = UsageService()
    limit = svc.numeric_limit(org_a, "process.monthly_runs")
    assert limit == 100

    # Fill up to limit - 1
    for i in range(int(limit) - 1):
        usage.record(
            organization_id=org_a,
            meter_code="process.monthly_runs",
            quantity=1,
            idempotency_key=f"fill-{i}",
        )

    svc.assert_meter(org_a, "process.monthly_runs", increment=1)
    usage.record(
        organization_id=org_a,
        meter_code="process.monthly_runs",
        quantity=1,
        idempotency_key="last-ok",
    )

    with pytest.raises(LimitExceeded) as exc:
        svc.assert_meter(org_a, "process.monthly_runs", increment=1)
    assert exc.value.code == "LIMIT_EXCEEDED"
    assert exc.value.details["feature_code"] == "process.monthly_runs"


def test_limit_exceeded_via_api(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
) -> None:
    # Exhaust monthly runs
    usage = UsageService()
    for i in range(100):
        usage.record(
            organization_id=org_a,
            meter_code="process.monthly_runs",
            quantity=1,
            idempotency_key=f"api-fill-{i}",
        )

    process = client.post(
        "/v1/processes",
        headers=auth_headers_a,
        json={"name": "Limited", "description": "x"},
    )
    assert process.status_code == 201
    version = client.post(
        f"/v1/processes/{process.json()['id']}/versions",
        headers=auth_headers_a,
        json={"plan_snapshot": {"steps": []}},
    )
    assert version.status_code == 201

    run = client.post(
        "/v1/process-runs",
        headers=auth_headers_a,
        json={
            "process_id": process.json()["id"],
            "process_version_id": version.json()["id"],
        },
    )
    assert run.status_code == 402
    assert run.json()["error"]["code"] == "LIMIT_EXCEEDED"


def test_subscription_cancellation(org_a: UUID, user_a_id: UUID) -> None:
    svc = EntitlementService()
    sub = svc.cancel(org_a, at_period_end=False, actor_user_id=user_a_id)
    assert sub["status"] == "cancelled"
    assert svc.plan_code_for_org(org_a) == "pro"


def test_webhook_idempotency(org_a: UUID) -> None:
    handler = BillingWebhookHandler()
    payload = {"organization_id": str(org_a), "plan_code": "enterprise"}
    first = handler.handle(
        provider="mock",
        provider_event_id="evt_1",
        event_type="subscription.updated",
        payload=payload,
    )
    assert first["idempotent"] is False
    assert first["status"] == "processed"

    second = handler.handle(
        provider="mock",
        provider_event_id="evt_1",
        event_type="subscription.updated",
        payload=payload,
    )
    assert second["idempotent"] is True
    assert second["status"] == "duplicate"
    assert len(get_memory_store().billing_webhook_events) == 1


def test_upgrade_and_downgrade(org_a: UUID, user_a_id: UUID) -> None:
    svc = EntitlementService()
    assert svc.plan_code_for_org(org_a) == "pro"

    upgraded = svc.upgrade(org_a, "enterprise", actor_user_id=user_a_id)
    assert upgraded["plan_code"] == "enterprise"
    assert svc.has_feature(org_a, "security.sso_enabled") is True

    downgraded = svc.downgrade(org_a, "pro", actor_user_id=user_a_id)
    assert downgraded["plan_code"] == "pro"
    assert svc.has_feature(org_a, "security.sso_enabled") is False


def test_existing_workflow_after_downgrade(org_a: UUID, user_a_id: UUID) -> None:
    """In-flight workflows continue after downgrade; new entitlement checks use new plan."""
    reset_mock_engine()
    svc = EntitlementService()
    svc.upgrade(org_a, "enterprise", actor_user_id=user_a_id)

    repo = ProcessRepository(org_a)
    proc = repo.create(name="WF", description="d", created_by_user_id=user_a_id)
    version = repo.create_version(
        proc.id, plan_snapshot={"goal": "x", "steps": []}, status="confirmed"
    )
    run = ProcessRunRepository(org_a).create(
        process_id=proc.id,
        process_version_id=version.id,
        initiated_by_user_id=user_a_id,
        correlation_id="downgrade-wf",
    )
    eng = MockDurableWorkflowEngine()
    instance = eng.start(
        organization_id=org_a,
        process_id=proc.id,
        process_run_id=run.id,
        process_version_id=version.id,
        initiated_by_user_id=user_a_id,
        context={"_force_approval_required": True},
    )
    assert instance.status.value == "waiting"

    # Downgrade while waiting for approval — existing run stays waiting
    svc.downgrade(org_a, "pro", actor_user_id=user_a_id)
    still = eng.get(instance.id)
    assert still.status.value == "waiting"
    run_rec = ProcessRunRepository(org_a).get(run.id)
    assert run_rec.status != ProcessRunStatus.CANCELLED

    # Can still complete the in-flight workflow
    done = eng.signal(
        instance.id,
        signal_type="approval_decision",
        payload={"decision": "approved"},
    )
    assert done.status.value == "completed"

    # New feature checks use pro
    assert svc.has_feature(org_a, "security.sso_enabled") is False


def test_billing_api_plans_and_subscription(
    client: TestClient,
    auth_headers_a: dict[str, str],
) -> None:
    plans = client.get("/v1/billing/plans", headers=auth_headers_a)
    assert plans.status_code == 200
    codes = {p["plan_code"] for p in plans.json()["plans"]}
    assert codes == {"pro", "enterprise", "pro_max"}

    snap = client.get("/v1/billing/subscription", headers=auth_headers_a)
    assert snap.status_code == 200
    assert snap.json()["plan_code"] == "pro"

    upgraded = client.post(
        "/v1/billing/subscription/upgrade",
        headers=auth_headers_a,
        json={"plan_code": "pro_max"},
    )
    assert upgraded.status_code == 200
    assert upgraded.json()["plan_code"] == "pro_max"
    assert upgraded.json()["features"].get("workers.dedicated_capacity") is True

    webhook = client.post(
        "/v1/billing/webhooks",
        json={
            "provider": "mock",
            "provider_event_id": str(uuid4()),
            "event_type": "subscription.cancelled",
            "payload": {
                "organization_id": auth_headers_a["X-Organization-Id"],
                "at_period_end": False,
            },
        },
    )
    assert webhook.status_code == 202
    assert webhook.json()["status"] == "processed"
