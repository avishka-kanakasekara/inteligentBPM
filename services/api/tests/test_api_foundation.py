from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.v1.approvals import seed_approval
from app.domain.enums import OrgRole
from app.repositories.memory_repos import AuditRepository
from tests.conftest import add_membership, make_token


def test_authentication_required(client: TestClient) -> None:
    response = client.get("/v1/auth/me")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_UNAUTHORIZED"
    assert body["error"]["correlation_id"]


def test_authentication_me(client: TestClient, user_a_id: UUID, org_a: UUID) -> None:
    headers = {
        "Authorization": f"Bearer {make_token(user_a_id)}",
        "X-Organization-Id": str(org_a),
    }
    response = client.get("/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(user_a_id)


def test_tenant_context_required(client: TestClient, user_a_id: UUID) -> None:
    headers = {"Authorization": f"Bearer {make_token(user_a_id)}"}
    response = client.get("/v1/employees", headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TENANT_CONTEXT_REQUIRED"


def test_permission_checks(client: TestClient, org_a: UUID) -> None:
    employee_id = uuid4()
    add_membership(org_a, employee_id, OrgRole.EMPLOYEE)
    headers = {
        "Authorization": f"Bearer {make_token(employee_id)}",
        "X-Organization-Id": str(org_a),
    }
    denied = client.post(
        "/v1/employees",
        headers=headers,
        json={"full_name": "X", "email": "x@example.com"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "AUTH_FORBIDDEN"


def test_pagination_filtering_sorting(client: TestClient, auth_headers_a: dict[str, str]) -> None:
    for idx in range(5):
        client.post(
            "/v1/employees",
            headers=auth_headers_a,
            json={"full_name": f"Person {idx}", "email": f"p{idx}@example.com"},
        )
    response = client.get(
        "/v1/employees?limit=2&offset=0&sort=name&order=asc&q=Person",
        headers=auth_headers_a,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 5
    assert payload["meta"]["limit"] == 2
    assert len(payload["items"]) == 2
    assert payload["items"][0]["full_name"] <= payload["items"][1]["full_name"]


def test_idempotency(client: TestClient, auth_headers_a: dict[str, str], org_a: UUID) -> None:
    headers = {
        **auth_headers_a,
        "Idempotency-Key": "doc-key-1",
    }
    body = {
        "title": "Policy",
        "storage_path": f"{org_a}/policies/a.pdf",
    }
    first = client.post("/v1/documents", headers=headers, json=body)
    second = client.post("/v1/documents", headers=headers, json=body)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_cross_tenant_access_denied(
    client: TestClient,
    auth_headers_a: dict[str, str],
    auth_headers_b: dict[str, str],
    org_a: UUID,
    org_b: UUID,
) -> None:
    created = client.post(
        "/v1/documents",
        headers=auth_headers_a,
        json={"title": "A Doc", "storage_path": f"{org_a}/a.pdf"},
    )
    assert created.status_code == 201
    doc_id = created.json()["id"]

    denied = client.get(f"/v1/documents/{doc_id}", headers=auth_headers_b)
    assert denied.status_code == 404

    mismatch = client.post(
        "/v1/documents",
        headers=auth_headers_a,
        json={
            "title": "Bad",
            "storage_path": f"{org_a}/b.pdf",
            "organization_id": str(org_b),
        },
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "TENANT_MISMATCH"


def test_error_serialization(client: TestClient) -> None:
    response = client.get("/v1/auth/me")
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) >= {"code", "message", "correlation_id"}


def test_audit_event_creation(client: TestClient, auth_headers_a: dict[str, str]) -> None:
    response = client.post(
        "/v1/organizations",
        headers={"Authorization": auth_headers_a["Authorization"]},
        json={"name": "Audit Org", "plan_code": "pro"},
    )
    assert response.status_code == 201
    org_id = UUID(response.json()["id"])
    events = AuditRepository().list_for_org(org_id)
    assert any(event.action == "organization.created" for event in events)


def test_approval_decision_and_process_run(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
) -> None:
    process = client.post(
        "/v1/processes",
        headers=auth_headers_a,
        json={"name": "Proc 1", "description": "demo"},
    )
    assert process.status_code == 201
    process_id = process.json()["id"]

    version = client.post(
        f"/v1/processes/{process_id}/versions",
        headers=auth_headers_a,
        json={"plan_snapshot": {"steps": []}},
    )
    assert version.status_code == 201

    run = client.post(
        "/v1/process-runs",
        headers=auth_headers_a,
        json={"process_id": process_id, "process_version_id": version.json()["id"]},
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    paused = client.post(f"/v1/process-runs/{run_id}/pause", headers=auth_headers_a)
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = client.post(f"/v1/process-runs/{run_id}/resume", headers=auth_headers_a)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "executing"

    events = client.get(f"/v1/process-runs/{run_id}/events", headers=auth_headers_a)
    assert events.status_code == 200
    assert "text/event-stream" in events.headers["content-type"]

    approval = seed_approval(organization_id=org_a)
    decided = client.post(
        f"/v1/approvals/{approval.id}/decision",
        headers=auth_headers_a,
        json={"decision": "approved", "row_version": 1},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
