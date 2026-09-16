"""Durable workflow domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.contracts.common import utcnow


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class WaitReason(StrEnum):
    HUMAN_APPROVAL = "human_approval"
    MISSING_INFORMATION = "missing_information"
    EXTERNAL_CALLBACK = "external_callback"
    INTEGRATION_FAILURE = "integration_failure"
    USER_PAUSE = "user_pause"
    APPROVAL_GATE = "approval_gate"
    TIMEOUT = "timeout"


class WorkflowSignal(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    RETRY = "retry"
    APPROVAL_DECISION = "approval_decision"
    MISSING_INFO_PROVIDED = "missing_info_provided"
    EXTERNAL_CALLBACK = "external_callback"
    INTEGRATION_RECOVERED = "integration_recovered"


class ProcessStepName(StrEnum):
    START = "start_process_run"
    LOAD_PLAN = "load_process_plan"
    QUOTA_CHECK = "quota_check"
    ENTITLEMENT_CHECK = "entitlement_check"
    AGENT1_PLANNING = "agent1_planning"
    AGENT2_ALLOCATION = "agent2_resource_allocation"
    PERSIST_ALLOCATION = "persist_resource_allocation"
    AGENT3_RISK = "agent3_risk_analysis"
    PERSIST_RISK = "persist_risk_result"
    STOP_IF_BLOCKED = "stop_if_blocked"
    REQUEST_APPROVAL = "request_approval"
    WAIT_APPROVAL = "wait_for_approval"
    REVALIDATE = "revalidate_plan_and_risk"
    AGENT4_EXECUTION = "agent4_execution"
    APPROVAL_GATES = "pause_at_approval_gates"
    NOTIFICATIONS = "notifications"
    AUDIT_EVENTS = "audit_events"
    COMPLETE = "complete"


PROCESS_FLOW: tuple[ProcessStepName, ...] = (
    ProcessStepName.START,
    ProcessStepName.LOAD_PLAN,
    ProcessStepName.QUOTA_CHECK,
    ProcessStepName.ENTITLEMENT_CHECK,
    ProcessStepName.AGENT1_PLANNING,
    ProcessStepName.AGENT2_ALLOCATION,
    ProcessStepName.PERSIST_ALLOCATION,
    ProcessStepName.AGENT3_RISK,
    ProcessStepName.PERSIST_RISK,
    ProcessStepName.STOP_IF_BLOCKED,
    ProcessStepName.REQUEST_APPROVAL,
    ProcessStepName.WAIT_APPROVAL,
    ProcessStepName.REVALIDATE,
    ProcessStepName.AGENT4_EXECUTION,
    ProcessStepName.APPROVAL_GATES,
    ProcessStepName.NOTIFICATIONS,
    ProcessStepName.AUDIT_EVENTS,
    ProcessStepName.COMPLETE,
)


@dataclass
class HistoryEvent:
    event_type: str
    at: str
    step: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunRecord:
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    process_run_id: UUID
    agent_name: str
    status: str
    trace_id: str
    started_at: str
    finished_at: str | None = None
    attempt: int = 1
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    output_snapshot: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ApprovalWaitRecord:
    """Approval record fields required by durable orchestration waits."""

    approval_id: UUID
    organization_id: UUID
    process_run_id: UUID
    process_version_id: UUID
    risk_analysis_id: UUID
    snapshot_hash: str
    requested_role: str
    requested_user: UUID | None
    decision: str | None
    decision_reason: str | None
    requested_timestamp: str
    decision_timestamp: str | None
    expiration_timestamp: str
    audit_reference: str


@dataclass
class WorkflowInstance:
    id: UUID
    organization_id: UUID
    process_id: UUID
    process_run_id: UUID
    process_version_id: UUID | None
    workflow_version: str
    status: WorkflowStatus
    trace_id: str
    step_index: int
    wait_reason: WaitReason | None
    history: list[HistoryEvent] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    pending_signals: list[dict[str, Any]] = field(default_factory=list)
    activity_attempts: dict[str, int] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: utcnow().isoformat())
    timeout_at: str | None = None
    last_error: str | None = None
    initiated_by_user_id: UUID | None = None

    def append_history(self, event_type: str, *, step: str | None = None, **detail: Any) -> None:
        self.history.append(
            HistoryEvent(
                event_type=event_type,
                at=utcnow().isoformat(),
                step=step,
                detail=detail,
            )
        )
        self.updated_at = utcnow().isoformat()

    def to_checkpoint(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "process_id": str(self.process_id),
            "process_run_id": str(self.process_run_id),
            "process_version_id": str(self.process_version_id)
            if self.process_version_id
            else None,
            "workflow_version": self.workflow_version,
            "status": self.status.value,
            "trace_id": self.trace_id,
            "step_index": self.step_index,
            "wait_reason": self.wait_reason.value if self.wait_reason else None,
            "history": [
                {
                    "event_type": h.event_type,
                    "at": h.at,
                    "step": h.step,
                    "detail": h.detail,
                }
                for h in self.history
            ],
            "context": self.context,
            "pending_signals": list(self.pending_signals),
            "activity_attempts": dict(self.activity_attempts),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "timeout_at": self.timeout_at,
            "last_error": self.last_error,
            "initiated_by_user_id": str(self.initiated_by_user_id)
            if self.initiated_by_user_id
            else None,
        }

    @classmethod
    def from_checkpoint(cls, data: dict[str, Any]) -> WorkflowInstance:
        history = [
            HistoryEvent(
                event_type=h["event_type"],
                at=h["at"],
                step=h.get("step"),
                detail=h.get("detail") or {},
            )
            for h in data.get("history") or []
        ]
        wait = data.get("wait_reason")
        return cls(
            id=UUID(data["id"]),
            organization_id=UUID(data["organization_id"]),
            process_id=UUID(data["process_id"]),
            process_run_id=UUID(data["process_run_id"]),
            process_version_id=UUID(data["process_version_id"])
            if data.get("process_version_id")
            else None,
            workflow_version=data["workflow_version"],
            status=WorkflowStatus(data["status"]),
            trace_id=data["trace_id"],
            step_index=int(data.get("step_index") or 0),
            wait_reason=WaitReason(wait) if wait else None,
            history=history,
            context=dict(data.get("context") or {}),
            pending_signals=list(data.get("pending_signals") or []),
            activity_attempts=dict(data.get("activity_attempts") or {}),
            created_at=data.get("created_at") or utcnow().isoformat(),
            updated_at=data.get("updated_at") or utcnow().isoformat(),
            timeout_at=data.get("timeout_at"),
            last_error=data.get("last_error"),
            initiated_by_user_id=UUID(data["initiated_by_user_id"])
            if data.get("initiated_by_user_id")
            else None,
        )
