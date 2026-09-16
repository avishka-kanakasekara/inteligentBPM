"""Workflow activities — Agent 1–4, approvals, notifications, audit, quota/entitlement."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from app.contracts.common import utcnow
from app.database.memory import ApprovalRecord, get_memory_store, new_id
from app.domain.enums import ApprovalStatus, ProcessRunStatus
from app.repositories.memory_repos import ProcessRepository, ProcessRunRepository
from app.workflows.models import AgentRunRecord, ApprovalWaitRecord, WaitReason
from app.workflows.retry import DEFAULT_ACTIVITY_RETRY, RetryPolicy


class ActivityError(Exception):
    def __init__(self, message: str, *, error_type: str = "ActivityError", retryable: bool = True) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


@dataclass
class ActivityResult:
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    wait_reason: WaitReason | None = None
    error: str | None = None
    error_type: str | None = None
    retryable: bool = False
    skip_remaining: bool = False
    terminal_status: str | None = None


@dataclass
class ActivityContext:
    organization_id: UUID
    process_id: UUID
    process_run_id: UUID
    workflow_id: UUID
    trace_id: str
    process_version_id: UUID | None
    initiated_by_user_id: UUID | None
    context: dict[str, Any]
    # Test hooks / fault injection
    fail_activities: set[str] = field(default_factory=set)
    fail_once: set[str] = field(default_factory=set)
    force_approval_required: bool | None = None
    force_blocked: bool = False
    force_missing_info: bool = False
    force_gate: bool = False
    approval_ttl_seconds: int = 3600
    success_criteria_pass: bool = True


class ActivityRunner(Protocol):
    def run(self, name: str, ctx: ActivityContext) -> ActivityResult: ...


def _hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _record_agent_run(
    ctx: ActivityContext,
    *,
    agent_name: str,
    status: str,
    attempt: int,
    output: dict[str, Any] | None = None,
    error: str | None = None,
) -> UUID:
    store = get_memory_store()
    run_id = uuid4()
    now = utcnow().isoformat()
    record = AgentRunRecord(
        id=run_id,
        organization_id=ctx.organization_id,
        workflow_id=ctx.workflow_id,
        process_run_id=ctx.process_run_id,
        agent_name=agent_name,
        status=status,
        trace_id=ctx.trace_id,
        started_at=now,
        finished_at=now if status != "running" else None,
        attempt=attempt,
        input_snapshot={"process_id": str(ctx.process_id)},
        output_snapshot=output or {},
        error=error,
    )
    store.agent_run_records[run_id] = {
        "id": str(record.id),
        "organization_id": str(record.organization_id),
        "workflow_id": str(record.workflow_id),
        "process_run_id": str(record.process_run_id),
        "agent_name": record.agent_name,
        "status": record.status,
        "trace_id": record.trace_id,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "attempt": record.attempt,
        "input_snapshot": record.input_snapshot,
        "output_snapshot": record.output_snapshot,
        "error": record.error,
    }
    return run_id


class DefaultActivityRunner:
    """Default durable activities. Deterministic; LLM agents are invoked via thin adapters when needed."""

    def __init__(
        self,
        *,
        overrides: dict[str, Callable[[ActivityContext], ActivityResult]] | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.overrides = overrides or {}
        self.retry_policy = retry_policy or DEFAULT_ACTIVITY_RETRY

    def run(self, name: str, ctx: ActivityContext) -> ActivityResult:
        if name in ctx.fail_activities:
            raise ActivityError(f"Injected failure for {name}", error_type="ToolFailure", retryable=True)
        if name in ctx.fail_once:
            ctx.fail_once.discard(name)
            ctx.context["_fail_once"] = list(ctx.fail_once)
            raise ActivityError(f"Transient failure for {name}", error_type="TransientError", retryable=True)
        if name in self.overrides:
            return self.overrides[name](ctx)
        handler = getattr(self, f"activity_{name}", None)
        if handler is None:
            raise ActivityError(f"Unknown activity {name}", error_type="UnknownActivity", retryable=False)
        return handler(ctx)  # type: ignore[no-any-return]

    def activity_start_process_run(self, ctx: ActivityContext) -> ActivityResult:
        repo = ProcessRunRepository(ctx.organization_id)
        run = repo.get(ctx.process_run_id)
        run.status = ProcessRunStatus.DISCOVERING
        run.updated_at = utcnow()
        return ActivityResult(data={"status": run.status.value})

    def activity_load_process_plan(self, ctx: ActivityContext) -> ActivityResult:
        processes = ProcessRepository(ctx.organization_id)
        process = processes.get(ctx.process_id)
        version_id = ctx.process_version_id
        plan_snapshot: dict[str, Any] = {}
        plan_hash = ""
        if version_id:
            version = processes.get_version(ctx.process_id, version_id)
            plan_snapshot = dict(version.plan_snapshot)
            plan_hash = version.plan_snapshot_hash
        else:
            # Prefer latest confirmed / immutable version
            versions = [
                v
                for v in get_memory_store().process_versions.values()
                if v.organization_id == ctx.organization_id and v.process_id == ctx.process_id
            ]
            versions.sort(key=lambda v: v.version_number, reverse=True)
            if not versions:
                raise ActivityError("No process plan found", error_type="ValidationAppError", retryable=False)
            version = versions[0]
            version_id = version.id
            plan_snapshot = dict(version.plan_snapshot)
            plan_hash = version.plan_snapshot_hash
            ctx.process_version_id = version_id

        ctx.context["process_version_id"] = str(version_id)
        ctx.context["plan_snapshot"] = plan_snapshot
        ctx.context["plan_snapshot_hash"] = plan_hash
        ctx.context["plan_loaded_at"] = utcnow().isoformat()
        run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
        run.process_version_id = version_id
        run.plan_snapshot_hash = plan_hash
        run.status = ProcessRunStatus.PLAN_READY
        run.updated_at = utcnow()
        return ActivityResult(
            data={
                "process_id": str(process.id),
                "process_version_id": str(version_id),
                "plan_snapshot_hash": plan_hash,
            }
        )

    def activity_quota_check(self, ctx: ActivityContext) -> ActivityResult:
        # Foundation: always pass; hook for metering later
        ctx.context["quota_ok"] = True
        return ActivityResult(data={"quota_ok": True})

    def activity_entitlement_check(self, ctx: ActivityContext) -> ActivityResult:
        from app.billing.service import EntitlementService

        EntitlementService().assert_feature(ctx.organization_id, "process.execution")
        ctx.context["entitlement_ok"] = True
        ctx.context["plan_code"] = EntitlementService().plan_code_for_org(ctx.organization_id)
        return ActivityResult(
            data={"entitlement_ok": True, "plan_code": ctx.context["plan_code"]}
        )

    def activity_agent1_planning(self, ctx: ActivityContext) -> ActivityResult:
        """Agent 1 — planning. Uses loaded plan unless missing_info wait is forced."""
        _record_agent_run(ctx, agent_name="agent1_planning", status="completed", attempt=1)
        if ctx.force_missing_info:
            ctx.context["missing_information"] = ["budget_code"]
            return ActivityResult(
                ok=True,
                wait_reason=WaitReason.MISSING_INFORMATION,
                data={"missing": ["budget_code"]},
            )
        plan = ctx.context.get("plan_snapshot") or {}
        if not plan:
            raise ActivityError("Plan missing for Agent 1", error_type="ValidationAppError", retryable=False)
        return ActivityResult(data={"agent": "agent1", "plan_present": True})

    def activity_agent2_resource_allocation(self, ctx: ActivityContext) -> ActivityResult:
        _record_agent_run(ctx, agent_name="agent2_resource_allocation", status="running", attempt=1)
        allocation = {
            "process_id": str(ctx.process_id),
            "process_version_id": ctx.context.get("process_version_id"),
            "assignments": ctx.context.get("allocation_assignments")
            or [{"resource_type": "department", "resource_id": "ops"}],
            "status": "allocated",
        }
        allocation_hash = _hash(allocation)
        ctx.context["allocation_result"] = allocation
        ctx.context["allocation_snapshot_hash"] = allocation_hash
        run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
        run.status = ProcessRunStatus.ALLOCATING
        run.updated_at = utcnow()
        _record_agent_run(
            ctx,
            agent_name="agent2_resource_allocation",
            status="completed",
            attempt=1,
            output={"allocation_snapshot_hash": allocation_hash},
        )
        return ActivityResult(data={"allocation_snapshot_hash": allocation_hash})

    def activity_persist_resource_allocation(self, ctx: ActivityContext) -> ActivityResult:
        store = get_memory_store()
        allocation_id = new_id()
        version_id = UUID(ctx.context["process_version_id"])
        now = utcnow()
        from app.database.memory import AllocationResultRecord

        record = AllocationResultRecord(
            id=allocation_id,
            organization_id=ctx.organization_id,
            process_id=ctx.process_id,
            process_version_id=version_id,
            status="allocated",
            result_snapshot=dict(ctx.context.get("allocation_result") or {}),
            created_at=now,
            updated_at=now,
        )
        store.allocations[allocation_id] = record
        ctx.context["allocation_id"] = str(allocation_id)
        run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
        run.status = ProcessRunStatus.ALLOCATED
        run.updated_at = now
        return ActivityResult(data={"allocation_id": str(allocation_id)})

    def activity_agent3_risk_analysis(self, ctx: ActivityContext) -> ActivityResult:
        _record_agent_run(ctx, agent_name="agent3_risk_analysis", status="running", attempt=1)
        run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
        run.status = ProcessRunStatus.ANALYZING_RISK
        run.updated_at = utcnow()

        if ctx.force_blocked:
            decision = "BLOCKED"
            requires_approval = False
        elif ctx.force_approval_required is False:
            decision = "CLEAR"
            requires_approval = False
        else:
            decision = "APPROVAL_REQUIRED"
            requires_approval = True

        risk_payload = {
            "decision": decision,
            "plan_snapshot_hash": ctx.context.get("plan_snapshot_hash"),
            "allocation_snapshot_hash": ctx.context.get("allocation_snapshot_hash"),
            "requires_approval": requires_approval,
            "required_roles": ["manager"] if requires_approval else [],
        }
        risk_hash = _hash(risk_payload)
        ctx.context["risk_result"] = risk_payload
        ctx.context["risk_snapshot_hash"] = risk_hash
        ctx.context["risk_decision"] = decision
        ctx.context["requires_approval"] = requires_approval
        _record_agent_run(
            ctx,
            agent_name="agent3_risk_analysis",
            status="completed",
            attempt=1,
            output={"decision": decision, "risk_snapshot_hash": risk_hash},
        )
        return ActivityResult(data={"decision": decision, "risk_snapshot_hash": risk_hash})

    def activity_persist_risk_result(self, ctx: ActivityContext) -> ActivityResult:
        from app.database.memory import RiskResultRecord

        store = get_memory_store()
        risk_id = new_id()
        version_id = UUID(ctx.context["process_version_id"])
        now = utcnow()
        record = RiskResultRecord(
            id=risk_id,
            organization_id=ctx.organization_id,
            process_id=ctx.process_id,
            process_version_id=version_id,
            allocation_id=UUID(ctx.context["allocation_id"]) if ctx.context.get("allocation_id") else None,
            status="complete",
            result_snapshot=dict(ctx.context.get("risk_result") or {}),
            plan_snapshot_hash=str(ctx.context.get("plan_snapshot_hash") or ""),
            allocation_snapshot_hash=ctx.context.get("allocation_snapshot_hash"),
            risk_snapshot_hash=str(ctx.context.get("risk_snapshot_hash") or ""),
            valid=True,
            invalidated_reason=None,
            created_at=now,
            updated_at=now,
        )
        store.risk_results[risk_id] = record
        ctx.context["risk_analysis_id"] = str(risk_id)
        run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
        run.status = ProcessRunStatus.RISK_COMPLETE
        run.risk_snapshot_hash = record.risk_snapshot_hash
        run.updated_at = now
        return ActivityResult(data={"risk_analysis_id": str(risk_id)})

    def activity_stop_if_blocked(self, ctx: ActivityContext) -> ActivityResult:
        if ctx.context.get("risk_decision") == "BLOCKED":
            run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
            run.status = ProcessRunStatus.BLOCKED
            run.pause_reason = "risk_blocked"
            run.updated_at = utcnow()
            return ActivityResult(
                ok=True,
                wait_reason=WaitReason.INTEGRATION_FAILURE
                if ctx.context.get("integration_failure")
                else None,
                skip_remaining=True,
                terminal_status="blocked",
                data={"blocked": True},
            )
        return ActivityResult(data={"blocked": False})

    def activity_request_approval(self, ctx: ActivityContext) -> ActivityResult:
        if not ctx.context.get("requires_approval"):
            return ActivityResult(data={"approval_required": False})

        store = get_memory_store()
        now = utcnow()
        expires = now + timedelta(seconds=ctx.approval_ttl_seconds)
        approval_id = new_id()
        snapshot_hash = _hash(
            {
                "plan": ctx.context.get("plan_snapshot_hash"),
                "allocation": ctx.context.get("allocation_snapshot_hash"),
                "risk": ctx.context.get("risk_snapshot_hash"),
                "process_run_id": str(ctx.process_run_id),
            }
        )
        audit_ref = f"audit:{approval_id}"
        version_id = UUID(ctx.context["process_version_id"])
        risk_analysis_id = UUID(ctx.context["risk_analysis_id"])
        requested_role = (ctx.context.get("risk_result") or {}).get("required_roles", ["manager"])[0]

        record = ApprovalRecord(
            id=approval_id,
            organization_id=ctx.organization_id,
            process_run_id=ctx.process_run_id,
            status=ApprovalStatus.PENDING,
            snapshot_hash=snapshot_hash,
            snapshot_payload={
                "plan_snapshot_hash": ctx.context.get("plan_snapshot_hash"),
                "allocation_snapshot_hash": ctx.context.get("allocation_snapshot_hash"),
                "risk_snapshot_hash": ctx.context.get("risk_snapshot_hash"),
            },
            decided_by_user_id=None,
            decision_note=None,
            row_version=1,
            created_at=now,
            updated_at=now,
            process_id=ctx.process_id,
            process_version_id=version_id,
            risk_result_id=risk_analysis_id,
            plan_snapshot_hash=ctx.context.get("plan_snapshot_hash"),
            allocation_snapshot_hash=ctx.context.get("allocation_snapshot_hash"),
            risk_snapshot_hash=ctx.context.get("risk_snapshot_hash"),
            required_roles=[requested_role],
            requested_role=requested_role,
            requested_user=ctx.initiated_by_user_id,
            decision=None,
            decision_reason=None,
            requested_timestamp=now,
            decision_timestamp=None,
            expiration_timestamp=expires,
            audit_reference=audit_ref,
            risk_analysis_id=risk_analysis_id,
        )
        store.approvals[approval_id] = record

        wait = ApprovalWaitRecord(
            approval_id=approval_id,
            organization_id=ctx.organization_id,
            process_run_id=ctx.process_run_id,
            process_version_id=version_id,
            risk_analysis_id=risk_analysis_id,
            snapshot_hash=snapshot_hash,
            requested_role=requested_role,
            requested_user=ctx.initiated_by_user_id,
            decision=None,
            decision_reason=None,
            requested_timestamp=now.isoformat(),
            decision_timestamp=None,
            expiration_timestamp=expires.isoformat(),
            audit_reference=audit_ref,
        )
        ctx.context["approval_wait"] = {
            "approval_id": str(wait.approval_id),
            "organization_id": str(wait.organization_id),
            "process_run_id": str(wait.process_run_id),
            "process_version_id": str(wait.process_version_id),
            "risk_analysis_id": str(wait.risk_analysis_id),
            "snapshot_hash": wait.snapshot_hash,
            "requested_role": wait.requested_role,
            "requested_user": str(wait.requested_user) if wait.requested_user else None,
            "decision": wait.decision,
            "decision_reason": wait.decision_reason,
            "requested_timestamp": wait.requested_timestamp,
            "decision_timestamp": wait.decision_timestamp,
            "expiration_timestamp": wait.expiration_timestamp,
            "audit_reference": wait.audit_reference,
        }
        ctx.context["approval_id"] = str(approval_id)
        ctx.context["approval_snapshot_hash"] = snapshot_hash

        run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
        run.status = ProcessRunStatus.AWAITING_APPROVAL
        run.approval_id = approval_id
        run.updated_at = now
        return ActivityResult(data={"approval_id": str(approval_id), "approval_required": True})

    def activity_wait_for_approval(self, ctx: ActivityContext) -> ActivityResult:
        if not ctx.context.get("requires_approval"):
            return ActivityResult(data={"skipped": True})

        approval_id = UUID(ctx.context["approval_id"])
        store = get_memory_store()
        record = store.approvals.get(approval_id)
        if record is None:
            raise ActivityError("Approval record missing", error_type="ValidationAppError", retryable=False)

        now = utcnow()
        if (
            record.status == ApprovalStatus.PENDING
            and record.expiration_timestamp
            and now > record.expiration_timestamp
        ):
            record.status = ApprovalStatus.EXPIRED
            record.decision = "expired"
            record.decision_reason = "Approval TTL exceeded"
            record.decision_timestamp = now
            record.updated_at = now
            run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
            run.status = ProcessRunStatus.FAILED
            run.updated_at = now
            raise ActivityError("Approval expired", error_type="ApprovalExpired", retryable=False)

        if record.status == ApprovalStatus.PENDING:
            return ActivityResult(ok=True, wait_reason=WaitReason.HUMAN_APPROVAL, data={"waiting": True})

        if record.status == ApprovalStatus.REJECTED:
            run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
            run.status = ProcessRunStatus.REJECTED
            run.updated_at = now
            raise ActivityError("Approval rejected", error_type="ApprovalRejected", retryable=False)

        if record.status == ApprovalStatus.EXPIRED:
            raise ActivityError("Approval expired", error_type="ApprovalExpired", retryable=False)

        if record.status != ApprovalStatus.APPROVED:
            raise ActivityError(
                f"Unexpected approval status {record.status}",
                error_type="ValidationAppError",
                retryable=False,
            )

        run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
        run.status = ProcessRunStatus.APPROVED
        run.updated_at = now
        ctx.context["approval_decision"] = "approved"
        return ActivityResult(data={"decision": "approved"})

    def activity_revalidate_plan_and_risk(self, ctx: ActivityContext) -> ActivityResult:
        """Revalidate plan and risk snapshot hashes before execution."""
        version_id = UUID(ctx.context["process_version_id"])
        processes = ProcessRepository(ctx.organization_id)
        version = processes.get_version(ctx.process_id, version_id)
        current_plan_hash = version.plan_snapshot_hash
        expected_plan = ctx.context.get("plan_snapshot_hash")
        if current_plan_hash != expected_plan:
            raise ActivityError(
                "Plan mutated after approval snapshot",
                error_type="PlanMutated",
                retryable=False,
            )

        approval_id = ctx.context.get("approval_id")
        if approval_id:
            store = get_memory_store()
            record = store.approvals.get(UUID(approval_id))
            if record and record.snapshot_hash != ctx.context.get("approval_snapshot_hash"):
                raise ActivityError(
                    "Approval snapshot mismatch",
                    error_type="PlanMutated",
                    retryable=False,
                )
            # Also detect plan hash drift vs approval package
            if record and record.plan_snapshot_hash and record.plan_snapshot_hash != current_plan_hash:
                record.status = ApprovalStatus.INVALIDATED
                record.updated_at = utcnow()
                raise ActivityError(
                    "Plan mutated; approval invalidated",
                    error_type="PlanMutated",
                    retryable=False,
                )

        return ActivityResult(
            data={
                "plan_snapshot_hash": current_plan_hash,
                "risk_snapshot_hash": ctx.context.get("risk_snapshot_hash"),
                "revalidated": True,
            }
        )

    def activity_agent4_execution(self, ctx: ActivityContext) -> ActivityResult:
        _record_agent_run(ctx, agent_name="agent4_execution", status="running", attempt=1)
        if ctx.context.get("force_external_callback"):
            return ActivityResult(
                ok=True,
                wait_reason=WaitReason.EXTERNAL_CALLBACK,
                data={"waiting_callback": True},
            )
        if ctx.context.get("integration_failure"):
            return ActivityResult(
                ok=True,
                wait_reason=WaitReason.INTEGRATION_FAILURE,
                data={"integration_failure": True},
            )

        run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
        run.status = ProcessRunStatus.EXECUTING
        run.updated_at = utcnow()
        ctx.context["execution_result"] = {"status": "success", "steps_completed": 1}
        _record_agent_run(
            ctx,
            agent_name="agent4_execution",
            status="completed",
            attempt=1,
            output=ctx.context["execution_result"],
        )
        return ActivityResult(data=ctx.context["execution_result"])

    def activity_pause_at_approval_gates(self, ctx: ActivityContext) -> ActivityResult:
        gates = list(ctx.context.get("approval_gates") or [])
        if ctx.force_gate and "mid_exec_gate" not in gates:
            gates.append("mid_exec_gate")
            ctx.context["approval_gates"] = gates
        pending = ctx.context.get("pending_gate")
        if pending:
            return ActivityResult(
                ok=True,
                wait_reason=WaitReason.APPROVAL_GATE,
                data={"gate": pending},
            )
        if gates:
            gate = gates.pop(0)
            ctx.context["approval_gates"] = gates
            ctx.context["pending_gate"] = gate
            run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
            run.status = ProcessRunStatus.AWAITING_APPROVAL
            run.pause_reason = f"gate:{gate}"
            run.updated_at = utcnow()
            return ActivityResult(
                ok=True,
                wait_reason=WaitReason.APPROVAL_GATE,
                data={"gate": gate},
            )
        return ActivityResult(data={"gates_cleared": True})

    def activity_notifications(self, ctx: ActivityContext) -> ActivityResult:
        store = get_memory_store()
        nid = new_id()
        store.notifications[nid] = {
            "id": str(nid),
            "organization_id": str(ctx.organization_id),
            "process_run_id": str(ctx.process_run_id),
            "trace_id": ctx.trace_id,
            "type": "workflow.status",
            "payload": {"status": "completing"},
            "at": utcnow().isoformat(),
        }
        return ActivityResult(data={"notification_id": str(nid)})

    def activity_audit_events(self, ctx: ActivityContext) -> ActivityResult:
        from app.audit import AuditService

        AuditService().record(
            organization_id=ctx.organization_id,
            actor_user_id=ctx.initiated_by_user_id,
            action="workflow.audit_checkpoint",
            resource_type="process_run",
            resource_id=ctx.process_run_id,
            correlation_id=ctx.trace_id,
            payload={"workflow_id": str(ctx.workflow_id)},
        )
        return ActivityResult(data={"audited": True})

    def activity_complete(self, ctx: ActivityContext) -> ActivityResult:
        if not ctx.success_criteria_pass:
            raise ActivityError(
                "Success criteria not met",
                error_type="ValidationAppError",
                retryable=False,
            )
        if ctx.context.get("pending_gate"):
            raise ActivityError(
                "Cannot complete while approval gate pending",
                error_type="ConflictError",
                retryable=False,
            )
        run = ProcessRunRepository(ctx.organization_id).get(ctx.process_run_id)
        run.status = ProcessRunStatus.COMPLETED
        run.updated_at = utcnow()
        return ActivityResult(data={"status": "completed"}, terminal_status="completed")
