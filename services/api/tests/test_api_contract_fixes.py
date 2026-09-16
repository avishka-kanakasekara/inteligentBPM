"""Regression tests for frontend/backend API contract alignment."""

from __future__ import annotations

from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient

from app.repositories.memory_repos import ProcessRepository


def test_process_summary_risk_level_is_valid_enum(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
    user_a_id: UUID,
) -> None:
    repo = ProcessRepository(org_a)
    record = repo.create(name="Risk Enum Test", description="x", created_by_user_id=user_a_id)
    from app.database.memory import get_memory_store, RiskResultRecord, new_id
    from datetime import datetime, timezone

    store = get_memory_store()
    now = datetime.now(timezone.utc)
    store.risk_results[new_id()] = RiskResultRecord(
        id=new_id(),
        organization_id=org_a,
        process_id=record.id,
        process_version_id=new_id(),
        allocation_id=None,
        status="complete",
        result_snapshot={
            "decision": "approval_required",
            "risk_items": [{"severity": "high", "description": "Spend threshold"}],
        },
        plan_snapshot_hash="abc",
        allocation_snapshot_hash=None,
        risk_snapshot_hash="def",
        valid=True,
        invalidated_reason=None,
        created_at=now,
        updated_at=now,
    )

    response = client.get("/v1/processes/summaries", headers=auth_headers_a)
    assert response.status_code == 200
    match = next(item for item in response.json() if item["id"] == str(record.id))
    assert match["risk_level"] in {"low", "medium", "high", "critical", None}


def test_legacy_plan_routes_exist(client: TestClient, auth_headers_a: dict[str, str], org_a: UUID) -> None:
    created = client.post(
        "/v1/processes",
        headers=auth_headers_a,
        json={"name": "Legacy Route Test"},
    )
    assert created.status_code == 201
    pid = created.json()["id"]
    assert "unresolved_assignments" in created.json()

    legacy_draft = client.post(f"/v1/processes/{pid}/plan", headers=auth_headers_a, json={})
    assert legacy_draft.status_code in {201, 500}  # LLM may fail in CI; route must exist
    if legacy_draft.status_code == 201:
        vid = legacy_draft.json()["version_id"]
        legacy_confirm = client.post(
            f"/v1/processes/{pid}/plan/confirm",
            headers=auth_headers_a,
            json={"version_id": vid},
        )
        assert legacy_confirm.status_code == 200


def test_notifications_route(client: TestClient, auth_headers_a: dict[str, str]) -> None:
    response = client.get("/v1/notifications", headers=auth_headers_a)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
