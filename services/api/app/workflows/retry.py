"""Retry policies and dead-letter behavior for workflow activities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from app.contracts.common import utcnow
from app.database.memory import get_memory_store


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_interval_seconds: float = 0.01
    backoff_coefficient: float = 2.0
    max_interval_seconds: float = 30.0
    non_retryable_error_types: tuple[str, ...] = (
        "ValidationAppError",
        "ConflictError",
        "CancellationError",
        "ApprovalRejected",
        "ApprovalExpired",
        "PlanMutated",
    )

    def next_delay(self, attempt: int) -> float:
        """attempt is 1-based after a failure."""
        delay = self.initial_interval_seconds * (self.backoff_coefficient ** max(0, attempt - 1))
        return min(delay, self.max_interval_seconds)

    def is_retryable(self, error_type: str | None) -> bool:
        if error_type and error_type in self.non_retryable_error_types:
            return False
        return True


DEFAULT_ACTIVITY_RETRY = RetryPolicy()
INTEGRATION_RETRY = RetryPolicy(max_attempts=5, initial_interval_seconds=0.02)
CRITICAL_RETRY = RetryPolicy(max_attempts=2, initial_interval_seconds=0.01)


def publish_dead_letter(
    *,
    workflow_id: UUID,
    organization_id: UUID,
    activity_name: str,
    attempt: int,
    error: str,
    payload: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> UUID:
    store = get_memory_store()
    dlq_id = uuid4()
    store.workflow_dead_letters[dlq_id] = {
        "id": str(dlq_id),
        "workflow_id": str(workflow_id),
        "organization_id": str(organization_id),
        "activity_name": activity_name,
        "attempt": attempt,
        "error": error,
        "payload": payload or {},
        "trace_id": trace_id,
        "created_at": utcnow().isoformat(),
        "status": "open",
    }
    return dlq_id
