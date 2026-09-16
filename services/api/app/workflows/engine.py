"""Mock durable workflow engine — Temporal-equivalent semantics without local containers."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.contracts.common import utcnow
from app.database.memory import get_memory_store
from app.domain.enums import ApprovalStatus, ProcessRunStatus
from app.repositories.memory_repos import ProcessRunRepository
from app.workflows.activities import ActivityError, ActivityRunner, DefaultActivityRunner
from app.workflows.models import (
    PROCESS_FLOW,
    WaitReason,
    WorkflowInstance,
    WorkflowSignal,
    WorkflowStatus,
)
from app.workflows.outbox import DuplicateEventError, InboxService, OutboxService
from app.workflows.process_workflow import BPMProcessWorkflow
from app.workflows.retry import DEFAULT_ACTIVITY_RETRY, RetryPolicy, publish_dead_letter
from app.workflows.versioning import WORKFLOW_DEFINITION_VERSION, migrate_workflow_state


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class MockDurableWorkflowEngine:
    """
    In-process durable orchestration engine.

    Persists checkpoints to the memory store so worker restarts can recover.
    Compatible API surface with Temporal Cloud client (start / signal / query).
    """

    def __init__(
        self,
        *,
        activities: ActivityRunner | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: bool = False,
    ) -> None:
        self.workflow = BPMProcessWorkflow(activities or DefaultActivityRunner())
        self.retry_policy = retry_policy or DEFAULT_ACTIVITY_RETRY
        self.outbox = OutboxService()
        self.inbox = InboxService()
        self.sleep = sleep

    def _persist(self, instance: WorkflowInstance) -> None:
        store = get_memory_store()
        store.workflow_instances[instance.id] = instance.to_checkpoint()
        store.workflow_trace_index[instance.trace_id] = instance.id

    def _load(self, workflow_id: UUID) -> WorkflowInstance:
        store = get_memory_store()
        raw = store.workflow_instances.get(workflow_id)
        if not raw:
            raise KeyError(f"Workflow {workflow_id} not found")
        migrated = migrate_workflow_state(raw)
        return WorkflowInstance.from_checkpoint(migrated)

    def start(
        self,
        *,
        organization_id: UUID,
        process_id: UUID,
        process_run_id: UUID,
        process_version_id: UUID | None = None,
        initiated_by_user_id: UUID | None = None,
        trace_id: str | None = None,
        context: dict[str, Any] | None = None,
        timeout_seconds: int | None = 86_400,
    ) -> WorkflowInstance:
        workflow_id = uuid4()
        tid = trace_id or f"wf-{workflow_id}"
        now = utcnow()
        instance = WorkflowInstance(
            id=workflow_id,
            organization_id=organization_id,
            process_id=process_id,
            process_run_id=process_run_id,
            process_version_id=process_version_id,
            workflow_version=WORKFLOW_DEFINITION_VERSION,
            status=WorkflowStatus.RUNNING,
            trace_id=tid,
            step_index=0,
            wait_reason=None,
            context=dict(context or {}),
            initiated_by_user_id=initiated_by_user_id,
            timeout_at=(now + timedelta(seconds=timeout_seconds)).isoformat()
            if timeout_seconds
            else None,
        )
        instance.append_history("workflow.started", workflow_version=WORKFLOW_DEFINITION_VERSION)
        self._persist(instance)
        self.outbox.publish(
            organization_id=organization_id,
            workflow_id=workflow_id,
            process_run_id=process_run_id,
            event_type="workflow.started",
            payload={"trace_id": tid, "workflow_version": WORKFLOW_DEFINITION_VERSION},
            trace_id=tid,
        )
        self.run_until_idle(workflow_id)
        return self._load(workflow_id)

    def get(self, workflow_id: UUID) -> WorkflowInstance:
        return self._load(workflow_id)

    def get_by_process_run(self, process_run_id: UUID) -> WorkflowInstance | None:
        store = get_memory_store()
        for raw in store.workflow_instances.values():
            if raw.get("process_run_id") == str(process_run_id):
                return WorkflowInstance.from_checkpoint(migrate_workflow_state(raw))
        return None

    def history(self, workflow_id: UUID) -> list[dict[str, Any]]:
        instance = self._load(workflow_id)
        return [
            {"event_type": h.event_type, "at": h.at, "step": h.step, "detail": h.detail}
            for h in instance.history
        ]

    def signal(
        self,
        workflow_id: UUID,
        *,
        signal_type: str | WorkflowSignal,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
        reject_duplicates: bool = False,
    ) -> WorkflowInstance:
        instance = self._load(workflow_id)
        eid = event_id or str(uuid4())
        sig = signal_type.value if isinstance(signal_type, WorkflowSignal) else signal_type

        try:
            if reject_duplicates:
                self.inbox.accept_or_raise(
                    event_id=eid,
                    organization_id=instance.organization_id,
                    workflow_id=workflow_id,
                    signal_type=sig,
                    payload=payload or {},
                    trace_id=instance.trace_id,
                )
            else:
                accepted = self.inbox.accept(
                    event_id=eid,
                    organization_id=instance.organization_id,
                    workflow_id=workflow_id,
                    signal_type=sig,
                    payload=payload or {},
                    trace_id=instance.trace_id,
                )
                if not accepted:
                    # Replay protection: ignore duplicate delivery
                    instance.append_history("signal.duplicate_ignored", event_id=eid, signal_type=sig)
                    self._persist(instance)
                    return instance
        except DuplicateEventError:
            raise

        # Apply approval decision to approval record before workflow signal
        if sig == WorkflowSignal.APPROVAL_DECISION.value or sig == "approval_decision":
            self._apply_approval_decision(instance, payload or {})

        self.workflow.apply_signal(
            instance, {"type": sig, "payload": payload or {}, "event_id": eid}
        )
        self._persist(instance)
        self.outbox.publish(
            organization_id=instance.organization_id,
            workflow_id=workflow_id,
            process_run_id=instance.process_run_id,
            event_type=f"workflow.signal.{sig}",
            payload=payload or {},
            trace_id=instance.trace_id,
            event_id=UUID(eid) if _is_uuid(eid) else None,
        )

        if instance.status == WorkflowStatus.CANCELLED:
            ProcessRunRepository(instance.organization_id).set_status(
                instance.process_run_id, ProcessRunStatus.CANCELLED
            )
            return instance

        if instance.status != WorkflowStatus.PAUSED:
            self.run_until_idle(workflow_id)
        return self._load(workflow_id)

    def _apply_approval_decision(self, instance: WorkflowInstance, payload: dict[str, Any]) -> None:
        approval_id = instance.context.get("approval_id") or payload.get("approval_id")
        if not approval_id:
            return
        store = get_memory_store()
        record = store.approvals.get(UUID(str(approval_id)))
        if not record:
            return
        decision = str(payload.get("decision") or "").lower()
        now = utcnow()
        if decision == "approved":
            record.status = ApprovalStatus.APPROVED
        elif decision == "rejected":
            record.status = ApprovalStatus.REJECTED
        else:
            return
        record.decision = decision
        record.decision_reason = payload.get("reason")
        record.decision_note = payload.get("reason")
        record.decision_timestamp = now
        record.decided_by_user_id = (
            UUID(payload["decided_by_user_id"]) if payload.get("decided_by_user_id") else None
        )
        record.updated_at = now
        wait = instance.context.get("approval_wait")
        if isinstance(wait, dict):
            wait["decision"] = decision
            wait["decision_reason"] = payload.get("reason")
            wait["decision_timestamp"] = now.isoformat()
            requested = wait.get("requested_timestamp")
            if requested:
                try:
                    from datetime import datetime, timezone

                    from app.observability.metrics import M_APPROVAL_WAIT, metrics

                    started_at = datetime.fromisoformat(str(requested).replace("Z", "+00:00"))
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                    end = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
                    wait_ms = max(0.0, (end - started_at).total_seconds() * 1000)
                    metrics.observe(M_APPROVAL_WAIT, wait_ms)
                except Exception:  # noqa: BLE001
                    pass

    def check_timeout(self, workflow_id: UUID) -> WorkflowInstance:
        instance = self._load(workflow_id)
        deadline = _parse_iso(instance.timeout_at)
        if deadline and utcnow() > deadline and instance.status not in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.TIMED_OUT,
        }:
            instance.status = WorkflowStatus.TIMED_OUT
            instance.wait_reason = WaitReason.TIMEOUT
            instance.last_error = "Workflow timed out"
            instance.append_history("workflow.timed_out")
            self._persist(instance)
            ProcessRunRepository(instance.organization_id).set_status(
                instance.process_run_id, ProcessRunStatus.FAILED
            )
            self.outbox.publish(
                organization_id=instance.organization_id,
                workflow_id=workflow_id,
                process_run_id=instance.process_run_id,
                event_type="workflow.timed_out",
                payload={},
                trace_id=instance.trace_id,
            )
        return self._load(workflow_id)

    def recover(self, workflow_id: UUID) -> WorkflowInstance:
        """Worker restart simulation — reload checkpoint and continue."""
        instance = self._load(workflow_id)
        instance.append_history("workflow.recovered")
        self._persist(instance)
        if instance.status in {WorkflowStatus.RUNNING, WorkflowStatus.WAITING}:
            # Waiting stays idle until signal; running continues
            if instance.status == WorkflowStatus.RUNNING:
                self.run_until_idle(workflow_id)
        return self._load(workflow_id)

    def run_until_idle(self, workflow_id: UUID, *, max_steps: int = 64) -> WorkflowInstance:
        for _ in range(max_steps):
            instance = self._load(workflow_id)
            self.check_timeout(workflow_id)
            instance = self._load(workflow_id)

            if instance.status in {
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
                WorkflowStatus.TIMED_OUT,
                WorkflowStatus.PAUSED,
            }:
                break
            if instance.status == WorkflowStatus.WAITING and instance.wait_reason:
                break

            step = (
                PROCESS_FLOW[instance.step_index].value
                if instance.step_index < len(PROCESS_FLOW)
                else None
            )
            if step is None:
                instance.status = WorkflowStatus.COMPLETED
                self._persist(instance)
                break

            attempts = instance.activity_attempts.get(step, 0)
            try:
                result = self.workflow.execute_current_step(instance)
                instance.activity_attempts[step] = 0
                self._persist(instance)
                self.outbox.publish(
                    organization_id=instance.organization_id,
                    workflow_id=workflow_id,
                    process_run_id=instance.process_run_id,
                    event_type="workflow.step",
                    payload={"step": step, "data": result.data, "wait": result.wait_reason.value if result.wait_reason else None},
                    trace_id=instance.trace_id,
                )
                if result.wait_reason or instance.status != WorkflowStatus.RUNNING:
                    break
            except ActivityError as exc:
                attempts += 1
                instance.activity_attempts[step] = attempts
                instance.last_error = str(exc)
                instance.append_history(
                    "activity.error",
                    step=step,
                    error=str(exc),
                    error_type=exc.error_type,
                    attempt=attempts,
                )
                retryable = exc.retryable and self.retry_policy.is_retryable(exc.error_type)
                if retryable and attempts < self.retry_policy.max_attempts:
                    self._persist(instance)
                    delay = self.retry_policy.next_delay(attempts)
                    if self.sleep and delay > 0:
                        time.sleep(delay)
                    continue

                # Exhausted or non-retryable → DLQ + fail
                publish_dead_letter(
                    workflow_id=workflow_id,
                    organization_id=instance.organization_id,
                    activity_name=step or "unknown",
                    attempt=attempts,
                    error=str(exc),
                    payload={"error_type": exc.error_type},
                    trace_id=instance.trace_id,
                )
                instance.status = WorkflowStatus.FAILED
                self._persist(instance)
                # Map known terminal run statuses
                run_status = ProcessRunStatus.FAILED
                if exc.error_type == "ApprovalRejected":
                    run_status = ProcessRunStatus.REJECTED
                ProcessRunRepository(instance.organization_id).set_status(
                    instance.process_run_id, run_status
                )
                try:
                    from app.observability.metrics import M_PROCESS_FAILURES, metrics

                    metrics.incr(M_PROCESS_FAILURES)
                except Exception:  # noqa: BLE001
                    pass
                self.outbox.publish(
                    organization_id=instance.organization_id,
                    workflow_id=workflow_id,
                    process_run_id=instance.process_run_id,
                    event_type="workflow.failed",
                    payload={"error": str(exc), "error_type": exc.error_type},
                    trace_id=instance.trace_id,
                )
                break
            except Exception as exc:  # noqa: BLE001 — durable catch → DLQ
                attempts += 1
                instance.activity_attempts[step] = attempts
                instance.last_error = str(exc)
                instance.append_history("activity.error", step=step, error=str(exc), attempt=attempts)
                if attempts < self.retry_policy.max_attempts:
                    self._persist(instance)
                    continue
                publish_dead_letter(
                    workflow_id=workflow_id,
                    organization_id=instance.organization_id,
                    activity_name=step or "unknown",
                    attempt=attempts,
                    error=str(exc),
                    trace_id=instance.trace_id,
                )
                instance.status = WorkflowStatus.FAILED
                self._persist(instance)
                ProcessRunRepository(instance.organization_id).set_status(
                    instance.process_run_id, ProcessRunStatus.FAILED
                )
                try:
                    from app.observability.metrics import M_PROCESS_FAILURES, metrics

                    metrics.incr(M_PROCESS_FAILURES)
                except Exception:  # noqa: BLE001
                    pass
                break

        return self._load(workflow_id)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


# Process-local singleton for mock mode (shared across API requests in same process)
_ENGINE: MockDurableWorkflowEngine | None = None


def get_mock_engine() -> MockDurableWorkflowEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = MockDurableWorkflowEngine()
    return _ENGINE


def reset_mock_engine() -> None:
    global _ENGINE
    _ENGINE = None
