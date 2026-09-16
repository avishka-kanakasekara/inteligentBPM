"""Permission boundaries, RBAC roles, and multi-tenant isolation tests."""

from __future__ import annotations

from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient

from app.domain.enums import OrgRole
from app.permissions.codes import (
    APPROVALS_DECIDE,
    AUDIT_READ,
    BILLING_MANAGE,
    DOCUMENTS_UPLOAD,
    EXECUTION_RUN,
    PROCESSES_CREATE,
    permissions_for_role,
)
from tests.conftest import add_membership, make_token


def test_rbac_role_permission_hierarchy() -> None:
    owner_perms = permissions_for_role(OrgRole.OWNER)
    admin_perms = permissions_for_role(OrgRole.ADMIN)
    manager_perms = permissions_for_role(OrgRole.MANAGER)
    employee_perms = permissions_for_role(OrgRole.EMPLOYEE)
    auditor_perms = permissions_for_role(OrgRole.AUDITOR)

    # Owner & Admin have full business management
    assert BILLING_MANAGE in owner_perms
    assert BILLING_MANAGE in admin_perms

    # Manager has execution and approval authority, but not billing
    assert APPROVALS_DECIDE in manager_perms
    assert EXECUTION_RUN in manager_perms
    assert BILLING_MANAGE not in manager_perms

    # Employee can create processes and read info, but cannot approve or execute runs
    assert PROCESSES_CREATE in employee_perms
    assert APPROVALS_DECIDE not in employee_perms
    assert EXECUTION_RUN not in employee_perms
    assert BILLING_MANAGE not in employee_perms

    # Auditor has read-only audit capabilities
    assert AUDIT_READ in auditor_perms
    assert PROCESSES_CREATE not in auditor_perms
    assert APPROVALS_DECIDE not in auditor_perms
    assert DOCUMENTS_UPLOAD not in auditor_perms


def test_tenant_isolation_employees(
    client: TestClient,
    auth_headers_a: dict[str, str],
    auth_headers_b: dict[str, str],
) -> None:
    # Org A creates an employee
    resp_create = client.post(
        "/v1/employees",
        headers=auth_headers_a,
        json={
            "full_name": "Org A Worker",
            "email": "worker@org-a.com",
            "title": "Engineer",
        },
    )
    assert resp_create.status_code == 201
    emp_id = resp_create.json()["id"]

    # Org A can fetch the employee
    resp_get_a = client.get(f"/v1/employees/{emp_id}", headers=auth_headers_a)
    assert resp_get_a.status_code == 200
    assert resp_get_a.json()["full_name"] == "Org A Worker"

    # Org B CANNOT fetch Org A's employee (returns 404, no data leakage)
    resp_get_b = client.get(f"/v1/employees/{emp_id}", headers=auth_headers_b)
    assert resp_get_b.status_code == 404

    # Org B list does not contain Org A's employee
    resp_list_b = client.get("/v1/employees", headers=auth_headers_b)
    assert resp_list_b.status_code == 200
    b_ids = [e["id"] for e in resp_list_b.json().get("items", [])]
    assert emp_id not in b_ids


def test_tenant_isolation_suppliers(
    client: TestClient,
    auth_headers_a: dict[str, str],
    auth_headers_b: dict[str, str],
) -> None:
    # Org A creates a supplier
    resp_create = client.post(
        "/v1/suppliers",
        headers=auth_headers_a,
        json={
            "name": "Acme Hardware Partner",
            "code": "ACME-HW",
            "approval_status": "approved",
        },
    )
    assert resp_create.status_code == 201
    sup_id = resp_create.json()["id"]

    # Org B cannot view or update Org A's supplier
    resp_b_get = client.get(f"/v1/suppliers/{sup_id}", headers=auth_headers_b)
    assert resp_b_get.status_code == 404

    resp_b_update = client.patch(
        f"/v1/suppliers/{sup_id}",
        headers=auth_headers_b,
        json={"name": "Hacked Supplier"},
    )
    assert resp_b_update.status_code == 404


def test_tenant_header_spoofing_rejected(
    client: TestClient,
    user_a_id: UUID,
    org_b: UUID,
) -> None:
    # User A presents token for User A, but specifies Org B (where User A is NOT a member)
    spoofed_headers = {
        "Authorization": f"Bearer {make_token(user_a_id, email='user_a@example.com')}",
        "X-Organization-Id": str(org_b),
    }

    resp = client.get("/v1/employees", headers=spoofed_headers)
    assert resp.status_code == 403
    assert "Forbidden" in resp.text or "not a member" in resp.text.lower() or "forbidden" in resp.text.lower()


def test_missing_and_invalid_tenant_headers(client: TestClient, user_a_id: UUID) -> None:
    valid_token = make_token(user_a_id)

    # Missing X-Organization-Id
    resp_missing = client.get(
        "/v1/employees",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert resp_missing.status_code in {400, 422}

    # Invalid UUID in X-Organization-Id
    resp_invalid = client.get(
        "/v1/employees",
        headers={
            "Authorization": f"Bearer {valid_token}",
            "X-Organization-Id": "not-a-valid-uuid",
        },
    )
    assert resp_invalid.status_code in {400, 422}


def test_unauthenticated_request_rejected(client: TestClient, org_a: UUID) -> None:
    resp = client.get(
        "/v1/employees",
        headers={"X-Organization-Id": str(org_a)},
    )
    assert resp.status_code in {401, 403}


def test_employee_role_permission_restrictions(
    client: TestClient,
    org_a: UUID,
) -> None:
    # Create an employee-only user in Org A
    emp_user_id = uuid4()
    add_membership(org_a, emp_user_id, role=OrgRole.EMPLOYEE)

    emp_headers = {
        "Authorization": f"Bearer {make_token(emp_user_id, email='employee@org-a.com')}",
        "X-Organization-Id": str(org_a),
    }

    # Employee CAN read employees
    read_resp = client.get("/v1/employees", headers=emp_headers)
    assert read_resp.status_code == 200

    # Employee CANNOT configure billing
    billing_resp = client.post(
        "/v1/billing/subscription/upgrade",
        headers=emp_headers,
        json={"plan_code": "enterprise"},
    )
    assert billing_resp.status_code == 403
