"""Workload Rule V1: baseline plus one unit per active process."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.agents.discovery.models import ActionType, ProcessPlan, ProcessStep, RiskLevel
from app.database.memory import AllocationResultRecord, get_memory_store
from app.domain.enums import ProcessRunStatus
from app.repositories.memory_repos import (
    EmployeeRepository,
    ProcessRepository,
    ProcessRunRepository,
)
from app.services.workload import WorkloadService, recompute_organization_workload


def _employee(
    org_id: UUID,
    name: str,
    email: str,
    baseline: float,
    *,
    max_allocation: float = 100,
):
    return EmployeeRepository(org_id).create(
        full_name=name,
        email=email,
        baseline_workload_percent=baseline,
        current_workload_percent=baseline,
        max_allocation_percent=max_allocation,
        status="active",
    )


def _process(org_id: UUID, name: str):
    return ProcessRepository(org_id).create(
        name=name,
        description="workload test",
        created_by_user_id=None,
    )


def _assignment(employee_id: UUID, *, resource_type: str = "employee", requirement: str = "Python"):
    return {
        "step_id": "step_allocate",
        "requirement": requirement,
        "resource_id": str(employee_id),
        "resource_type": resource_type,
        "reason": "test",
        "data_source": "directory_query",
        "confidence": 1,
        "authorization_status": "authorized",
        "active_status": True,
        "display_name": "Person",
    }


def _snapshot(
    org_id: UUID,
    process_id: UUID,
    *,
    status: str,
    assignments: list[dict],
    when: datetime,
) -> None:
    record = AllocationResultRecord(
        id=uuid4(),
        organization_id=org_id,
        process_id=process_id,
        process_version_id=uuid4(),
        status=status,
        result_snapshot={"status": status, "assignments": assignments},
        created_at=when,
        updated_at=when,
    )
    get_memory_store().allocations[record.id] = record


def _plan(requirement: str) -> dict:
    plan = ProcessPlan(
        goal="Allocate resources",
        steps=[
            ProcessStep(
                step_id="step_allocate",
                action_type=ActionType.HUMAN_TASK,
                title="Allocate",
                description="Bind resources",
                required_resources=[requirement],
                approval_requirements=[],
                success_criteria=["Resources bound"],
                risk_level=RiskLevel.MEDIUM,
            )
        ],
        reasoning_summary="Workload test plan",
    )
    return plan.model_dump(mode="json")


def test_baseline_plus_one_process_is_forty_and_baseline_stays(org_a: UUID) -> None:
    employee = _employee(org_a, "Worker One", "one@example.com", 30)
    process = _process(org_a, "Process A")
    _snapshot(
        org_a,
        process.id,
        status="resolved",
        assignments=[_assignment(employee.id)],
        when=datetime.now(UTC),
    )
    recompute_organization_workload(org_a)
    stored = EmployeeRepository(org_a).get(employee.id)
    assert stored.baseline_workload_percent == 30
    assert stored.current_workload_percent == 40


def test_two_processes_add_twenty(org_a: UUID) -> None:
    employee = _employee(org_a, "Worker Two", "two@example.com", 30)
    first = _process(org_a, "Process A")
    second = _process(org_a, "Process B")
    now = datetime.now(UTC)
    _snapshot(org_a, first.id, status="resolved", assignments=[_assignment(employee.id)], when=now)
    _snapshot(
        org_a,
        second.id,
        status="resolved",
        assignments=[_assignment(employee.id, requirement="Java")],
        when=now,
    )
    recompute_organization_workload(org_a)
    stored = EmployeeRepository(org_a).get(employee.id)
    assert stored.current_workload_percent == 50
    assert stored.baseline_workload_percent == 30


def test_two_requirements_in_one_process_count_once(org_a: UUID) -> None:
    employee = _employee(org_a, "Worker Once", "once@example.com", 30)
    process = _process(org_a, "One process")
    _snapshot(
        org_a,
        process.id,
        status="resolved",
        assignments=[
            _assignment(employee.id, requirement="Python"),
            _assignment(employee.id, requirement="Review"),
        ],
        when=datetime.now(UTC),
    )
    recompute_organization_workload(org_a)
    assert EmployeeRepository(org_a).get(employee.id).current_workload_percent == 40


def test_rerun_allocation_does_not_add_another_unit(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
) -> None:
    employee = _employee(org_a, "Stable Worker", "stable@example.com", 30)
    created = client.post(
        "/v1/processes",
        headers=auth_headers_a,
        json={"name": "Stable", "description": "Stable"},
    )
    process_id = created.json()["id"]
    client.post(
        f"/v1/processes/{process_id}/versions",
        headers=auth_headers_a,
        json={"plan_snapshot": _plan("Stable Worker")},
    )
    first = client.post(f"/v1/processes/{process_id}/allocate", headers=auth_headers_a, json={})
    second = client.post(f"/v1/processes/{process_id}/allocate", headers=auth_headers_a, json={})
    assert first.status_code == 200
    assert second.status_code == 200
    stored = EmployeeRepository(org_a).get(employee.id)
    assert stored.baseline_workload_percent == 30
    assert stored.current_workload_percent == 40


def test_reallocation_moves_the_workload_unit(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
) -> None:
    first_employee = _employee(org_a, "Employee B", "bee@example.com", 30)
    second_employee = _employee(org_a, "Employee C", "cee@example.com", 30)
    created = client.post(
        "/v1/processes",
        headers=auth_headers_a,
        json={"name": "Move", "description": "Move"},
    )
    process_id = created.json()["id"]
    client.post(
        f"/v1/processes/{process_id}/versions",
        headers=auth_headers_a,
        json={"plan_snapshot": _plan("Employee B")},
    )
    client.post(f"/v1/processes/{process_id}/allocate", headers=auth_headers_a, json={})
    client.post(
        f"/v1/processes/{process_id}/versions",
        headers=auth_headers_a,
        json={"plan_snapshot": _plan("Employee C")},
    )
    moved = client.post(f"/v1/processes/{process_id}/allocate", headers=auth_headers_a, json={})
    assert moved.status_code == 200
    assert EmployeeRepository(org_a).get(first_employee.id).current_workload_percent == 30
    assert EmployeeRepository(org_a).get(second_employee.id).current_workload_percent == 40


def test_unresolved_and_non_employee_allocations_add_nothing(org_a: UUID) -> None:
    employee = _employee(org_a, "Untouched", "untouched@example.com", 30)
    now = datetime.now(UTC)
    for status in ("needs_clarification", "blocked"):
        process = _process(org_a, status)
        _snapshot(
            org_a,
            process.id,
            status=status,
            assignments=[_assignment(employee.id)],
            when=now,
        )
    supplier_process = _process(org_a, "supplier")
    _snapshot(
        org_a,
        supplier_process.id,
        status="resolved",
        assignments=[_assignment(uuid4(), resource_type="supplier")],
        when=now,
    )
    recompute_organization_workload(org_a)
    assert EmployeeRepository(org_a).get(employee.id).current_workload_percent == 30


def test_completed_process_and_terminal_runs_add_nothing(org_a: UUID) -> None:
    employee = _employee(org_a, "Finisher", "finisher@example.com", 30)
    completed = _process(org_a, "Done")
    cancelled = _process(org_a, "Stopped")
    failed = _process(org_a, "Failed run")
    now = datetime.now(UTC)
    for process in (completed, cancelled, failed):
        _snapshot(
            org_a,
            process.id,
            status="resolved",
            assignments=[_assignment(employee.id)],
            when=now,
        )
    recompute_organization_workload(org_a)
    assert EmployeeRepository(org_a).get(employee.id).current_workload_percent == 60

    ProcessRepository(org_a).set_status(completed.id, "completed")
    assert EmployeeRepository(org_a).get(employee.id).current_workload_percent == 50

    ProcessRepository(org_a).set_status(cancelled.id, "cancelled")
    assert EmployeeRepository(org_a).get(employee.id).current_workload_percent == 40

    run = ProcessRunRepository(org_a).create(
        process_id=failed.id,
        process_version_id=None,
        initiated_by_user_id=None,
        correlation_id="workload-failed",
    )
    ProcessRunRepository(org_a).set_status(run.id, ProcessRunStatus.FAILED)
    assert EmployeeRepository(org_a).get(employee.id).current_workload_percent == 30


def test_workload_clamps_at_one_hundred(org_a: UUID) -> None:
    employee = _employee(org_a, "Busy", "busy@example.com", 95)
    process = _process(org_a, "Extra")
    _snapshot(
        org_a,
        process.id,
        status="resolved",
        assignments=[_assignment(employee.id)],
        when=datetime.now(UTC),
    )
    recompute_organization_workload(org_a)
    stored = EmployeeRepository(org_a).get(employee.id)
    assert stored.current_workload_percent == 100
    assert stored.baseline_workload_percent == 95


def test_patch_cannot_overwrite_calculated_workload(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
) -> None:
    created = client.post(
        "/v1/employees",
        headers=auth_headers_a,
        json={
            "full_name": "Patched",
            "email": "patched@example.com",
            "baseline_workload_percent": 30,
        },
    )
    employee_id = created.json()["id"]
    process = _process(org_a, "Live")
    _snapshot(
        org_a,
        process.id,
        status="resolved",
        assignments=[_assignment(UUID(employee_id))],
        when=datetime.now(UTC),
    )
    recompute_organization_workload(org_a)

    patched = client.patch(
        f"/v1/employees/{employee_id}",
        headers=auth_headers_a,
        json={"current_workload_percent": 40, "phone": "555-0100"},
    )
    assert patched.status_code == 200
    assert patched.json()["baseline_workload_percent"] == 30
    assert patched.json()["current_workload_percent"] == 40

    second = _process(org_a, "Second live")
    _snapshot(
        org_a,
        second.id,
        status="resolved",
        assignments=[_assignment(UUID(employee_id), requirement="Java")],
        when=datetime.now(UTC),
    )
    recompute_organization_workload(org_a)
    stored = EmployeeRepository(org_a).get(UUID(employee_id))
    assert stored.baseline_workload_percent == 30
    assert stored.current_workload_percent == 50


def test_baseline_change_keeps_active_process_contribution(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
) -> None:
    employee = _employee(org_a, "Adjust", "adjust@example.com", 30)
    process = _process(org_a, "Still active")
    _snapshot(
        org_a,
        process.id,
        status="resolved",
        assignments=[_assignment(employee.id)],
        when=datetime.now(UTC),
    )
    recompute_organization_workload(org_a)
    updated = client.patch(
        f"/v1/employees/{employee.id}",
        headers=auth_headers_a,
        json={"baseline_workload_percent": 20},
    )
    assert updated.status_code == 200
    assert updated.json()["baseline_workload_percent"] == 20
    assert updated.json()["current_workload_percent"] == 30


def test_repeated_recomputation_does_not_double_count(org_a: UUID) -> None:
    employee = _employee(org_a, "Repeat", "repeat@example.com", 30)
    process = _process(org_a, "Only one")
    now = datetime.now(UTC)
    _snapshot(
        org_a,
        process.id,
        status="resolved",
        assignments=[_assignment(employee.id)],
        when=now - timedelta(minutes=5),
    )
    _snapshot(
        org_a,
        process.id,
        status="resolved",
        assignments=[_assignment(employee.id)],
        when=now,
    )

    def _run() -> None:
        recompute_organization_workload(org_a)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: _run(), range(16)))
    for _ in range(5):
        recompute_organization_workload(org_a)
    stored = EmployeeRepository(org_a).get(employee.id)
    assert stored.baseline_workload_percent == 30
    assert stored.current_workload_percent == 40


def test_complete_endpoint_removes_process_contribution(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
) -> None:
    employee = _employee(org_a, "Closer", "closer@example.com", 30)
    created = client.post(
        "/v1/processes",
        headers=auth_headers_a,
        json={"name": "To complete", "description": "Done soon"},
    )
    process_id = UUID(created.json()["id"])
    version = ProcessRepository(org_a).create_version(
        process_id,
        plan_snapshot=_plan("Closer"),
    )
    _snapshot(
        org_a,
        process_id,
        status="resolved",
        assignments=[_assignment(employee.id)],
        when=datetime.now(UTC),
    )
    recompute_organization_workload(org_a)
    assert EmployeeRepository(org_a).get(employee.id).current_workload_percent == 40
    completed = client.post(f"/v1/processes/{process_id}/complete", headers=auth_headers_a)
    assert completed.status_code == 200
    assert version.id
    assert EmployeeRepository(org_a).get(employee.id).current_workload_percent == 30


def _with_active_processes(org_id: UUID, employee_id: UUID, count: int, label: str):
    now = datetime.now(UTC)
    for index in range(count):
        process = _process(org_id, f"{label} {index}")
        _snapshot(
            org_id,
            process.id,
            status="resolved",
            assignments=[_assignment(employee_id, requirement=f"{label}-{index}")],
            when=now + timedelta(seconds=index),
        )
    recompute_organization_workload(org_id)
    return WorkloadService()._active_process_counts(org_id).get(employee_id, 0)


def test_baseline_below_max_with_no_processes_stays_at_baseline(org_a: UUID) -> None:
    employee = _employee(org_a, "Ceiling Idle", "idle-ceiling@example.com", 70, max_allocation=80)
    recompute_organization_workload(org_a)
    stored = EmployeeRepository(org_a).get(employee.id)
    assert stored.current_workload_percent == 70
    assert stored.baseline_workload_percent == 70


def test_one_process_reaches_max_allocation(org_a: UUID) -> None:
    employee = _employee(org_a, "Ceiling One", "one-ceiling@example.com", 70, max_allocation=80)
    counted = _with_active_processes(org_a, employee.id, 1, "ceiling-one")
    stored = EmployeeRepository(org_a).get(employee.id)
    assert counted == 1
    assert stored.current_workload_percent == 80


def test_extra_processes_do_not_raise_current_above_max(org_a: UUID) -> None:
    employee = _employee(org_a, "Ceiling Two", "two-ceiling@example.com", 70, max_allocation=80)
    counted = _with_active_processes(org_a, employee.id, 2, "ceiling-two")
    stored = EmployeeRepository(org_a).get(employee.id)
    assert counted == 2
    assert stored.baseline_workload_percent == 70
    assert stored.current_workload_percent == 80


def test_process_at_existing_max_keeps_current_at_max(org_a: UUID) -> None:
    employee = _employee(org_a, "Already Max", "already-max@example.com", 90, max_allocation=90)
    counted = _with_active_processes(org_a, employee.id, 1, "already-max")
    stored = EmployeeRepository(org_a).get(employee.id)
    assert counted == 1
    assert stored.current_workload_percent == 90


def test_seven_processes_clamp_at_one_hundred(org_a: UUID) -> None:
    employee = _employee(org_a, "Full Load", "full-load@example.com", 30, max_allocation=100)
    counted = _with_active_processes(org_a, employee.id, 7, "full-load")
    stored = EmployeeRepository(org_a).get(employee.id)
    assert counted == 7
    assert stored.current_workload_percent == 100


def test_seven_processes_clamp_at_lower_max_allocation(org_a: UUID) -> None:
    employee = _employee(org_a, "Capped Load", "capped-load@example.com", 30, max_allocation=80)
    counted = _with_active_processes(org_a, employee.id, 7, "capped-load")
    stored = EmployeeRepository(org_a).get(employee.id)
    assert counted == 7
    assert stored.current_workload_percent == 80


def test_agent2_does_not_assign_employee_already_at_max(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="At Max",
        email="at-max@example.com",
        primary_skills=["Python"],
        baseline_workload_percent=80,
        current_workload_percent=80,
        max_allocation_percent=80,
    )
    created = client.post(
        "/v1/processes",
        headers=auth_headers_a,
        json={"name": "No more load", "description": "At ceiling"},
    )
    process_id = created.json()["id"]
    client.post(
        f"/v1/processes/{process_id}/versions",
        headers=auth_headers_a,
        json={"plan_snapshot": _plan("Python")},
    )
    allocated = client.post(f"/v1/processes/{process_id}/allocate", headers=auth_headers_a, json={})
    assert allocated.status_code == 200, allocated.text
    assigned_ids = {item["resource_id"] for item in allocated.json()["assignments"]}
    assert str(employee.id) not in assigned_ids
    stored = EmployeeRepository(org_a).get(employee.id)
    assert stored.current_workload_percent == 80
    assert stored.max_allocation_percent == 80


def test_agent2_still_assigns_employee_below_max(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a: UUID,
) -> None:
    employee = EmployeeRepository(org_a).create(
        full_name="Under Max",
        email="under-max@example.com",
        primary_skills=["Python"],
        baseline_workload_percent=30,
        current_workload_percent=30,
        max_allocation_percent=80,
    )
    created = client.post(
        "/v1/processes",
        headers=auth_headers_a,
        json={"name": "Room left", "description": "Below ceiling"},
    )
    process_id = created.json()["id"]
    client.post(
        f"/v1/processes/{process_id}/versions",
        headers=auth_headers_a,
        json={"plan_snapshot": _plan("Python")},
    )
    allocated = client.post(f"/v1/processes/{process_id}/allocate", headers=auth_headers_a, json={})
    assert allocated.status_code == 200, allocated.text
    assert allocated.json()["assignments"][0]["resource_id"] == str(employee.id)
    stored = EmployeeRepository(org_a).get(employee.id)
    assert stored.current_workload_percent == 40
    assert stored.current_workload_percent < stored.max_allocation_percent
