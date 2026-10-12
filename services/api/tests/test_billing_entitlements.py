"""Subscriptions and entitlements tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.billing.service import EntitlementDenied, EntitlementService, LimitExceeded
from app.billing.usage import UsageService
from app.billing.webhooks import BillingWebhookHandler
from app.contracts.common import utcnow
from app.database.memory import OrganizationRecord, get_memory_store
from app.domain.enums import ProcessRunStatus
from app.repositories.memory_repos import (
    OrganizationRepository,
    ProcessRepository,
    ProcessRunRepository,
)
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


def _blank_hosted_org() -> UUID:
    org_id = uuid4()
    now = utcnow()
    get_memory_store().organizations[org_id] = OrganizationRecord(
        id=org_id,
        name=str(org_id),
        slug="",
        plan_code="",
        status="",
        row_version=1,
        created_at=now,
        updated_at=now,
    )
    return org_id


def test_created_webhook_without_plan_does_not_grant_a_paid_plan(client: TestClient) -> None:
    org_id = _blank_hosted_org()
    handler = BillingWebhookHandler()
    missing = handler.handle(
        provider="mock",
        provider_event_id="created-missing-plan",
        event_type="subscription.created",
        payload={"organization_id": str(org_id)},
    )
    svc = EntitlementService()
    assert missing["result"]["plan_code"] == ""
    assert svc.plan_code_for_org(org_id) == ""
    assert svc.has_feature(org_id, "process.discovery") is False
    assert OrganizationRepository().get(org_id).plan_code == ""

    blank_org = _blank_hosted_org()
    blank = handler.handle(
        provider="mock",
        provider_event_id="created-blank-plan",
        event_type="subscription.created",
        payload={"organization_id": str(blank_org), "plan_code": "  "},
    )
    assert blank["result"]["plan_code"] == ""
    assert svc.has_feature(blank_org, "security.sso_enabled") is False
    assert svc.has_feature(blank_org, "workers.dedicated_capacity") is False


def test_created_webhook_keeps_an_explicit_plan(client: TestClient, org_a: UUID) -> None:
    handler = BillingWebhookHandler()
    kept = handler.handle(
        provider="mock",
        provider_event_id="created-omit-keeps-pro",
        event_type="subscription.created",
        payload={"organization_id": str(org_a)},
    )
    assert kept["result"]["plan_code"] == "pro"

    hosted = _blank_hosted_org()
    explicit = handler.handle(
        provider="mock",
        provider_event_id="created-explicit-enterprise",
        event_type="subscription.created",
        payload={"organization_id": str(hosted), "plan_code": "enterprise"},
    )
    svc = EntitlementService()
    assert explicit["result"]["plan_code"] == "enterprise"
    assert svc.plan_code_for_org(hosted) == "enterprise"
    assert svc.has_feature(hosted, "security.sso_enabled") is True


def test_immediate_cancel_keeps_verified_plan_fallback_and_blank_plan(
    client: TestClient,
    org_a: UUID,
    user_a_id: UUID,
) -> None:
    svc = EntitlementService()
    svc.upgrade(org_a, "enterprise", actor_user_id=user_a_id)
    cancelled = svc.cancel(org_a, at_period_end=False, actor_user_id=user_a_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["plan_code"] == "pro"
    assert svc.plan_code_for_org(org_a) == "pro"
    assert svc.has_feature(org_a, "security.sso_enabled") is False
    assert OrganizationRepository().get(org_a).plan_code == "pro"

    hosted = _blank_hosted_org()
    svc.ensure_subscription(hosted)
    blank_cancel = svc.cancel(hosted, at_period_end=False, actor_user_id=user_a_id)
    assert blank_cancel["status"] == "cancelled"
    assert blank_cancel["plan_code"] == ""
    assert svc.plan_code_for_org(hosted) == ""
    assert OrganizationRepository().get(hosted).plan_code == ""
    assert svc.has_feature(hosted, "process.discovery") is False
    with pytest.raises(LimitExceeded):
        svc.assert_meter(hosted, "process.monthly_runs", increment=1)

    blank_cancel["current_period_end"] = "2000-01-01T00:00:00+00:00"
    assert svc.plan_code_for_org(hosted) == ""


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


def test_blank_hosted_plan_is_not_stored_as_a_paid_plan(
    client: TestClient,
    user_a_id: UUID,
) -> None:
    org_id = uuid4()
    now = utcnow()
    store = get_memory_store()
    store.organizations[org_id] = OrganizationRecord(
        id=org_id,
        name=str(org_id),
        slug="",
        plan_code="",
        status="",
        row_version=1,
        created_at=now,
        updated_at=now,
    )
    svc = EntitlementService()
    sub = svc.ensure_subscription(org_id)
    assert sub["plan_code"] == ""
    assert svc.plan_code_for_org(org_id) == ""
    assert svc.has_feature(org_id, "process.discovery") is False
    assert svc.has_feature(org_id, "security.sso_enabled") is False
    assert svc.has_feature(org_id, "workers.dedicated_capacity") is False
    with pytest.raises(LimitExceeded):
        svc.assert_meter(org_id, "process.monthly_runs", increment=1)
    snap = svc.snapshot_for_org(org_id)
    assert snap["plan_code"] == ""
    assert snap["features"] == {}

    selected = OrganizationRepository().create(
        name="Explicit Plan Co",
        plan_code="enterprise",
        owner_user_id=user_a_id,
    )
    assert svc.plan_code_for_org(selected.id) == "enterprise"
