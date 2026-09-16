"""Agent 2 — Resource and Company Context Allocation tests."""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.agents.allocation.matcher import DeterministicResourceMatcher, OrgCatalog
from app.agents.allocation.models import ResourceType
from app.agents.discovery.models import ActionType, ProcessPlan, ProcessStep, RiskLevel
from app.database.memory import get_memory_store
from app.repositories.memory_repos import (
    BudgetRepository,
    CostCenterRepository,
    DepartmentRepository,
    EmployeeManagerLinkRepository,
    EmployeeRepository,
    ProcessRepository,
    SupplierContactRepository,
    SupplierProductRepository,
    SupplierRepository,
)


def _plan_with_resources(*requirements: str, step_id: str = "step_allocate") -> dict:
    plan = ProcessPlan(
        goal="Allocate resources for procurement",
        steps=[
            ProcessStep(
                step_id=step_id,
                action_type=ActionType.HUMAN_TASK,
                title="Allocate",
                description="Bind resources",
                required_resources=list(requirements),
                approval_requirements=[],
                success_criteria=["Resources bound"],
                risk_level=RiskLevel.MEDIUM,
            )
        ],
        reasoning_summary="Test plan for Agent 2",
    )
    return plan.model_dump(mode="json")


def _seed_process_version(org_id: UUID, plan_snapshot: dict) -> tuple[UUID, UUID]:
    processes = ProcessRepository(org_id)
    proc = processes.create(name="Allocation Process", description="test", created_by_user_id=None)
    version = processes.create_version(proc.id, plan_snapshot=plan_snapshot, status="draft")
    return proc.id, version.id


def test_exact_resource_matching(org_a: UUID, auth_headers_a: dict[str, str], client: TestClient) -> None:
    emp = EmployeeRepository(org_a).create(
        full_name="Alex Manager",
        email="alex@example.com",
        is_manager=True,
        role_code="manager",
        approval_authority_limit=5000,
    )
    process_id, _ = _seed_process_version(
        org_a, _plan_with_resources("Alex Manager", "alex@example.com")
    )
    # One requirement exact name; create plan with single exact email to avoid double
    process_id, _ = _seed_process_version(org_a, _plan_with_resources("alex@example.com"))

    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["side_effects_executed"] is False
    assert body["invented_resources"] is False
    assert len(body["assignments"]) == 1
    assert body["assignments"][0]["resource_id"] == str(emp.id)
    assert body["assignments"][0]["active_status"] is True
    assert body["assignments"][0]["authorization_status"] == "authorized"
    assert body["status"] == "resolved"

    fetched = client.get(f"/v1/processes/{process_id}/allocation", headers=auth_headers_a)
    assert fetched.status_code == 200
    assert fetched.json()["assignments"][0]["resource_id"] == str(emp.id)


def test_ambiguous_names_request_clarification(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(full_name="Jordan Lee", email="j1@example.com")
    EmployeeRepository(org_a).create(full_name="Jordan Lee", email="j2@example.com")
    process_id, _ = _seed_process_version(org_a, _plan_with_resources("Jordan Lee"))

    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert len(body["candidates"]) >= 2
    assert body["unresolved"]
    assert body["clarifying_questions"]


def test_inactive_employees_not_assigned(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    emp = EmployeeRepository(org_a).create(
        full_name="Inactive Sam",
        email="sam@example.com",
        status="inactive",
    )
    process_id, _ = _seed_process_version(org_a, _plan_with_resources("Inactive Sam"))

    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assignments"] == []
    assert any(c["conflict_status"] == "inactive" for c in body["conflicts"])
    assert str(emp.id) in {c["resource_id"] for c in body["candidates"]} or any(
        str(emp.id) in {x["resource_id"] for x in c.get("candidates", [])}
        for c in body["conflicts"]
    )


def test_unapproved_suppliers_blocked(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    SupplierRepository(org_a).create(
        name="Contoso",
        code="CO-1",
        approval_status="pending",
    )
    process_id, _ = _seed_process_version(org_a, _plan_with_resources("Contoso"))

    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assignments"] == []
    assert any(c["conflict_status"] == "unapproved" for c in body["conflicts"])


def test_missing_supplier_contacts(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    SupplierRepository(org_a).create(
        name="Northwind",
        code="NW-1",
        approval_status="approved",
    )
    process_id, _ = _seed_process_version(org_a, _plan_with_resources("Northwind"))

    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(c["conflict_status"] == "missing_contact" for c in body["conflicts"])
    assert any(u["resource_type"] == "supplier_contact" for u in body["unresolved"])


def test_approved_supplier_with_contact_assigns(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    supplier = SupplierRepository(org_a).create(
        name="Acme Supplies",
        code="ACME",
        approval_status="approved",
    )
    SupplierContactRepository(org_a).create(
        supplier_id=supplier.id,
        full_name="Pat Contact",
        email="pat@acme.test",
        is_primary=True,
    )
    process_id, _ = _seed_process_version(org_a, _plan_with_resources("Acme Supplies"))

    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["assignments"]) == 1
    assert body["assignments"][0]["resource_id"] == str(supplier.id)
    assert body["status"] == "resolved"


def test_budget_ownership(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    dept = DepartmentRepository(org_a).create(name="Engineering", code="ENG")
    other = DepartmentRepository(org_a).create(name="Sales", code="SAL")
    BudgetRepository(org_a).create(
        name="Eng FY26",
        fiscal_year=2026,
        amount_total=100000,
        department_id=dept.id,
    )
    BudgetRepository(org_a).create(
        name="Sales FY26",
        fiscal_year=2026,
        amount_total=50000,
        department_id=other.id,
    )
    # Requirement "budget" with Engineering as only matching dept via intent/resources
    plan = ProcessPlan(
        goal="Spend engineering budget",
        steps=[
            ProcessStep(
                step_id="step_budget",
                action_type=ActionType.HUMAN_TASK,
                title="Use budget",
                description="Bind engineering budget",
                required_resources=["Engineering", "budget"],
                success_criteria=["Budget bound"],
            )
        ],
    )
    process_id, _ = _seed_process_version(org_a, plan.model_dump(mode="json"))

    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    budget_assignments = [a for a in body["assignments"] if a["resource_type"] == "budget"]
    assert len(budget_assignments) == 1
    assert budget_assignments[0]["display_name"] == "Eng FY26"


def test_manager_hierarchy(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    manager = EmployeeRepository(org_a).create(
        full_name="Alex Manager",
        email="alex@example.com",
        is_manager=True,
    )
    worker = EmployeeRepository(org_a).create(
        full_name="Sam Worker",
        email="sam@example.com",
        is_manager=False,
    )
    EmployeeManagerLinkRepository(org_a).create(
        employee_id=worker.id,
        manager_employee_id=manager.id,
    )
    plan = ProcessPlan(
        goal="Manager approval",
        intent={
            "goal": "Manager approval",
            "actors": ["Sam Worker"],
        },
        steps=[
            ProcessStep(
                step_id="step_approve",
                action_type=ActionType.APPROVAL,
                title="Approve",
                description="Manager approval",
                required_resources=["manager"],
                approval_requirements=["manager"],
                success_criteria=["Approved"],
            )
        ],
    )
    process_id, _ = _seed_process_version(org_a, plan.model_dump(mode="json"))

    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # manager requirement may appear twice (required + approval) — both should resolve to Alex
    assert body["assignments"]
    assert all(a["resource_id"] == str(manager.id) for a in body["assignments"])
    assert all(a["data_source"] == "manager_link" for a in body["assignments"])


def test_cross_organization_lookup_prevention(
    org_a: UUID,
    org_b: UUID,
    auth_headers_a: dict[str, str],
    auth_headers_b: dict[str, str],
    client: TestClient,
) -> None:
    EmployeeRepository(org_b).create(
        full_name="Secret Employee",
        email="secret@orgb.test",
    )
    process_id, _ = _seed_process_version(org_a, _plan_with_resources("Secret Employee"))

    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assignments"] == []
    # Must not leak org B employee as candidate
    names = {c["display_name"] for c in body["candidates"]}
    assert "Secret Employee" not in names

    # Org B cannot allocate against org A process
    blocked = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_b,
        json={},
    )
    assert blocked.status_code in {403, 404}

    # Matcher assert_tenant raises on foreign resource
    catalog = OrgCatalog(organization_id=org_a)
    foreign = EmployeeRepository(org_b).list_all()[0]
    matcher = DeterministicResourceMatcher(catalog)
    try:
        catalog.assert_tenant(foreign.organization_id)
        raise AssertionError("expected cross-tenant denial")
    except ValueError as exc:
        assert "cross-organization" in str(exc)


def test_department_manager_org_rule(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    mgr = EmployeeRepository(org_a).create(
        full_name="Dept Head",
        email="head@example.com",
        is_manager=True,
    )
    EmployeeRepository(org_a).create(
        full_name="Other Manager",
        email="other@example.com",
        is_manager=True,
    )
    DepartmentRepository(org_a).create(
        name="Operations",
        code="OPS",
        manager_employee_id=mgr.id,
    )
    plan = ProcessPlan(
        goal="Ops approval",
        steps=[
            ProcessStep(
                step_id="step_mgr",
                action_type=ActionType.APPROVAL,
                title="Ops manager",
                description="Use department manager",
                required_resources=["Operations", "manager"],
                success_criteria=["Assigned"],
            )
        ],
    )
    process_id, _ = _seed_process_version(org_a, plan.model_dump(mode="json"))
    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    mgr_assignments = [a for a in body["assignments"] if a["resource_type"] == "manager"]
    assert len(mgr_assignments) == 1
    assert mgr_assignments[0]["resource_id"] == str(mgr.id)
    assert mgr_assignments[0]["data_source"] == "department_rule"


def test_cost_center_and_product_exact_match(org_a: UUID) -> None:
    cc = CostCenterRepository(org_a).create(code="CC-100", name="Platform")
    supplier = SupplierRepository(org_a).create(
        name="GadgetCo", approval_status="approved"
    )
    product = SupplierProductRepository(org_a).create(
        supplier_id=supplier.id,
        name="Laptop Pro",
        sku="LP-1",
        unit_price=1200,
    )
    catalog = OrgCatalog(
        organization_id=org_a,
        cost_centers=CostCenterRepository(org_a).list_all(),
        products=SupplierProductRepository(org_a).list_all(),
        suppliers=SupplierRepository(org_a).list_all(),
        contacts=SupplierContactRepository(org_a).list_all(),
        employees=[],
        departments=[],
        budgets=[],
        manager_links=[],
    )
    matcher = DeterministicResourceMatcher(catalog)
    cc_out = matcher.match(step_id="s1", requirement="CC-100")
    assert cc_out.assigned is not None
    assert cc_out.assigned.resource_id == str(cc.id)
    assert cc_out.assigned.resource_type == ResourceType.COST_CENTER

    prod_out = matcher.match(step_id="s1", requirement="LP-1")
    assert prod_out.assigned is not None
    assert prod_out.assigned.resource_id == str(product.id)
    assert prod_out.assigned.resource_type == ResourceType.PRODUCT


def test_clarification_choice_resolves_ambiguity(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    a = EmployeeRepository(org_a).create(full_name="Jordan Lee", email="j1@example.com")
    EmployeeRepository(org_a).create(full_name="Jordan Lee", email="j2@example.com")
    process_id, version_id = _seed_process_version(
        org_a, _plan_with_resources("Jordan Lee")
    )

    first = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={"process_version_id": str(version_id)},
    )
    assert first.json()["status"] == "needs_clarification"

    resolved = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={
            "process_version_id": str(version_id),
            "clarification_choices": [
                {
                    "step_id": "step_allocate",
                    "requirement": "Jordan Lee",
                    "resource_id": str(a.id),
                    "resource_type": "employee",
                }
            ],
        },
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "resolved"
    assert body["assignments"][0]["resource_id"] == str(a.id)
    assert body["assignments"][0]["data_source"] == "user_clarification"


def test_integrations_listed_without_side_effects(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="Solo",
        email="solo@example.com",
        is_manager=True,
    )
    process_id, _ = _seed_process_version(org_a, _plan_with_resources("solo@example.com"))
    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    keys = {i["key"] for i in body["integrations"]}
    assert "email" in keys
    assert "purchasing" in keys
    assert body["side_effects_executed"] is False
    # Ensure no org mutation from allocation
    before = len(get_memory_store().employees)
    client.post(f"/v1/processes/{process_id}/allocate", headers=auth_headers_a, json={})
    assert len(get_memory_store().employees) == before
