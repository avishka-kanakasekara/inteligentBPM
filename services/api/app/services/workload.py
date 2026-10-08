"""Recompute employee workload from the latest allocation snapshots.

current_workload_percent is derived. It is never incremented.

current_workload_percent = min(
    100,
    max_allocation_percent,
    baseline_workload_percent + active_process_count * 10,
)

The active-process count is unchanged. Only the stored workload is capped.
"""

from __future__ import annotations

from uuid import UUID

from app.database.memory import (
    AllocationResultRecord,
    ProcessRunRecord,
    get_memory_store,
)
from app.domain.enums import ProcessRunStatus

WORKLOAD_UNIT_PERCENT = 10.0
EMPLOYEE_RESOURCE_TYPES = frozenset({"employee", "manager", "approval_authority"})
TERMINAL_PROCESS_STATUSES = frozenset({"completed", "cancelled"})
TERMINAL_RUN_STATUSES = frozenset(
    {
        ProcessRunStatus.COMPLETED.value,
        ProcessRunStatus.CANCELLED.value,
        ProcessRunStatus.FAILED.value,
    }
)


def recompute_organization_workload(organization_id: UUID) -> None:
    """Recalculate current_workload_percent for every employee in one organization."""
    WorkloadService().recompute(organization_id)


class WorkloadService:
    def recompute(self, organization_id: UUID) -> None:
        store = get_memory_store()
        with store.lock:
            counts = self._active_process_counts(organization_id)
            for employee in list(store.employees.values()):
                if employee.organization_id != organization_id:
                    continue
                active_processes = counts.get(employee.id, 0)
                calculated = min(
                    100.0,
                    float(employee.max_allocation_percent),
                    float(employee.baseline_workload_percent)
                    + active_processes * WORKLOAD_UNIT_PERCENT,
                )
                if float(employee.current_workload_percent) == calculated:
                    continue
                employee.current_workload_percent = calculated
                store.employees[employee.id] = employee

    def _active_process_counts(self, organization_id: UUID) -> dict[UUID, int]:
        store = get_memory_store()
        latest_allocations: dict[UUID, AllocationResultRecord] = {}
        for record in store.allocations.values():
            if record.organization_id != organization_id:
                continue
            current = latest_allocations.get(record.process_id)
            if current is None or (record.updated_at, record.created_at) >= (
                current.updated_at,
                current.created_at,
            ):
                latest_allocations[record.process_id] = record

        latest_runs: dict[UUID, ProcessRunRecord] = {}
        for run in store.process_runs.values():
            if run.organization_id != organization_id:
                continue
            current = latest_runs.get(run.process_id)
            if current is None or (run.updated_at, run.created_at) >= (
                current.updated_at,
                current.created_at,
            ):
                latest_runs[run.process_id] = run

        counts: dict[UUID, int] = {}
        for process_id, allocation in latest_allocations.items():
            if str(allocation.status) != "resolved":
                continue
            process = store.processes.get(process_id)
            if process is None or process.organization_id != organization_id:
                continue
            if process.status in TERMINAL_PROCESS_STATUSES:
                continue
            run = latest_runs.get(process_id)
            if run is not None and _status_value(run.status) in TERMINAL_RUN_STATUSES:
                continue
            employee_ids = _employee_ids(allocation.result_snapshot)
            for employee_id in employee_ids:
                employee = store.employees.get(employee_id)
                if employee is None or employee.organization_id != organization_id:
                    continue
                counts[employee_id] = counts.get(employee_id, 0) + 1
        return counts


def _status_value(status: object) -> str:
    return str(getattr(status, "value", status))


def _employee_ids(snapshot: dict[str, object]) -> set[UUID]:
    found: set[UUID] = set()
    assignments = snapshot.get("assignments") if isinstance(snapshot, dict) else None
    if not isinstance(assignments, list):
        return found
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        resource_type = str(assignment.get("resource_type") or "")
        if resource_type not in EMPLOYEE_RESOURCE_TYPES:
            continue
        raw_id = assignment.get("resource_id")
        try:
            found.add(UUID(str(raw_id)))
        except (TypeError, ValueError):
            continue
    return found
