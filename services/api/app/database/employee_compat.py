"""Map hosted tenant/role rows onto the application employee model."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from app.contracts.common import utcnow
from app.database.memory import EmployeeManagerLinkRecord, EmployeeRecord


@dataclass(frozen=True)
class HostedRole:
    id: UUID
    tenant_id: UUID
    code: str


def role_code_for_tenant(
    employee_tenant_id: UUID,
    role_tenant_id: UUID | None,
    role_code: str | None,
) -> str | None:
    """Accept a role code only when it belongs to the employee's tenant."""
    if role_code is None or role_tenant_id is None:
        return None
    if role_tenant_id != employee_tenant_id:
        return None
    return role_code


def resolve_role_id(
    roles: Sequence[HostedRole],
    tenant_id: UUID,
    role_code: str | None,
) -> UUID | None:
    """Return the one same-tenant role id. Missing or foreign codes resolve to nothing."""
    if role_code is None or not role_code.strip():
        return None
    matches = [
        role.id
        for role in roles
        if role.tenant_id == tenant_id and role.code == role_code
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def employee_model_values(record: EmployeeRecord, *, role_id: UUID | None) -> dict[str, object]:
    """Columns written for an employee. employee_number is intentionally absent."""
    return {
        "id": record.id,
        "organization_id": record.organization_id,
        "employee_code": record.employee_code,
        "full_name": record.full_name,
        "email": record.email,
        "phone": record.phone,
        "department_id": record.department_id,
        "role_id": role_id,
        "manager_employee_id": record.manager_employee_id,
        "status": record.status,
        "is_manager": record.is_manager,
        "employment_type": record.employment_type,
        "reporting_level": record.reporting_level,
        "primary_skills": list(record.primary_skills),
        "secondary_skills": list(record.secondary_skills),
        "skill_level": record.skill_level,
        "availability_percent": record.availability_percent,
        "weekly_capacity_hours": record.weekly_capacity_hours,
        "baseline_workload_percent": record.baseline_workload_percent,
        "current_workload_percent": record.current_workload_percent,
        "cost_per_hour": 0 if record.cost_per_hour is None else record.cost_per_hour,
        "approval_authority_limit": record.approval_authority_limit,
        "approval_tier": record.approval_tier,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def manager_links_for_catalog(
    employees: Sequence[EmployeeRecord],
    existing_links: Sequence[EmployeeManagerLinkRecord],
    *,
    now: datetime | None = None,
) -> list[EmployeeManagerLinkRecord]:
    """Keep same-tenant manager links and add links from manager_employee_id."""
    timestamp = now or utcnow()
    by_id = {employee.id: employee for employee in employees}
    kept: list[EmployeeManagerLinkRecord] = []
    seen: set[tuple[UUID, UUID]] = set()
    for link in existing_links:
        employee = by_id.get(link.employee_id)
        manager = by_id.get(link.manager_employee_id)
        if employee is None or manager is None:
            continue
        if employee.organization_id != manager.organization_id:
            continue
        if link.organization_id != employee.organization_id:
            continue
        pair = (link.employee_id, link.manager_employee_id)
        if pair in seen:
            continue
        kept.append(link)
        seen.add(pair)
    for employee in employees:
        manager_id = employee.manager_employee_id
        if manager_id is None:
            continue
        pair = (employee.id, manager_id)
        if pair in seen:
            continue
        manager = by_id.get(manager_id)
        if manager is None or manager.organization_id != employee.organization_id:
            continue
        kept.append(
            EmployeeManagerLinkRecord(
                id=uuid5(NAMESPACE_URL, f"{employee.id}:{manager_id}"),
                organization_id=employee.organization_id,
                employee_id=employee.id,
                manager_employee_id=manager_id,
                link_type="direct",
                status="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        seen.add(pair)
    return kept
