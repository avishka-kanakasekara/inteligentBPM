"""BPM process workflow step machine (Temporal-compatible semantics)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.workflows.activities import ActivityContext, ActivityResult, ActivityRunner, DefaultActivityRunner
from app.workflows.models import PROCESS_FLOW, ProcessStepName, WaitReason, WorkflowInstance, WorkflowStatus


class BPMProcessWorkflow:
    """
    Durable process orchestration matching Temporal workflow semantics:

    - Deterministic step progression
    - Explicit waits (approval, missing info, callback, pause)
    - Signals applied before continuing
    - Versioned definition via workflow_version on the instance
    """

    def __init__(self, activities: ActivityRunner | None = None) -> None:
        self.activities = activities or DefaultActivityRunner()

    def current_step(self, instance: WorkflowInstance) -> ProcessStepName | None:
        if instance.step_index >= len(PROCESS_FLOW):
            return None
        return PROCESS_FLOW[instance.step_index]

    def build_activity_context(self, instance: WorkflowInstance) -> ActivityContext:
        return ActivityContext(
            organization_id=instance.organization_id,
            process_id=instance.process_id,
            process_run_id=instance.process_run_id,
            workflow_id=instance.id,
            trace_id=instance.trace_id,
            process_version_id=instance.process_version_id
            or (
                UUID(instance.context["process_version_id"])
                if instance.context.get("process_version_id")
                else None
            ),
            initiated_by_user_id=instance.initiated_by_user_id,
            context=instance.context,
            fail_activities=set(instance.context.get("_fail_activities") or []),
            fail_once=set(instance.context.get("_fail_once") or []),
            force_approval_required=instance.context.get("_force_approval_required"),
            force_blocked=bool(instance.context.get("_force_blocked")),
            force_missing_info=bool(instance.context.get("_force_missing_info")),
            force_gate=bool(instance.context.get("_force_gate")),
            approval_ttl_seconds=int(instance.context.get("_approval_ttl_seconds") or 3600),
            success_criteria_pass=instance.context.get("_success_criteria_pass", True) is not False,
        )

    def apply_signal(self, instance: WorkflowInstance, signal: dict[str, Any]) -> None:
        signal_type = signal.get("type")
        payload = signal.get("payload") or {}
        instance.append_history("signal.received", signal_type=signal_type, payload=payload)

        if signal_type == "pause":
            instance.status = WorkflowStatus.PAUSED
            instance.wait_reason = WaitReason.USER_PAUSE
            return
        if signal_type == "cancel":
            instance.status = WorkflowStatus.CANCELLED
            instance.wait_reason = None
            instance.append_history("workflow.cancelled")
            return
        if signal_type == "resume":
            if instance.status in {WorkflowStatus.PAUSED, WorkflowStatus.WAITING}:
                instance.status = WorkflowStatus.RUNNING
                if instance.wait_reason == WaitReason.USER_PAUSE:
                    instance.wait_reason = None
            return
        if signal_type == "retry":
            instance.status = WorkflowStatus.RUNNING
            instance.wait_reason = None
            instance.last_error = None
            # Stay on current step for retry
            return
        if signal_type == "approval_decision":
            instance.context["signal_approval_decision"] = payload
            # Clear wait so engine re-enters wait_for_approval activity
            if instance.wait_reason == WaitReason.HUMAN_APPROVAL:
                instance.wait_reason = None
                instance.status = WorkflowStatus.RUNNING
            return
        if signal_type == "missing_info_provided":
            instance.context["missing_information"] = []
            instance.context["_force_missing_info"] = False
            instance.context.update(payload.get("fields") or {})
            if instance.wait_reason == WaitReason.MISSING_INFORMATION:
                instance.wait_reason = None
                instance.status = WorkflowStatus.RUNNING
            return
        if signal_type == "external_callback":
            instance.context["external_callback"] = payload
            instance.context.pop("force_external_callback", None)
            if instance.wait_reason == WaitReason.EXTERNAL_CALLBACK:
                instance.wait_reason = None
                instance.status = WorkflowStatus.RUNNING
            return
        if signal_type == "integration_recovered":
            instance.context.pop("integration_failure", None)
            if instance.wait_reason == WaitReason.INTEGRATION_FAILURE:
                instance.wait_reason = None
                instance.status = WorkflowStatus.RUNNING
            return
        if signal_type == "approval_gate_cleared":
            instance.context.pop("pending_gate", None)
            if instance.wait_reason == WaitReason.APPROVAL_GATE:
                instance.wait_reason = None
                instance.status = WorkflowStatus.RUNNING
            return

    def execute_current_step(self, instance: WorkflowInstance) -> ActivityResult:
        step = self.current_step(instance)
        if step is None:
            instance.status = WorkflowStatus.COMPLETED
            return ActivityResult(terminal_status="completed")

        ctx = self.build_activity_context(instance)
        # Sync fail hooks back from mutable ctx sets
        result = self.activities.run(step.value, ctx)
        instance.context = ctx.context
        instance.context["_fail_once"] = list(ctx.fail_once)
        if ctx.process_version_id:
            instance.process_version_id = ctx.process_version_id

        instance.append_history(
            "activity.completed" if result.ok else "activity.failed",
            step=step.value,
            data=result.data,
            error=result.error,
        )

        if result.wait_reason:
            instance.status = WorkflowStatus.WAITING
            instance.wait_reason = result.wait_reason
            instance.append_history("workflow.waiting", step=step.value, reason=result.wait_reason.value)
            return result

        if result.skip_remaining:
            instance.status = WorkflowStatus.FAILED
            if result.terminal_status == "blocked":
                instance.context["blocked"] = True
            return result

        if result.terminal_status == "completed":
            instance.status = WorkflowStatus.COMPLETED
            instance.step_index = len(PROCESS_FLOW)
            return result

        # Advance
        instance.step_index += 1
        if instance.step_index >= len(PROCESS_FLOW):
            instance.status = WorkflowStatus.COMPLETED
        return result
