"""Agent 2 — Resource and Company Context Allocation tests."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.agents.allocation.matcher import (
    DeterministicResourceMatcher,
    OrgCatalog,
    infer_resource_type,
)
from app.agents.allocation.models import ResourceType
from app.agents.allocation.service import AllocationService
from app.agents.discovery.models import ActionType, ProcessPlan, ProcessStep, RiskLevel
from app.database.memory import get_memory_store
from app.llm.client import FakeGeminiClient
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


def _allocate_requirement(
    client: TestClient,
    org_id: UUID,
    headers: dict[str, str],
    requirement: str,
) -> dict:
    process_id, _ = _seed_process_version(org_id, _plan_with_resources(requirement))
    response = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=headers,
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_skill_match_prefers_lower_workload(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="Employee A",
        email="a@example.com",
        primary_skills=["Python"],
        current_workload_percent=90,
    )
    employee_b = EmployeeRepository(org_a).create(
        full_name="Employee B",
        email="b@example.com",
        primary_skills=["Python"],
        current_workload_percent=30,
    )
    EmployeeRepository(org_a).create(
        full_name="Employee C",
        email="c@example.com",
        primary_skills=["Java"],
        current_workload_percent=10,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Python")
    assert body["status"] == "resolved"
    assert len(body["assignments"]) == 1
    assignment = body["assignments"][0]
    assert assignment["resource_id"] == str(employee_b.id)
    assert assignment["display_name"] == "Employee B"
    assert "primary skill match" in assignment["reason"]
    assert "30%" in assignment["reason"]
    assert float(employee_b.baseline_workload_percent) == 30
    assert float(employee_b.current_workload_percent) == 40


def test_skill_match_skips_employee_at_max_allocation(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    employee_a = EmployeeRepository(org_a).create(
        full_name="Employee A",
        email="a@example.com",
        primary_skills=["Python"],
        current_workload_percent=90,
        max_allocation_percent=100,
    )
    EmployeeRepository(org_a).create(
        full_name="Employee B",
        email="b@example.com",
        primary_skills=["Python"],
        current_workload_percent=100,
        max_allocation_percent=100,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Python")
    assert body["assignments"][0]["resource_id"] == str(employee_a.id)


def test_primary_skill_outranks_lower_secondary_workload(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="Employee A",
        email="a@example.com",
        secondary_skills=["Python"],
        current_workload_percent=20,
    )
    employee_b = EmployeeRepository(org_a).create(
        full_name="Employee B",
        email="b@example.com",
        primary_skills=["Python"],
        current_workload_percent=50,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Python")
    assert body["assignments"][0]["resource_id"] == str(employee_b.id)
    assert "primary skill match" in body["assignments"][0]["reason"]


def test_skill_match_skips_zero_availability(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="Employee A",
        email="a@example.com",
        primary_skills=["Python"],
        availability_percent=0,
        current_workload_percent=10,
    )
    employee_b = EmployeeRepository(org_a).create(
        full_name="Employee B",
        email="b@example.com",
        primary_skills=["Python"],
        availability_percent=80,
        current_workload_percent=40,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Python")
    assert body["assignments"][0]["resource_id"] == str(employee_b.id)


def test_exact_name_beats_better_skill_workload(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    employee_a = EmployeeRepository(org_a).create(
        full_name="Employee A",
        email="a@example.com",
        primary_skills=["Python"],
        current_workload_percent=90,
    )
    EmployeeRepository(org_a).create(
        full_name="Employee B",
        email="b@example.com",
        primary_skills=["Python"],
        current_workload_percent=10,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Employee A")
    assignment = body["assignments"][0]
    assert assignment["resource_id"] == str(employee_a.id)
    assert assignment["reason"] == "Exact directory match"


def _questions(body: dict) -> str:
    parts = list(body.get("clarifying_questions") or [])
    parts.extend(item.get("question", "") for item in body.get("unresolved") or [])
    parts.extend(item.get("message", "") for item in body.get("conflicts") or [])
    return " ".join(parts)


def _pin_at_capacity(org_id: UUID, *keep_ids: UUID) -> None:
    kept = set(keep_ids)
    for employee in EmployeeRepository(org_id).list_all():
        if employee.id in kept:
            continue
        employee.current_workload_percent = float(employee.max_allocation_percent)


def test_explicit_name_below_max_is_selected(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Capacity Open",
        email="capacity-open@example.com",
        current_workload_percent=40,
        max_allocation_percent=80,
        availability_percent=100,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Capacity Open")
    assert body["status"] == "resolved"
    assert body["assignments"][0]["resource_id"] == str(employee.id)
    assert body["assignments"][0]["reason"] == "Exact directory match"


def test_explicit_name_at_max_is_not_replaced(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    named = EmployeeRepository(org_a).create(
        full_name="Named Employee",
        email="named-employee@example.com",
        current_workload_percent=80,
        max_allocation_percent=80,
    )
    other = EmployeeRepository(org_a).create(
        full_name="Someone Else",
        email="someone-else@example.com",
        primary_skills=["Named Employee"],
        current_workload_percent=10,
        max_allocation_percent=100,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Named Employee")
    assigned = {item["resource_id"] for item in body["assignments"]}
    assert str(named.id) not in assigned
    assert str(other.id) not in assigned
    assert body["status"] == "needs_clarification"
    assert body["unresolved"]
    assert "Named Employee is at maximum allocation capacity." in _questions(body)


def test_exact_email_at_max_is_not_selected(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Mailbox Max",
        email="mailbox-max@example.com",
        current_workload_percent=90,
        max_allocation_percent=90,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "mailbox-max@example.com")
    assert str(employee.id) not in {item["resource_id"] for item in body["assignments"]}
    assert body["status"] == "needs_clarification"
    assert "Mailbox Max is at maximum allocation capacity." in _questions(body)


def test_exact_employee_code_at_max_is_not_selected(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Code Max",
        email="code-max@example.com",
        employee_code="CAP-900",
        current_workload_percent=70,
        max_allocation_percent=70,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "CAP-900")
    assert str(employee.id) not in {item["resource_id"] for item in body["assignments"]}
    assert body["status"] == "needs_clarification"
    assert "Code Max is at maximum allocation capacity." in _questions(body)


def test_role_match_skips_overloaded_employee(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="Role Max",
        email="role-max@example.com",
        role_code="workload_clerk",
        current_workload_percent=80,
        max_allocation_percent=80,
    )
    eligible = EmployeeRepository(org_a).create(
        full_name="Role Open",
        email="role-open@example.com",
        role_code="workload_clerk",
        current_workload_percent=20,
        max_allocation_percent=80,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "workload_clerk")
    assert body["assignments"][0]["resource_id"] == str(eligible.id)


def test_manager_match_skips_overloaded_manager(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    overloaded = EmployeeRepository(org_a).create(
        full_name="Overloaded Manager",
        email="overloaded-manager@example.com",
        is_manager=True,
        current_workload_percent=100,
        max_allocation_percent=100,
    )
    eligible = EmployeeRepository(org_a).create(
        full_name="Eligible Manager",
        email="eligible-manager@example.com",
        is_manager=True,
        current_workload_percent=30,
        max_allocation_percent=100,
    )
    worker = EmployeeRepository(org_a).create(
        full_name="Capacity Worker",
        email="capacity-worker@example.com",
    )
    EmployeeManagerLinkRepository(org_a).create(
        employee_id=worker.id,
        manager_employee_id=overloaded.id,
    )
    EmployeeManagerLinkRepository(org_a).create(
        employee_id=worker.id,
        manager_employee_id=eligible.id,
    )
    plan = ProcessPlan(
        goal="Manager approval",
        intent={"goal": "Manager approval", "actors": ["Capacity Worker"]},
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
    assigned = {item["resource_id"] for item in body["assignments"]}
    assert str(overloaded.id) not in assigned
    assert assigned == {str(eligible.id)}
    assert all(item["data_source"] == "manager_link" for item in body["assignments"])


def test_approval_skips_highest_authority_at_max(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="High Approver",
        email="high-approver@example.com",
        is_manager=True,
        role_code="manager",
        approval_authority_limit=1000000,
        current_workload_percent=100,
        max_allocation_percent=100,
    )
    eligible = EmployeeRepository(org_a).create(
        full_name="Eligible Approver",
        email="eligible-approver@example.com",
        approval_authority_limit=5000,
        current_workload_percent=40,
        max_allocation_percent=100,
    )
    _pin_at_capacity(org_a, eligible.id)
    body = _allocate_requirement(client, org_a, auth_headers_a, "approval authority")
    assert body["assignments"][0]["resource_id"] == str(eligible.id)
    assert body["assignments"][0]["resource_type"] == "approval_authority"


def test_approval_unresolved_when_every_approver_is_at_max(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="Blocked High",
        email="blocked-high@example.com",
        is_manager=True,
        role_code="owner",
        approval_authority_limit=1000000,
        current_workload_percent=100,
        max_allocation_percent=100,
    )
    EmployeeRepository(org_a).create(
        full_name="Blocked Low",
        email="blocked-low@example.com",
        approval_authority_limit=5000,
        current_workload_percent=80,
        max_allocation_percent=80,
    )
    _pin_at_capacity(org_a)
    body = _allocate_requirement(client, org_a, auth_headers_a, "approval authority")
    assert body["assignments"] == []
    assert body["status"] == "needs_clarification"
    assert body["unresolved"]
    assert "maximum allocation capacity" in _questions(body)


def test_skill_ranking_unchanged_when_candidates_are_eligible(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="Skill Heavy",
        email="skill-heavy@example.com",
        primary_skills=["Python"],
        current_workload_percent=90,
        max_allocation_percent=100,
    )
    lighter = EmployeeRepository(org_a).create(
        full_name="Skill Light",
        email="skill-light@example.com",
        primary_skills=["Python"],
        current_workload_percent=30,
        max_allocation_percent=100,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Python")
    assignment = body["assignments"][0]
    assert assignment["resource_id"] == str(lighter.id)
    assert "primary skill match" in assignment["reason"]
    assert "30%" in assignment["reason"]


def test_inactive_employee_stays_ineligible(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    inactive = EmployeeRepository(org_a).create(
        full_name="Inactive Named",
        email="inactive-named@example.com",
        status="inactive",
        current_workload_percent=10,
        max_allocation_percent=100,
    )
    other = EmployeeRepository(org_a).create(
        full_name="Active Substitute",
        email="active-substitute@example.com",
        primary_skills=["Inactive Named"],
        current_workload_percent=10,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Inactive Named")
    assigned = {item["resource_id"] for item in body["assignments"]}
    assert str(inactive.id) not in assigned
    assert str(other.id) not in assigned
    assert any(item["conflict_status"] == "inactive" for item in body["conflicts"])


def test_zero_availability_exact_match_is_not_selected(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    unavailable = EmployeeRepository(org_a).create(
        full_name="Unavailable Named",
        email="unavailable-named@example.com",
        availability_percent=0,
        current_workload_percent=10,
        max_allocation_percent=100,
    )
    other = EmployeeRepository(org_a).create(
        full_name="Available Substitute",
        email="available-substitute@example.com",
        primary_skills=["Unavailable Named"],
        availability_percent=100,
        current_workload_percent=10,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Unavailable Named")
    assigned = {item["resource_id"] for item in body["assignments"]}
    assert str(unavailable.id) not in assigned
    assert str(other.id) not in assigned
    assert body["status"] == "needs_clarification"
    assert "Unavailable Named is unavailable and cannot be assigned." in _questions(body)


def test_employee_below_max_with_availability_stays_eligible(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Ready Person",
        email="ready-person@example.com",
        availability_percent=75,
        current_workload_percent=25,
        max_allocation_percent=80,
    )
    body = _allocate_requirement(client, org_a, auth_headers_a, "Ready Person")
    assert body["assignments"][0]["resource_id"] == str(employee.id)
    assert float(employee.availability_percent) > 0
    assert float(employee.current_workload_percent) < float(employee.max_allocation_percent)


def _queue_allocation(
    org_id: UUID,
    user_id: UUID,
    requirement: str,
    proposals: list[dict[str, str]] | None,
):
    import os

    from app.config import reset_settings_cache

    process_id, _ = _seed_process_version(org_id, _plan_with_resources(requirement))
    fake = FakeGeminiClient()
    if proposals is not None:
        fake.enqueue_structured(
            {"proposed_assignments": proposals, "reasoning_summary": "queued test proposal"}
        )
    previous = os.environ.get("GEMINI_RESOURCE_MODEL")
    os.environ["GEMINI_RESOURCE_MODEL"] = "gemini-2.0-flash-001"
    reset_settings_cache()
    try:
        service = AllocationService(org_id, client=fake)
        return service.allocate(
            process_id,
            user_id=user_id,
            correlation_id="llm-gate",
            permissions=frozenset(),
        )
    finally:
        if previous is None:
            os.environ.pop("GEMINI_RESOURCE_MODEL", None)
        else:
            os.environ["GEMINI_RESOURCE_MODEL"] = previous
        reset_settings_cache()


def _proposal(employee_id: str, requirement: str, *, display_name: str = "") -> dict[str, str]:
    payload = {
        "step_id": "step_allocate",
        "requirement": requirement,
        "resource_id": employee_id,
        "resource_type": "employee",
        "reason": "queued proposal",
    }
    if display_name:
        payload["display_name"] = display_name
    return payload


def test_queued_proposal_for_employee_at_max_is_rejected(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Maxed Python",
        email="maxed-python@example.com",
        primary_skills=["Python"],
        current_workload_percent=100,
        max_allocation_percent=100,
    )
    result = _queue_allocation(
        org_a,
        user_a_id,
        "Python",
        [_proposal(str(employee.id), "Python", display_name="Maxed Python")],
    )
    assert result.assignments == []
    assert result.status == "needs_clarification"


def test_queued_proposal_for_inactive_employee_is_rejected(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Inactive Proposal",
        email="inactive-proposal@example.com",
        status="inactive",
        primary_skills=["Python"],
    )
    result = _queue_allocation(
        org_a,
        user_a_id,
        "Inactive Proposal",
        [_proposal(str(employee.id), "Inactive Proposal")],
    )
    assert result.assignments == []
    assert result.status == "needs_clarification"


def test_queued_proposal_for_zero_availability_is_rejected(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Unavailable Proposal",
        email="unavailable-proposal@example.com",
        availability_percent=0,
        primary_skills=["Python"],
    )
    result = _queue_allocation(
        org_a,
        user_a_id,
        "Unavailable Proposal",
        [_proposal(str(employee.id), "Unavailable Proposal")],
    )
    assert result.assignments == []
    assert result.status == "needs_clarification"


def test_queued_proposal_with_unknown_employee_id_is_rejected(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    result = _queue_allocation(
        org_a,
        user_a_id,
        "Python",
        [_proposal(str(uuid4()), "Python")],
    )
    assert result.assignments == []
    assert result.status == "needs_clarification"


def test_queued_proposal_with_wrong_skill_is_rejected(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Java Only",
        email="java-only@example.com",
        primary_skills=["Java"],
    )
    result = _queue_allocation(
        org_a,
        user_a_id,
        "Python",
        [_proposal(str(employee.id), "Python")],
    )
    assert result.assignments == []
    assert result.status == "needs_clarification"


def test_queued_proposal_with_matching_skill_is_accepted(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    skilled = EmployeeRepository(org_a).create(
        full_name="Python Dev",
        email="python-dev@example.com",
        primary_skills=["Python"],
        current_workload_percent=20,
        max_allocation_percent=100,
    )
    other = EmployeeRepository(org_a).create(
        full_name="Java Dev",
        email="java-dev@example.com",
        primary_skills=["Java"],
        current_workload_percent=10,
    )
    result = _queue_allocation(
        org_a,
        user_a_id,
        "Python",
        [_proposal(str(skilled.id), "Python"), _proposal(str(other.id), "Python")],
    )
    assigned = {item.resource_id for item in result.assignments}
    assert str(skilled.id) in assigned
    assert str(other.id) not in assigned


def test_explicit_employee_at_max_is_not_replaced_by_gemini(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="John Silva",
        email="john.silva@example.com",
        current_workload_percent=80,
        max_allocation_percent=80,
    )
    jane = EmployeeRepository(org_a).create(
        full_name="Jane Perera",
        email="jane.perera@example.com",
        primary_skills=["Python"],
        current_workload_percent=20,
        max_allocation_percent=100,
    )
    requirement = "Assign John Silva to prepare the report."
    result = _queue_allocation(
        org_a,
        user_a_id,
        requirement,
        [_proposal(str(jane.id), requirement, display_name="Jane Perera")],
    )
    assert all(item.resource_id != str(jane.id) for item in result.assignments)
    assert result.assignments == []
    assert result.status == "needs_clarification"
    assert result.unresolved


def test_explicit_eligible_employee_is_not_replaced_by_gemini(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    john = EmployeeRepository(org_a).create(
        full_name="John Silva",
        email="john.silva@example.com",
        current_workload_percent=30,
        max_allocation_percent=100,
    )
    jane = EmployeeRepository(org_a).create(
        full_name="Jane Perera",
        email="jane.perera@example.com",
        current_workload_percent=10,
    )
    requirement = "Assign John Silva to prepare the report."
    result = _queue_allocation(
        org_a,
        user_a_id,
        requirement,
        [_proposal(str(jane.id), requirement, display_name="Jane Perera")],
    )
    assigned = {item.resource_id for item in result.assignments}
    assert str(john.id) in assigned
    assert str(jane.id) not in assigned


def test_proposal_outside_candidate_list_is_rejected(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    EmployeeRepository(org_a).create(full_name="Quinn Casey", email="quinn-one@example.com")
    EmployeeRepository(org_a).create(full_name="Quinn Casey", email="quinn-two@example.com")
    outsider = EmployeeRepository(org_a).create(
        full_name="Outside Candidate",
        email="outside-candidate@example.com",
        current_workload_percent=10,
    )
    result = _queue_allocation(
        org_a,
        user_a_id,
        "Quinn Casey",
        [_proposal(str(outsider.id), "Quinn Casey", display_name="Outside Candidate")],
    )
    assert all(item.resource_id != str(outsider.id) for item in result.assignments)
    assert result.status == "needs_clarification"


def test_proposal_inside_candidate_list_is_accepted(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    chosen = EmployeeRepository(org_a).create(
        full_name="Quinn Casey",
        email="quinn-chosen@example.com",
    )
    EmployeeRepository(org_a).create(full_name="Quinn Casey", email="quinn-other@example.com")
    result = _queue_allocation(
        org_a,
        user_a_id,
        "Quinn Casey",
        [_proposal(str(chosen.id), "Quinn Casey")],
    )
    assert len(result.assignments) == 1
    assert result.assignments[0].resource_id == str(chosen.id)
    assert result.assignments[0].data_source.value == "llm_interpretation"


def test_empty_fake_gemini_cannot_bypass_explicit_identity(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="John Silva",
        email="john.silva@example.com",
        current_workload_percent=90,
        max_allocation_percent=90,
    )
    silva = EmployeeRepository(org_a).create(
        full_name="Silva",
        email="silva-only@example.com",
        current_workload_percent=10,
        max_allocation_percent=100,
    )
    result = _queue_allocation(org_a, user_a_id, "John Silva", None)
    assert result.assignments == []
    assert all(item.resource_id != str(silva.id) for item in result.assignments)
    assert result.status == "needs_clarification"


def test_display_name_fallback_cannot_replace_explicit_employee(
    org_a: UUID, user_a_id: UUID, client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="John Silva",
        email="john.silva@example.com",
        current_workload_percent=80,
        max_allocation_percent=80,
    )
    jane = EmployeeRepository(org_a).create(
        full_name="Jane Perera",
        email="jane.perera@example.com",
        current_workload_percent=15,
    )
    requirement = "Assign John Silva to prepare the report."
    result = _queue_allocation(
        org_a,
        user_a_id,
        requirement,
        [_proposal(str(uuid4()), requirement, display_name="Jane Perera")],
    )
    assert all(item.resource_id != str(jane.id) for item in result.assignments)
    assert result.assignments == []
    assert result.status == "needs_clarification"


def test_email_address_is_not_classified_as_integration() -> None:
    for requirement in (
        "email-max@example.com",
        "john.email@example.com",
        "employee.email@company.com",
    ):
        assert infer_resource_type(requirement) == ResourceType.EMPLOYEE


def test_email_phrases_stay_integrations() -> None:
    for requirement in (
        "email integration",
        "send email",
        "email system",
        "company email tool",
    ):
        assert infer_resource_type(requirement) == ResourceType.INTEGRATION


def test_integration_keywords_keep_existing_classification() -> None:
    for requirement in ("form", "tool", "system", "list", "directory", "software"):
        assert infer_resource_type(requirement) == ResourceType.INTEGRATION
    # "template" is an artifact keyword first, then match() still binds an integration.
    assert infer_resource_type("template") == ResourceType.UNKNOWN


def test_template_keyword_still_maps_to_integration(org_a: UUID) -> None:
    outcome = DeterministicResourceMatcher(OrgCatalog(organization_id=org_a)).match(
        step_id="s1",
        requirement="template",
    )
    assert outcome.assigned is not None
    assert outcome.assigned.resource_type == ResourceType.INTEGRATION


def test_email_address_reaches_exact_employee_match(org_a: UUID) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Email Liaison",
        email="email-max@example.com",
        employee_code="EMAIL-42",
    )
    other = EmployeeRepository(org_a).create(
        full_name="John Email",
        email="john.email@example.com",
        employee_code="EMAIL-77",
    )
    catalog = OrgCatalog(
        organization_id=org_a,
        employees=EmployeeRepository(org_a).list_all(),
    )
    matcher = DeterministicResourceMatcher(catalog)

    for person, requirement in (
        (employee, "email-max@example.com"),
        (other, "john.email@example.com"),
    ):
        outcome = matcher.match(step_id="s1", requirement=requirement)
        assert outcome.assigned is not None
        assert outcome.assigned.resource_id == str(person.id)
        assert outcome.assigned.resource_type == ResourceType.EMPLOYEE


def test_employee_email_with_email_in_name_and_code_is_not_an_integration(
    org_a: UUID,
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Email Coordinator",
        email="employee.email@company.com",
        employee_code="EMAIL-9",
    )
    catalog = OrgCatalog(
        organization_id=org_a,
        employees=EmployeeRepository(org_a).list_all(),
    )
    outcome = DeterministicResourceMatcher(catalog).match(
        step_id="s1",
        requirement="employee.email@company.com",
    )
    assert outcome.assigned is not None
    assert outcome.assigned.resource_id == str(employee.id)
    assert outcome.assigned.resource_type == ResourceType.EMPLOYEE
