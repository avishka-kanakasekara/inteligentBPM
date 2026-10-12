"""Hosted employee schema compatibility: tenant, code, role, and manager links."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.database.employee_compat import (
    HostedRole,
    employee_model_values,
    manager_links_for_catalog,
    resolve_role_id,
    role_code_for_tenant,
)
from app.database.memory import EmployeeRecord, get_memory_store, reset_memory_store
from app.database.models import EmployeeModel
from app.database.postgres_persistence import _employee_from_row
from app.repositories.memory_repos import EmployeeRepository


def _employee(
    organization_id: UUID,
    *,
    employee_code: str = "E-001",
    manager_employee_id: UUID | None = None,
    is_manager: bool = False,
) -> EmployeeRecord:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    return EmployeeRecord(
        id=uuid4(),
        organization_id=organization_id,
        full_name="Alex Owner",
        email="alex@example.com",
        title=None,
        department_id=None,
        is_manager=is_manager,
        status="active",
        created_at=now,
        updated_at=now,
        employee_code=employee_code,
        manager_employee_id=manager_employee_id,
    )


def _hosted_row(
    tenant_id: UUID,
    *,
    employee_code: str = "E-001",
    manager_employee_id: UUID | None = None,
    approval_authority_limit: float | None = 0,
) -> EmployeeModel:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    return EmployeeModel(
        id=uuid4(),
        organization_id=tenant_id,
        employee_code=employee_code,
        full_name="Alex Owner",
        email="alex@example.com",
        phone=None,
        department_id=None,
        role_id=uuid4(),
        manager_employee_id=manager_employee_id,
        status="active",
        is_manager=False,
        employment_type="full_time",
        reporting_level=1,
        primary_skills=["Python"],
        secondary_skills=[],
        skill_level="intermediate",
        availability_percent=100,
        weekly_capacity_hours=40,
        baseline_workload_percent=0,
        current_workload_percent=0,
        cost_per_hour=0,
        max_allocation_percent=100,
        approval_authority_limit=approval_authority_limit,
        approval_tier="none",
        created_at=now,
        updated_at=now,
    )


def test_tenant_id_hydrates_as_organization_id() -> None:
    tenant_id = uuid4()
    record = _employee_from_row(_hosted_row(tenant_id))
    assert record.organization_id == tenant_id
    assert EmployeeModel.organization_id.property.columns[0].name == "tenant_id"


def test_employee_code_hydrates_from_employee_code_column() -> None:
    record = _employee_from_row(_hosted_row(uuid4(), employee_code="EMP-0042"))
    assert record.employee_code == "EMP-0042"
    assert "employee_number" not in EmployeeModel.__table__.columns


def test_role_code_hydrates_only_for_the_same_tenant() -> None:
    tenant_id = uuid4()
    record = _employee_from_row(
        _hosted_row(tenant_id),
        role_code=role_code_for_tenant(tenant_id, tenant_id, "finance"),
    )
    assert record.role_code == "finance"


def test_role_lookup_is_tenant_scoped() -> None:
    tenant_id = uuid4()
    role_id = uuid4()
    resolved = resolve_role_id(
        [HostedRole(id=role_id, tenant_id=tenant_id, code="buyer")],
        tenant_id,
        "buyer",
    )
    assert resolved == role_id


def test_cross_tenant_role_cannot_be_selected() -> None:
    tenant_id = uuid4()
    other_tenant = uuid4()
    foreign_role = uuid4()
    assert role_code_for_tenant(tenant_id, other_tenant, "buyer") is None
    assert (
        resolve_role_id(
            [HostedRole(id=foreign_role, tenant_id=other_tenant, code="buyer")],
            tenant_id,
            "buyer",
        )
        is None
    )
    assert resolve_role_id([], tenant_id, None) is None


def test_persistence_values_write_tenant_and_leave_employee_number_untouched() -> None:
    tenant_id = uuid4()
    record = _employee(tenant_id, employee_code="E-010")
    values = employee_model_values(record, role_id=None)
    assert values["organization_id"] == tenant_id
    assert values["employee_code"] == "E-010"
    assert "employee_number" not in values
    assert "role_code" not in values
    assert "organization_id" not in EmployeeModel.__table__.columns


def test_role_code_resolves_to_role_id_in_the_same_tenant() -> None:
    tenant_id = uuid4()
    other_tenant = uuid4()
    same = HostedRole(id=uuid4(), tenant_id=tenant_id, code="manager")
    other = HostedRole(id=uuid4(), tenant_id=other_tenant, code="manager")
    assert resolve_role_id([other, same], tenant_id, "manager") == same.id


def test_manager_links_stay_inside_one_tenant() -> None:
    tenant_id = uuid4()
    other_tenant = uuid4()
    manager = _employee(tenant_id, employee_code="E-001", is_manager=True)
    report = _employee(tenant_id, employee_code="E-002", manager_employee_id=manager.id)
    outsider = _employee(other_tenant, employee_code="E-003", manager_employee_id=manager.id)
    links = manager_links_for_catalog([manager, report, outsider], [])
    pairs = {(link.employee_id, link.manager_employee_id) for link in links}
    assert (report.id, manager.id) in pairs
    assert (outsider.id, manager.id) not in pairs
    assert all(link.organization_id == tenant_id for link in links)
    assert report.is_manager is False


def test_migration_creates_max_allocation_before_its_check() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/20261009120000_hosted_employee_compatibility.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    add_at = sql.index("add column if not exists max_allocation_percent numeric(5, 2)")
    check_at = sql.index("employees_max_allocation_percent_check")
    assert add_at < check_at
    assert EmployeeModel.max_allocation_percent.property.columns[0].name == (
        "max_allocation_percent"
    )
    assert "approval_authority_limit numeric(12, 2) not null" not in sql


def test_missing_approval_limit_stays_unset() -> None:
    row = _hosted_row(uuid4(), approval_authority_limit=None)
    hydrated = _employee_from_row(row)
    assert hydrated.approval_authority_limit is None
    assert employee_model_values(hydrated, role_id=None)["approval_authority_limit"] is None


def test_repository_hides_employees_from_another_tenant() -> None:
    reset_memory_store()
    tenant_id = uuid4()
    other_tenant = uuid4()
    local = _employee(tenant_id, employee_code="E-001")
    foreign = _employee(other_tenant, employee_code="E-009")
    store = get_memory_store()
    store.employees[local.id] = local
    store.employees[foreign.id] = foreign
    visible = EmployeeRepository(tenant_id).list_all()
    assert [employee.id for employee in visible] == [local.id]
