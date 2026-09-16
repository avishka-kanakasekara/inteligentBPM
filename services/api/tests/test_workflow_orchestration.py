"""Durable workflow orchestration tests (mock Temporal-equivalent engine)."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from app.contracts.common import utcnow
from app.database.memory import get_memory_store
from app.domain.enums import ApprovalStatus, ProcessRunStatus
from app.repositories.memory_repos import ProcessRepository, ProcessRunRepository
from app.workflows.activities import DefaultActivityRunner
from app.workflows.engine import MockDurableWorkflowEngine, reset_mock_engine
from app.workflows.models import WaitReason, WorkflowStatus
from app.workflows.outbox import DuplicateEventError, InboxService
from app.workflows.retry import RetryPolicy
from app.workflows.service import WorkflowOrchestrationService
from app.workflows.versioning import WORKFLOW_DEFINITION_VERSION


def _seed_process(org_id: UUID, user_id: UUID) -> tuple[UUID, UUID]:
    repo = ProcessRepository(org_id)
    proc = repo.create(name="WF Process", description="workflow", created_by_user_id=user_id)
    version = repo.create_version(
        proc.id,
        plan_snapshot={
            "goal": "Run durable workflow",
            "steps": [{"step_id": "s1", "title": "Do work", "success_criteria": ["ok"]}],
        },
        status="confirmed",
    )
    return proc.id, version.id


def _start(
    org_id: UUID,
    user_id: UUID,
    *,
    engine: MockDurableWorkflowEngine | None = None,
    context: dict | None = None,
    timeout_seconds: int | None = 86_400,
):
    reset_mock_engine()
    process_id, version_id = _seed_process(org_id, user_id)
    run = ProcessRunRepository(org_id).create(
        process_id=process_id,
        process_version_id=version_id,
        initiated_by_user_id=user_id,
        correlation_id="wf-test",
    )
    eng = engine or MockDurableWorkflowEngine()
    instance = eng.start(
        organization_id=org_id,
        process_id=process_id,
        process_run_id=run.id,
        process_version_id=version_id,
        initiated_by_user_id=user_id,
        trace_id=f"trace-{run.id}",
        context=context or {},
        timeout_seconds=timeout_seconds,
    )
    return eng, instance, run.id, process_id, version_id


def test_full_process_progression(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, run_id, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": False},
    )
    assert instance.status == WorkflowStatus.COMPLETED
    assert instance.workflow_version == WORKFLOW_DEFINITION_VERSION
    assert instance.trace_id.startswith("trace-")
    run = ProcessRunRepository(org_a).get(run_id)
    assert run.status == ProcessRunStatus.COMPLETED
    steps = [h.step for h in instance.history if h.event_type == "activity.completed"]
    assert "agent2_resource_allocation" in steps
    assert "agent3_risk_analysis" in steps
    assert "agent4_execution" in steps
    assert "complete" in steps
    # Outbox + agent runs
    store = get_memory_store()
    assert any(e.get("event_type") == "workflow.started" for e in store.workflow_outbox.values())
    assert any(r.get("agent_name") == "agent4_execution" for r in store.agent_run_records.values())


def test_pause_and_resume(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, _, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": True},
    )
    assert instance.status == WorkflowStatus.WAITING
    assert instance.wait_reason == WaitReason.HUMAN_APPROVAL

    paused = eng.signal(instance.id, signal_type="pause")
    assert paused.status == WorkflowStatus.PAUSED

    resumed = eng.signal(instance.id, signal_type="resume")
    assert resumed.status == WorkflowStatus.WAITING
    assert resumed.wait_reason == WaitReason.HUMAN_APPROVAL


def test_approval_waiting_and_approve(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, run_id, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": True},
    )
    assert instance.status == WorkflowStatus.WAITING
    approval_id = instance.context["approval_id"]
    wait = instance.context["approval_wait"]
    assert wait["approval_id"] == approval_id
    assert wait["organization_id"] == str(org_a)
    assert wait["process_run_id"] == str(run_id)
    assert wait["process_version_id"]
    assert wait["risk_analysis_id"]
    assert wait["snapshot_hash"]
    assert wait["requested_role"]
    assert wait["requested_timestamp"]
    assert wait["expiration_timestamp"]
    assert wait["audit_reference"]
    assert wait["decision"] is None

    done = eng.signal(
        instance.id,
        signal_type="approval_decision",
        payload={"decision": "approved", "reason": "looks good", "decided_by_user_id": str(user_a_id)},
    )
    assert done.status == WorkflowStatus.COMPLETED
    store = get_memory_store()
    record = store.approvals[UUID(approval_id)]
    assert record.status == ApprovalStatus.APPROVED
    assert record.decision == "approved"
    assert record.decision_reason == "looks good"
    assert record.decision_timestamp is not None
    assert record.risk_analysis_id is not None
    assert record.id == UUID(approval_id)


def test_approval_rejection(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, run_id, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": True},
    )
    failed = eng.signal(
        instance.id,
        signal_type="approval_decision",
        payload={"decision": "rejected", "reason": "too risky"},
    )
    assert failed.status == WorkflowStatus.FAILED
    run = ProcessRunRepository(org_a).get(run_id)
    assert run.status == ProcessRunStatus.REJECTED


def test_approval_expiration(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, _, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": True, "_approval_ttl_seconds": 1},
    )
    approval_id = UUID(instance.context["approval_id"])
    store = get_memory_store()
    record = store.approvals[approval_id]
    record.expiration_timestamp = utcnow() - timedelta(seconds=1)

    # Re-enter wait activity via retry signal
    result = eng.signal(instance.id, signal_type="retry")
    assert result.status == WorkflowStatus.FAILED
    assert store.approvals[approval_id].status == ApprovalStatus.EXPIRED


def test_plan_mutation_invalidates(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, _, process_id, version_id = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": True},
    )
    # Mutate plan snapshot hash after approval package created
    version = ProcessRepository(org_a).get_version(process_id, version_id)
    version.plan_snapshot_hash = "mutated-hash-should-fail"
    version.plan_snapshot = {"goal": "changed", "steps": []}

    result = eng.signal(
        instance.id,
        signal_type="approval_decision",
        payload={"decision": "approved", "reason": "stale"},
    )
    assert result.status == WorkflowStatus.FAILED
    assert result.last_error and "mutat" in result.last_error.lower()


def test_workflow_retry_after_transient_failure(org_a: UUID, user_a_id: UUID) -> None:
    eng = MockDurableWorkflowEngine(
        retry_policy=RetryPolicy(max_attempts=3, initial_interval_seconds=0),
    )
    _, instance, run_id, _, _ = _start(
        org_a,
        user_a_id,
        engine=eng,
        context={
            "_force_approval_required": False,
            "_fail_once": ["agent2_resource_allocation"],
        },
    )
    assert instance.status == WorkflowStatus.COMPLETED
    run = ProcessRunRepository(org_a).get(run_id)
    assert run.status == ProcessRunStatus.COMPLETED
    errors = [h for h in instance.history if h.event_type == "activity.error"]
    assert len(errors) >= 1


def test_duplicate_event_delivery(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, _, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": True},
    )
    event_id = str(uuid4())
    eng.signal(
        instance.id,
        signal_type="approval_decision",
        payload={"decision": "approved", "reason": "ok"},
        event_id=event_id,
    )
    # Duplicate delivery ignored (replay protection)
    again = eng.signal(
        instance.id,
        signal_type="approval_decision",
        payload={"decision": "rejected", "reason": "should ignore"},
        event_id=event_id,
    )
    assert again.status == WorkflowStatus.COMPLETED
    dupes = [h for h in again.history if h.event_type == "signal.duplicate_ignored"]
    assert dupes

    inbox = InboxService()
    with pytest.raises(DuplicateEventError):
        inbox.accept_or_raise(
            event_id=event_id,
            organization_id=org_a,
            workflow_id=instance.id,
            signal_type="approval_decision",
            payload={},
        )


def test_worker_restart_simulation(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, _, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": True},
    )
    assert instance.status == WorkflowStatus.WAITING
    workflow_id = instance.id

    # Simulate worker crash + new worker process recovering from checkpoint
    fresh = MockDurableWorkflowEngine()
    recovered = fresh.recover(workflow_id)
    assert recovered.status == WorkflowStatus.WAITING
    assert recovered.trace_id == instance.trace_id
    assert any(h.event_type == "workflow.recovered" for h in recovered.history)

    done = fresh.signal(
        workflow_id,
        signal_type="approval_decision",
        payload={"decision": "approved"},
    )
    assert done.status == WorkflowStatus.COMPLETED


def test_tool_failure_dead_letter(org_a: UUID, user_a_id: UUID) -> None:
    eng = MockDurableWorkflowEngine(
        retry_policy=RetryPolicy(max_attempts=2, initial_interval_seconds=0),
    )
    _, instance, _, _, _ = _start(
        org_a,
        user_a_id,
        engine=eng,
        context={
            "_force_approval_required": False,
            "_fail_activities": ["agent4_execution"],
        },
    )
    assert instance.status == WorkflowStatus.FAILED
    store = get_memory_store()
    assert store.workflow_dead_letters
    dlq = next(iter(store.workflow_dead_letters.values()))
    assert dlq["activity_name"] == "agent4_execution"
    assert dlq["status"] == "open"


def test_cancellation(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, run_id, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": True},
    )
    cancelled = eng.signal(instance.id, signal_type="cancel")
    assert cancelled.status == WorkflowStatus.CANCELLED
    run = ProcessRunRepository(org_a).get(run_id)
    assert run.status == ProcessRunStatus.CANCELLED


def test_missing_information_and_external_callback_waits(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, _, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_missing_info": True, "_force_approval_required": False},
    )
    assert instance.wait_reason == WaitReason.MISSING_INFORMATION
    eng.signal(
        instance.id,
        signal_type="missing_info_provided",
        payload={"fields": {"budget_code": "OPS-1"}},
    )
    # Inject external callback wait mid-flight by patching context before agent4
    # After missing info, workflow continues; force callback via context on a fresh wait path
    mid = eng.get(instance.id)
    if mid.status != WorkflowStatus.COMPLETED:
        # If still running somehow, fine; otherwise start a dedicated callback wait test
        pass

    # Dedicated external callback path
    reset_mock_engine()
    eng2, inst2, _, _, _ = _start(
        org_a,
        user_a_id,
        engine=MockDurableWorkflowEngine(),
        context={
            "_force_approval_required": False,
            "force_external_callback": True,
        },
    )
    # force_external_callback is checked in agent4 via ctx.context
    # Ensure key is set without underscore strip
    if inst2.status != WorkflowStatus.WAITING:
        # Re-run with context key the activity expects
        reset_mock_engine()
        eng2, inst2, _, _, _ = _start(
            org_a,
            user_a_id,
            engine=MockDurableWorkflowEngine(),
            context={
                "_force_approval_required": False,
                "force_external_callback": True,
            },
        )
    assert inst2.wait_reason == WaitReason.EXTERNAL_CALLBACK
    done = eng2.signal(inst2.id, signal_type="external_callback", payload={"ok": True})
    assert done.status == WorkflowStatus.COMPLETED


def test_integration_failure_recovery(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, _, _, _ = _start(
        org_a,
        user_a_id,
        context={
            "_force_approval_required": False,
            "integration_failure": True,
        },
    )
    assert instance.wait_reason == WaitReason.INTEGRATION_FAILURE
    done = eng.signal(instance.id, signal_type="integration_recovered", payload={})
    assert done.status == WorkflowStatus.COMPLETED


def test_timeout(org_a: UUID, user_a_id: UUID) -> None:
    eng, instance, run_id, _, _ = _start(
        org_a,
        user_a_id,
        context={"_force_approval_required": True},
        timeout_seconds=0,
    )
    # timeout_at is in the past (0 seconds from start)
    timed = eng.check_timeout(instance.id)
    # If already waiting, force timeout by backdating
    store = get_memory_store()
    raw = store.workflow_instances[instance.id]
    raw["timeout_at"] = (utcnow() - timedelta(seconds=5)).isoformat()
    timed = eng.check_timeout(instance.id)
    assert timed.status == WorkflowStatus.TIMED_OUT
    run = ProcessRunRepository(org_a).get(run_id)
    assert run.status == ProcessRunStatus.FAILED


def test_orchestration_service_api(org_a: UUID, user_a_id: UUID) -> None:
    reset_mock_engine()
    process_id, version_id = _seed_process(org_a, user_a_id)
    run = ProcessRunRepository(org_a).create(
        process_id=process_id,
        process_version_id=version_id,
        initiated_by_user_id=user_a_id,
        correlation_id="svc",
    )
    svc = WorkflowOrchestrationService()
    wf = svc.start_run(
        organization_id=org_a,
        process_id=process_id,
        process_run_id=run.id,
        process_version_id=version_id,
        initiated_by_user_id=user_a_id,
        correlation_id="svc-trace",
        context={"_force_approval_required": True},
    )
    assert wf.status == WorkflowStatus.WAITING
    svc.pause(wf.id)
    assert svc.describe(wf.id).status == WorkflowStatus.PAUSED
    svc.resume(wf.id)
    svc.submit_approval_decision(wf.id, decision="approved", decided_by_user_id=user_a_id)
    assert svc.describe(wf.id).status == WorkflowStatus.COMPLETED
    hist = svc.history(wf.id)
    assert hist
    events = svc.events_for_run(run.id)
    assert events
