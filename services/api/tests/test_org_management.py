"""Organization management tests: imports, duplicates, roles, inactive, audit, isolation."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.domain.enums import OrgRole
from app.repositories.memory_repos import AuditRepository
from app.services.org_management import EmployeeService, SupplierService
from tests.conftest import add_membership, make_token


EMPLOYEE_CSV = """full_name,email,title,is_manager,role_code,approval_authority_limit
Alex Manager,alex@example.com,Ops Manager,true,manager,5000
Sam Worker,sam@example.com,Buyer,false,employee,
"""

SUPPLIER_CSV = """name,code,approval_status,contact_name,contact_email
Northwind,NW-1,approved,Pat Contact,pat@northwind.test
Contoso,CO-1,pending,Casey Contact,casey@contoso.test
"""


def test_employee_import_preview_and_commit(
    client: TestClient, auth_headers_a: dict[str, str]
) -> None:
    preview = client.post(
        "/v1/imports/employees/preview",
        headers=auth_headers_a,
        json={"csv_content": EMPLOYEE_CSV},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["total_rows"] == 2
    assert body["valid_count"] == 2
    assert body["error_count"] == 0

    commit = client.post(
        "/v1/imports/employees/commit",
        headers=auth_headers_a,
        json={"csv_content": EMPLOYEE_CSV},
    )
    assert commit.status_code == 200
    assert commit.json()["created_count"] == 2

    listed = client.get("/v1/employees?q=Alex", headers=auth_headers_a)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] >= 1


def test_employee_import_duplicate_detection(
    client: TestClient, auth_headers_a: dict[str, str]
) -> None:
    client.post(
        "/v1/employees",
        headers=auth_headers_a,
        json={"full_name": "Existing", "email": "dup@example.com"},
    )
    csv_content = (
        "full_name,email\n"
        "One,dup@example.com\n"
        "Two,dup@example.com\n"
    )
    preview = client.post(
        "/v1/imports/employees/preview",
        headers=auth_headers_a,
        json={"csv_content": csv_content},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["duplicate_count"] >= 1
    codes = {d["code"] for d in body["duplicates"]}
    assert "DUPLICATE_ACTIVE" in codes or "DUPLICATE_IN_FILE" in codes

    denied = client.post(
        "/v1/imports/employees/commit",
        headers=auth_headers_a,
        json={"csv_content": csv_content},
    )
    assert denied.status_code == 422


def test_supplier_import_and_approval_rules(
    client: TestClient, auth_headers_a: dict[str, str], org_a: UUID
) -> None:
    preview = client.post(
        "/v1/imports/suppliers/preview",
        headers=auth_headers_a,
        json={"csv_content": SUPPLIER_CSV},
    )
    assert preview.status_code == 200
    assert preview.json()["valid_count"] == 2

    commit = client.post(
        "/v1/imports/suppliers/commit",
        headers=auth_headers_a,
        json={"csv_content": SUPPLIER_CSV},
    )
    assert commit.status_code == 200

    suppliers = client.get("/v1/suppliers", headers=auth_headers_a).json()["items"]
    pending = next(s for s in suppliers if s["name"] == "Contoso")
    approved = next(s for s in suppliers if s["name"] == "Northwind")
    assert pending["approval_status"] == "pending"
    assert approved["approval_status"] == "approved"

    service = SupplierService(org_a)
    service.assert_approved(UUID(approved["id"]))
    try:
        service.assert_approved(UUID(pending["id"]))
        raise AssertionError("expected unapproved supplier rejection")
    except Exception as exc:  # ValidationAppError
        assert "Unapproved" in str(exc)


def test_duplicate_supplier_contact_email(
    client: TestClient, auth_headers_a: dict[str, str]
) -> None:
    created = client.post(
        "/v1/suppliers",
        headers=auth_headers_a,
        json={"name": "Vendor A", "approval_status": "approved"},
    )
    supplier_id = created.json()["id"]
    first = client.post(
        "/v1/supplier-contacts",
        headers=auth_headers_a,
        json={
            "supplier_id": supplier_id,
            "full_name": "A",
            "email": "shared@vendor.test",
        },
    )
    assert first.status_code == 201
    duplicate = client.post(
        "/v1/supplier-contacts",
        headers=auth_headers_a,
        json={
            "supplier_id": supplier_id,
            "full_name": "B",
            "email": "shared@vendor.test",
        },
    )
    assert duplicate.status_code == 409

    allowed = client.post(
        "/v1/supplier-contacts",
        headers=auth_headers_a,
        json={
            "supplier_id": supplier_id,
            "full_name": "C",
            "email": "shared@vendor.test",
            "allow_duplicate_email": True,
        },
    )
    assert allowed.status_code == 201


def test_role_restrictions_on_directory_and_org_config(
    client: TestClient, org_a: UUID
) -> None:
    employee_id = uuid4()
    add_membership(org_a, employee_id, OrgRole.EMPLOYEE)
    headers = {
        "Authorization": f"Bearer {make_token(employee_id)}",
        "X-Organization-Id": str(org_a),
    }
    denied_employee = client.post(
        "/v1/employees",
        headers=headers,
        json={"full_name": "Nope", "email": "nope@example.com"},
    )
    assert denied_employee.status_code == 403

    denied_import = client.post(
        "/v1/imports/employees/preview",
        headers=headers,
        json={"csv_content": EMPLOYEE_CSV},
    )
    assert denied_import.status_code == 403

    denied_profile = client.patch(
        f"/v1/organizations/{org_a}",
        headers=headers,
        json={"legal_name": "Blocked Corp"},
    )
    assert denied_profile.status_code == 403


def test_inactive_employee_cannot_be_assigned(
    client: TestClient, auth_headers_a: dict[str, str], org_a: UUID
) -> None:
    created = client.post(
        "/v1/employees",
        headers=auth_headers_a,
        json={"full_name": "Temp", "email": "temp@example.com"},
    )
    employee_id = UUID(created.json()["id"])
    deactivated = client.post(
        f"/v1/employees/{employee_id}/deactivate",
        headers=auth_headers_a,
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "inactive"

    # Soft-deactivated employee remains readable (historical refs stay valid).
    fetched = client.get(f"/v1/employees/{employee_id}", headers=auth_headers_a)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "inactive"

    service = EmployeeService(org_a)
    try:
        service.assert_assignable(employee_id)
        raise AssertionError("expected inactive assignment rejection")
    except Exception as exc:
        assert "Inactive employees" in str(exc)


def test_org_profile_update_and_audit(
    client: TestClient, auth_headers_a: dict[str, str], org_a: UUID
) -> None:
    updated = client.patch(
        f"/v1/organizations/{org_a}",
        headers=auth_headers_a,
        json={
            "legal_name": "Demo Legal LLC",
            "trading_name": "Demo Trading",
            "industry": "Technology",
            "country_code": "US",
            "default_timezone": "America/New_York",
            "default_currency": "USD",
            "tax_id": "12-3456789",
            "tax_information": {"vat_registered": True},
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["legal_name"] == "Demo Legal LLC"
    assert body["default_timezone"] == "America/New_York"
    assert body["tax_information"]["vat_registered"] is True

    events = AuditRepository().list_for_org(org_a)
    assert any(e.action == "organization.profile_updated" for e in events)


def test_cross_tenant_isolation_for_employees(
    client: TestClient,
    auth_headers_a: dict[str, str],
    auth_headers_b: dict[str, str],
) -> None:
    created = client.post(
        "/v1/employees",
        headers=auth_headers_a,
        json={"full_name": "Tenant A", "email": "a-only@example.com"},
    )
    assert created.status_code == 201
    employee_id = created.json()["id"]

    denied = client.get(f"/v1/employees/{employee_id}", headers=auth_headers_b)
    assert denied.status_code == 404

    listed_b = client.get("/v1/employees?q=Tenant", headers=auth_headers_b)
    assert listed_b.status_code == 200
    assert listed_b.json()["meta"]["total"] == 0


def test_cost_centers_budgets_policies_and_departments(
    client: TestClient, auth_headers_a: dict[str, str]
) -> None:
    dept = client.post(
        "/v1/departments",
        headers=auth_headers_a,
        json={"name": "Finance", "code": "FIN"},
    )
    assert dept.status_code == 201
    dept_id = dept.json()["id"]

    cc = client.post(
        "/v1/cost-centers",
        headers=auth_headers_a,
        json={"code": "CC-100", "name": "Ops Cost Center", "department_id": dept_id},
    )
    assert cc.status_code == 201

    budget = client.post(
        "/v1/budgets",
        headers=auth_headers_a,
        json={
            "name": "FY26 Ops",
            "fiscal_year": 2026,
            "amount_total": 100000,
            "department_id": dept_id,
            "cost_center_id": cc.json()["id"],
        },
    )
    assert budget.status_code == 201

    policy = client.post(
        "/v1/policies",
        headers=auth_headers_a,
        json={
            "code": "PROC-001",
            "title": "Procurement",
            "category": "procurement",
            "metadata": {"owner_team": "finance"},
        },
    )
    assert policy.status_code == 201
    assert policy.json()["metadata"]["owner_team"] == "finance"

    roles = client.get("/v1/roles", headers=auth_headers_a)
    assert roles.status_code == 200
    assert any(r["code"] == "admin" for r in roles.json())


def test_ambiguous_manager_not_guessed(
    client: TestClient, auth_headers_a: dict[str, str]
) -> None:
    manager = client.post(
        "/v1/employees",
        headers=auth_headers_a,
        json={
            "full_name": "Mgr",
            "email": "mgr@example.com",
            "is_manager": True,
        },
    )
    employee = client.post(
        "/v1/employees",
        headers=auth_headers_a,
        json={"full_name": "Emp", "email": "emp@example.com"},
    )
    other_mgr = client.post(
        "/v1/employees",
        headers=auth_headers_a,
        json={
            "full_name": "Mgr2",
            "email": "mgr2@example.com",
            "is_manager": True,
        },
    )
    first = client.post(
        "/v1/manager-links",
        headers=auth_headers_a,
        json={
            "employee_id": employee.json()["id"],
            "manager_employee_id": manager.json()["id"],
        },
    )
    assert first.status_code == 201
    second = client.post(
        "/v1/manager-links",
        headers=auth_headers_a,
        json={
            "employee_id": employee.json()["id"],
            "manager_employee_id": other_mgr.json()["id"],
        },
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "AMBIGUOUS_MANAGER"
