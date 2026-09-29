"""Workforce profile fields shared by employee create/update validation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.security.errors import ValidationAppError

EMPLOYMENT_TYPES = frozenset({"full_time", "part_time", "contract"})
SKILL_LEVELS = frozenset({"beginner", "intermediate", "expert"})
APPROVAL_TIERS = frozenset({"none", "team", "department", "business_unit", "executive"})
PERCENT_FIELDS = (
    "availability_percent",
    "current_workload_percent",
    "max_allocation_percent",
    "sla_compliance_percent",
    "performance_score",
)
NON_NEGATIVE_FIELDS = (
    "years_of_experience",
    "weekly_capacity_hours",
    "cost_per_hour",
    "monthly_cost",
    "approval_authority_limit",
    "tasks_completed",
    "avg_task_completion_hours",
)
LIST_FIELDS = ("primary_skills", "secondary_skills", "certifications")
CLEARABLE_FIELDS = frozenset(
    {
        "title",
        "phone",
        "department_id",
        "manager_employee_id",
        "team",
        "business_unit",
        "location",
        "role_code",
        "join_date",
        "years_of_experience",
        "cost_per_hour",
        "monthly_cost",
        "approval_authority_limit",
        "tasks_completed",
        "avg_task_completion_hours",
        "sla_compliance_percent",
        "performance_score",
    }
)
MUTABLE_FIELDS = frozenset(
    {
        "full_name",
        "email",
        "title",
        "department_id",
        "is_manager",
        "status",
        "employee_code",
        "role_code",
        "approval_authority_limit",
        "approval_authority_currency",
        "phone",
        "employment_type",
        "join_date",
        "manager_employee_id",
        "team",
        "business_unit",
        "location",
        "reporting_level",
        "primary_skills",
        "secondary_skills",
        "certifications",
        "years_of_experience",
        "skill_level",
        "availability_percent",
        "weekly_capacity_hours",
        "current_workload_percent",
        "cost_per_hour",
        "monthly_cost",
        "max_allocation_percent",
        "approval_tier",
        "can_approve_procurement",
        "can_approve_budget",
        "delegation_authority",
        "tasks_completed",
        "avg_task_completion_hours",
        "sla_compliance_percent",
        "performance_score",
    }
)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def validate_employee_profile(fields: dict[str, Any], *, employee_id: UUID | None = None) -> None:
    """Reject values that would break allocation, approval routing, or planning."""
    employment_type = fields.get("employment_type")
    if employment_type is not None and employment_type not in EMPLOYMENT_TYPES:
        raise ValidationAppError(
            "employment_type must be full_time, part_time, or contract",
            details={"employment_type": employment_type},
        )

    skill_level = fields.get("skill_level")
    if skill_level is not None and skill_level not in SKILL_LEVELS:
        raise ValidationAppError(
            "skill_level must be beginner, intermediate, or expert",
            details={"skill_level": skill_level},
        )

    approval_tier = fields.get("approval_tier")
    if approval_tier is not None and approval_tier not in APPROVAL_TIERS:
        raise ValidationAppError(
            "approval_tier is not recognized",
            details={"approval_tier": approval_tier},
        )

    status = fields.get("status")
    if status is not None and status not in {"active", "inactive", "terminated"}:
        raise ValidationAppError("status must be active, inactive, or terminated")

    for key in PERCENT_FIELDS:
        if key not in fields or fields[key] is None:
            continue
        number = _as_float(fields[key])
        if number is None or number < 0 or number > 100:
            raise ValidationAppError(
                f"{key} must be between 0 and 100",
                details={key: fields[key]},
            )

    for key in NON_NEGATIVE_FIELDS:
        if key not in fields or fields[key] is None:
            continue
        number = _as_float(fields[key])
        if number is None or number < 0:
            raise ValidationAppError(f"{key} cannot be negative", details={key: fields[key]})

    weekly = fields.get("weekly_capacity_hours")
    if weekly is not None and _as_float(weekly) is not None and float(weekly) > 168:
        raise ValidationAppError("weekly_capacity_hours cannot exceed 168")

    level = fields.get("reporting_level")
    if level is not None and int(level) < 1:
        raise ValidationAppError("reporting_level must be at least 1")

    manager_id = fields.get("manager_employee_id")
    if manager_id is not None and employee_id is not None and manager_id == employee_id:
        raise ValidationAppError("Employee cannot report to themselves")

    workload = fields.get("current_workload_percent")
    maximum = fields.get("max_allocation_percent")
    if (
        workload is not None
        and maximum is not None
        and float(workload) > float(maximum)
    ):
        raise ValidationAppError(
            "current_workload_percent cannot exceed max_allocation_percent",
            details={
                "current_workload_percent": workload,
                "max_allocation_percent": maximum,
            },
        )

    for key in LIST_FIELDS:
        if key not in fields or fields[key] is None:
            continue
        items = fields[key]
        if not isinstance(items, list) or any(not str(item).strip() for item in items):
            raise ValidationAppError(f"{key} must be a list of skill or certification names")
        if len(items) > 30:
            raise ValidationAppError(f"{key} accepts at most 30 entries")
