"""Agent 4 — Controlled Process Execution orchestration."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC
from typing import Any
from uuid import UUID

import structlog

from app.agents.execution.catalog import TOOL_ARGS, TOOL_CATALOG
from app.agents.execution.gateway import ToolGateway
from app.agents.execution.models import (
    ExecutionState,
    ToolContext,
    ToolInvocation,
    ToolProposalOutput,
)
from app.agents.execution.quotations import compare_quotations, normalize_quotation
from app.agents.risk.models import RiskDecision
from app.audit import AuditService
from app.contracts.common import utcnow
from app.database.memory import get_memory_store
from app.domain.enums import ApprovalStatus, ProcessRunStatus
from app.llm.client import FakeGeminiClient, GeminiClient, create_gemini_client
from app.llm.prompt_registry import PromptRegistry
from app.llm.structured import StructuredGenerationService
from app.llm.types import AgentExecutionContext, AgentKind
from app.repositories.memory_repos import (
    EmployeeRepository,
    ProcessRepository,
    ProcessRunRepository,
    SupplierContactRepository,
    SupplierRepository,
)
from app.security.errors import ConflictError, NotFoundError, ValidationAppError

logger = structlog.get_logger()


class ExecutionService:
    """Start/resume execution against approved snapshots; invoke tools via gateway."""

    def __init__(
        self,
        organization_id: UUID,
        *,
        gateway: ToolGateway | None = None,
        client: GeminiClient | None = None,
        structured: StructuredGenerationService | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.store = get_memory_store()
        self.processes = ProcessRepository(organization_id)
        self.runs = ProcessRunRepository(organization_id)
        self.gateway = gateway or ToolGateway()
        self.audit = AuditService()
        self.client = client or create_gemini_client()
        self.structured = structured or StructuredGenerationService(client=self.client)
        self.prompts = PromptRegistry()

    def start_execution(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        permissions: frozenset[str],
        dry_run: bool = False,
        process_version_id: UUID | None = None,
        approval_id: UUID | None = None,
    ) -> dict[str, Any]:
        process = self.processes.get(process_id)
        version = None
        if process_version_id:
            version = self.processes.get_version(process_id, process_version_id)
        else:
            versions = self.processes.list_versions(process_id)
            if not versions:
                raise ValidationAppError("No plan version available for execution")
            confirmed = [v for v in versions if v.status == "confirmed"]
            version = max(confirmed or versions, key=lambda v: v.version_number)

        risk = self._latest_risk(process_id)
        if risk is None and not dry_run:
            raise ValidationAppError("Risk analysis required before execution")
        if risk and not risk.get("valid", True) and not dry_run:
            raise ConflictError(
                "Risk result invalidated; re-run analysis before execution",
                code="RISK_INVALIDATED",
            )
        decision = (risk or {}).get("decision")
        if not dry_run and decision == RiskDecision.BLOCKED.value:
            raise ConflictError(
                "Blocked risk decision cannot proceed without override",
                code="BLOCKED_REQUIRES_OVERRIDE",
            )
        if not dry_run and decision == RiskDecision.INSUFFICIENT_INFORMATION.value:
            raise ValidationAppError("Insufficient risk information to execute")

        approval = None
        if approval_id:
            approval = self.store.approvals.get(approval_id)
            if approval is None or approval.organization_id != self.organization_id:
                raise NotFoundError("Approval not found")
        elif not dry_run and decision == RiskDecision.APPROVAL_REQUIRED.value:
            approval = self._latest_approved(process_id)
            if approval is None:
                raise ConflictError(
                    "Approved snapshot required before execution",
                    code="APPROVAL_REQUIRED",
                )

        plan_hash = version.plan_snapshot_hash
        risk_hash = (risk or {}).get("risk_snapshot_hash")
        if approval and not dry_run:
            if approval.status != ApprovalStatus.APPROVED:
                raise ConflictError("Approval is not granted", code="APPROVAL_REQUIRED")
            if approval.plan_snapshot_hash and approval.plan_snapshot_hash != plan_hash:
                raise ConflictError(
                    "Approval plan snapshot mismatch",
                    code="APPROVAL_PLAN_MISMATCH",
                )
            if (
                risk_hash
                and approval.risk_snapshot_hash
                and approval.risk_snapshot_hash != risk_hash
            ):
                raise ConflictError(
                    "Approval risk snapshot mismatch",
                    code="APPROVAL_RISK_MISMATCH",
                )

        run = self.runs.create(
            process_id=process_id,
            process_version_id=version.id,
            initiated_by_user_id=user_id,
            correlation_id=correlation_id,
        )
        run.plan_snapshot_hash = plan_hash
        run.risk_snapshot_hash = risk_hash
        run.approval_id = approval.id if approval else None
        run.dry_run = dry_run
        run.current_step_index = 0
        run.pause_reason = None
        allowed = self._allowed_tools_from_plan(version.plan_snapshot)
        run.allowed_tools = allowed
        run.status = ProcessRunStatus.EXECUTING if not dry_run else ProcessRunStatus.DRAFT
        run.updated_at = utcnow()
        from app.database.persist_helpers import persist_if_postgres

        persist_if_postgres(self.store, "process_runs", run.id)

        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="execution.started",
            resource_type="process_run",
            resource_id=run.id,
            correlation_id=correlation_id,
            payload={"dry_run": dry_run, "process_name": process.name},
        )
        return self.get_execution(process_id, run_id=run.id)

    def auto_run_execution(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        permissions: frozenset[str],
        dry_run: bool = False,
        process_version_id: UUID | None = None,
        approval_id: UUID | None = None,
        max_steps: int = 20,
    ) -> dict[str, Any]:
        """Start a real run and let Gemini choose/execute tools until complete or paused."""
        state = self.start_execution(
            process_id,
            user_id=user_id,
            correlation_id=correlation_id,
            permissions=permissions,
            dry_run=dry_run,
            process_version_id=process_version_id,
            approval_id=approval_id,
        )
        run_id = UUID(str(state["process_run_id"]))
        return self.advance_execution(
            process_id,
            user_id=user_id,
            correlation_id=correlation_id,
            permissions=permissions,
            run_id=run_id,
            max_steps=max_steps,
        )

    def advance_execution(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        permissions: frozenset[str],
        run_id: UUID | None = None,
        max_steps: int = 20,
    ) -> dict[str, Any]:
        """Gemini proposes tools → gateway executes them (no dry-run unless run flagged)."""
        run = self._resolve_run(process_id, run_id)
        version = self.processes.get_version(process_id, run.process_version_id)
        steps = (version.plan_snapshot or {}).get("steps") or []
        max_steps = max(1, min(int(max_steps or 40), 80))
        self._trace(
            run,
            f"Reading the plan ({len(steps)} steps) and working through every outcome.",
            kind="plan",
        )

        if run.status in {
            ProcessRunStatus.PAUSED,
            ProcessRunStatus.BLOCKED,
            ProcessRunStatus.AWAITING_APPROVAL,
        }:
            run.status = ProcessRunStatus.EXECUTING
            run.pause_reason = None
            run.updated_at = utcnow()

        if run.dry_run:
            run.dry_run = False
            run.status = ProcessRunStatus.EXECUTING
            run.updated_at = utcnow()

        executed = 0
        for _ in range(max_steps):
            curr_idx = int(getattr(run, "current_step_index", 0) or 0)
            if steps and curr_idx >= len(steps):
                run.status = ProcessRunStatus.COMPLETED
                run.pause_reason = None
                run.updated_at = utcnow()
                break
            if run.status not in {
                ProcessRunStatus.EXECUTING,
                ProcessRunStatus.DRAFT,
                ProcessRunStatus.APPROVED,
            }:
                break

            proposal = self.propose_next_tool(
                process_id,
                user_id=user_id,
                correlation_id=correlation_id,
                run_id=run.id,
                permissions=permissions,
            )
            if proposal.requires_approval and not getattr(run, "approval_id", None):
                run.status = ProcessRunStatus.AWAITING_APPROVAL
                run.pause_reason = proposal.approval_reason or proposal.rationale
                run.updated_at = utcnow()
                break

            proposal = self._refine_proposal(
                proposal,
                process_id=process_id,
                run=run,
                steps=steps,
                curr_idx=curr_idx,
                allowed=list(getattr(run, "allowed_tools", None) or list(TOOL_CATALOG.keys())),
            )
            self._trace(
                run,
                proposal.rationale or f"Next: {proposal.tool_name}",
                kind="decide",
                tool=proposal.tool_name,
                step=curr_idx,
            )
            if proposal.tool_name == "__noop__":
                self._apply_step_progress(
                    run,
                    steps=steps,
                    curr_idx=curr_idx,
                    proposal=proposal,
                    invocation_status="executed",
                )
                continue

            args = dict(proposal.arguments or {})
            self._ensure_tool_args(proposal.tool_name, args, process_id=process_id, run=run)
            blocked = self._outbound_block_reason(proposal.tool_name, args, run=run)
            if blocked:
                logger.info(
                    "execution.outbound_blocked",
                    tool=proposal.tool_name,
                    reason=blocked,
                    run_id=str(run.id),
                )
                # Prefer a non-email tool instead of pausing the whole run.
                alt = self._heuristic_proposal(
                    current_step=steps[curr_idx] if curr_idx < len(steps) else None,
                    allowed=[
                        t
                        for t in (
                            getattr(run, "allowed_tools", None) or list(TOOL_CATALOG.keys())
                        )
                        if t
                        not in {
                            "email.send",
                            proposal.tool_name,
                        }
                    ],
                    curr_idx=curr_idx,
                    allocation=self._latest_allocation(process_id) or {},
                    process_id=process_id,
                    run=run,
                )
                if alt.tool_name in {"email.send", proposal.tool_name}:
                    # Do not skip unfinished plan work just because outbound is blocked.
                    checklist = self._step_checklist(
                        step=steps[curr_idx] if curr_idx < len(steps) else None,
                        run=run,
                    )
                    rem = [
                        t
                        for t in (checklist.get("remaining") or [])
                        if t
                        not in {
                            "email.send",
                            "email.create_draft",
                            proposal.tool_name,
                        }
                    ]
                    if checklist.get("complete"):
                        self._apply_step_progress(
                            run,
                            steps=steps,
                            curr_idx=curr_idx,
                            proposal=ToolProposalOutput(
                                tool_name="__noop__",
                                arguments={},
                                rationale=blocked,
                                next_step_index=curr_idx + 1,
                            ),
                            invocation_status="executed",
                        )
                        continue
                    if not rem:
                        run.status = ProcessRunStatus.PAUSED
                        run.pause_reason = blocked
                        run.updated_at = utcnow()
                        break
                    proposal = ToolProposalOutput(
                        tool_name=rem[0],
                        arguments={},
                        rationale=f"{blocked} — switching to {rem[0]}",
                        next_step_index=None,
                    )
                    args = dict(proposal.arguments or {})
                    self._ensure_tool_args(
                        proposal.tool_name, args, process_id=process_id, run=run
                    )
                else:
                    proposal = alt
                    args = dict(proposal.arguments or {})
                    self._ensure_tool_args(
                        proposal.tool_name, args, process_id=process_id, run=run
                    )

            inv = self.invoke_tool(
                process_id,
                tool_name=proposal.tool_name,
                arguments=args,
                user_id=user_id,
                correlation_id=correlation_id,
                permissions=permissions,
                run_id=run.id,
                dry_run=False,
            )
            executed += 1
            run = self._resolve_run(process_id, run.id)
            self._trace(
                run,
                f"{proposal.tool_name} → {inv.status}",
                kind="act" if inv.status in {"executed", "replayed"} else "error",
                tool=proposal.tool_name,
                step=curr_idx,
            )

            if inv.status in {"denied", "failed"}:
                meta = self._run_meta(run)
                last = list(meta.get("recent_failures") or [])
                last.append(
                    {
                        "tool": proposal.tool_name,
                        "status": inv.status,
                        "at": utcnow().isoformat(),
                    }
                )
                meta["recent_failures"] = last[-8:]
                failed_tool = proposal.tool_name
                same = [f for f in meta["recent_failures"] if f.get("tool") == failed_tool]
                meta["stuck_strikes"] = len(same)
                run.metadata = meta

                # After repeated failures, auto-block that tool so the plan can continue.
                if len(same) >= 3 and failed_tool in TOOL_CATALOG:
                    blocked = set(meta.get("blocked_tools") or [])
                    blocked.add(failed_tool)
                    meta["blocked_tools"] = sorted(blocked)
                    meta["recent_failures"] = [
                        f for f in meta["recent_failures"] if f.get("tool") != failed_tool
                    ]
                    meta["stuck_strikes"] = 0
                    run.metadata = meta

                checklist = self._step_checklist(
                    step=steps[curr_idx] if curr_idx < len(steps) else None,
                    run=run,
                )
                blocked_now = set(self._operator_state(run).get("blocked_tools") or [])
                rem = [
                    t
                    for t in (checklist.get("remaining") or [])
                    if t != failed_tool and t not in blocked_now
                ]

                # Keep the run executing so recovery tools can still run.
                if run.status in {
                    ProcessRunStatus.PAUSED,
                    ProcessRunStatus.AWAITING_APPROVAL,
                } and rem:
                    run.status = ProcessRunStatus.EXECUTING
                    run.pause_reason = None
                    run.updated_at = utcnow()

                # Always auto-block the failed tool so propose won't loop it.
                if failed_tool in TOOL_CATALOG:
                    blocked_now.add(failed_tool)
                    meta["blocked_tools"] = sorted(blocked_now)
                    run.metadata = meta

                if rem and executed < max_steps:
                    alt_name = rem[0]
                    args2: dict[str, Any] = {}
                    self._ensure_tool_args(alt_name, args2, process_id=process_id, run=run)
                    inv2 = self.invoke_tool(
                        process_id,
                        tool_name=alt_name,
                        arguments=args2,
                        user_id=user_id,
                        correlation_id=correlation_id,
                        permissions=permissions,
                        run_id=run.id,
                        dry_run=False,
                    )
                    executed += 1
                    run = self._resolve_run(process_id, run.id)
                    if inv2.status in {"executed", "replayed", "dry_run"}:
                        self._apply_step_progress(
                            run,
                            steps=steps,
                            curr_idx=curr_idx,
                            proposal=ToolProposalOutput(
                                tool_name=alt_name,
                                arguments=args2,
                                rationale=f"Recovered after {failed_tool} failure → {alt_name}",
                            ),
                            invocation_status=inv2.status,
                        )
                        continue
                    # Recovery tool also failed — keep looping to propose another tool.
                    continue

                if checklist.get("complete"):
                    self._apply_step_progress(
                        run,
                        steps=steps,
                        curr_idx=curr_idx,
                        proposal=ToolProposalOutput(
                            tool_name="__noop__",
                            arguments={},
                            rationale=f"Skipping failed {failed_tool}; step outcomes met",
                            next_step_index=curr_idx + 1,
                        ),
                        invocation_status="executed",
                    )
                    continue

                if len(same) >= 3 and not rem:
                    run.status = ProcessRunStatus.PAUSED
                    run.pause_reason = (
                        f"Stuck watchdog: {failed_tool} failed/denied repeatedly "
                        "and no alternate remain."
                    )
                    run.updated_at = utcnow()
                    break
                # Soft failure: keep advancing proposals instead of ending the run.
                continue

            if run.status in {
                ProcessRunStatus.PAUSED,
                ProcessRunStatus.AWAITING_APPROVAL,
                ProcessRunStatus.BLOCKED,
                ProcessRunStatus.FAILED,
            }:
                break
            if inv.status in {"executed", "replayed", "dry_run"}:
                meta = self._run_meta(run)
                if inv.status == "replayed":
                    replays = list(meta.get("recent_replays") or [])
                    replays.append(
                        {"tool": proposal.tool_name, "at": utcnow().isoformat()}
                    )
                    meta["recent_replays"] = replays[-12:]
                    same_replay = [
                        r for r in meta["recent_replays"] if r.get("tool") == proposal.tool_name
                    ]
                    if len(same_replay) >= 2:
                        blocked = set(meta.get("blocked_tools") or [])
                        if proposal.tool_name in TOOL_CATALOG:
                            blocked.add(proposal.tool_name)
                        meta["blocked_tools"] = sorted(blocked)
                        run.metadata = meta
                        # Skip applying progress for a pure replay loop; pick another tool.
                        continue
                    run.metadata = meta
                if meta.get("stuck_strikes"):
                    meta["stuck_strikes"] = 0
                    meta["recent_failures"] = []
                    run.metadata = meta
                self._apply_step_progress(
                    run,
                    steps=steps,
                    curr_idx=curr_idx,
                    proposal=proposal,
                    invocation_status=inv.status,
                )

        if steps and int(getattr(run, "current_step_index", 0) or 0) >= len(steps):
            if run.status == ProcessRunStatus.EXECUTING:
                run.status = ProcessRunStatus.COMPLETED
                run.pause_reason = None
                run.updated_at = utcnow()
                self._trace(run, "Finished the process. Every plan step is done.", kind="done")

        from app.database.persist_helpers import persist_if_postgres
        from app.services.workload import recompute_organization_workload

        persist_if_postgres(self.store, "process_runs", run.id)
        if run.status in {
            ProcessRunStatus.COMPLETED,
            ProcessRunStatus.CANCELLED,
            ProcessRunStatus.FAILED,
        }:
            recompute_organization_workload(self.organization_id)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="execution.advanced",
            resource_type="process_run",
            resource_id=run.id,
            correlation_id=correlation_id,
            payload={"tools_executed": executed, "status": run.status.value},
        )
        return self.get_execution(process_id, run_id=run.id)

    def resume_execution(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        run = self._resolve_run(process_id, run_id)
        if run.status not in {
            ProcessRunStatus.PAUSED,
            ProcessRunStatus.BLOCKED,
            ProcessRunStatus.AWAITING_APPROVAL,
        }:
            raise ConflictError("Process run is not resumable", code="RUN_NOT_RESUMABLE")
        run.status = ProcessRunStatus.EXECUTING
        run.pause_reason = None
        run.updated_at = utcnow()
        from app.database.persist_helpers import persist_if_postgres

        persist_if_postgres(self.store, "process_runs", run.id)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="execution.resumed",
            resource_type="process_run",
            resource_id=run.id,
            correlation_id=correlation_id,
        )
        return self.get_execution(process_id, run_id=run.id)

    def pause_execution(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        run_id: UUID | None = None,
        reason: str = "Paused by operator",
    ) -> dict[str, Any]:
        run = self._resolve_run(process_id, run_id)
        if run.status not in {
            ProcessRunStatus.EXECUTING,
            ProcessRunStatus.DRAFT,
            ProcessRunStatus.APPROVED,
        }:
            raise ConflictError(
                f"Process run cannot be paused from status {run.status.value}",
                code="RUN_NOT_PAUSABLE",
            )
        run.status = ProcessRunStatus.PAUSED
        run.pause_reason = reason
        run.updated_at = utcnow()
        from app.database.persist_helpers import persist_if_postgres

        persist_if_postgres(self.store, "process_runs", run.id)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="execution.paused",
            resource_type="process_run",
            resource_id=run.id,
            correlation_id=correlation_id,
            payload={"reason": reason},
        )
        return self.get_execution(process_id, run_id=run.id)

    def cancel_execution(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        run_id: UUID | None = None,
        reason: str = "Cancelled by operator",
    ) -> dict[str, Any]:
        run = self._resolve_run(process_id, run_id)
        if run.status in {ProcessRunStatus.COMPLETED, ProcessRunStatus.CANCELLED}:
            raise ConflictError("Process run is already terminal", code="RUN_ALREADY_TERMINAL")
        run.status = ProcessRunStatus.CANCELLED
        run.pause_reason = reason
        run.updated_at = utcnow()
        from app.database.persist_helpers import persist_if_postgres
        from app.services.workload import recompute_organization_workload

        persist_if_postgres(self.store, "process_runs", run.id)
        recompute_organization_workload(self.organization_id)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="execution.cancelled",
            resource_type="process_run",
            resource_id=run.id,
            correlation_id=correlation_id,
            payload={"reason": reason},
        )
        return self.get_execution(process_id, run_id=run.id)

    def reset_execution(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        run = self._resolve_run(process_id, run_id)
        run.status = ProcessRunStatus.DRAFT
        run.current_step_index = 0
        run.pause_reason = None
        run.updated_at = utcnow()
        from app.database.persist_helpers import persist_if_postgres

        persist_if_postgres(self.store, "process_runs", run.id)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="execution.reset",
            resource_type="process_run",
            resource_id=run.id,
            correlation_id=correlation_id,
        )
        return self.get_execution(process_id, run_id=run.id)

    def get_execution_summary_report(
        self, process_id: UUID, *, run_id: UUID | None = None
    ) -> dict[str, Any]:
        state = self.get_execution(process_id, run_id=run_id)
        proc = self.processes.get(process_id)
        run = self._resolve_run(process_id, run_id)
        version = self.processes.get_version(process_id, run.process_version_id)
        plan = version.plan_snapshot or {}
        invocations = state.get("tool_invocations") or []
        successful_tools = [i for i in invocations if i.get("status") in {"executed", "replayed"}]
        failed_tools = [i for i in invocations if i.get("status") in {"failed", "denied"}]

        return {
            "process_id": process_id,
            "process_name": proc.name,
            "process_run_id": run.id,
            "status": run.status.value,
            "dry_run": bool(getattr(run, "dry_run", False)),
            "plan_goal": plan.get("goal", ""),
            "steps_total": len(plan.get("steps", [])),
            "steps_completed": int(getattr(run, "current_step_index", 0) or 0),
            "tools_invoked_total": len(invocations),
            "tools_successful": len(successful_tools),
            "tools_failed": len(failed_tools),
            "plan_snapshot_hash": getattr(run, "plan_snapshot_hash", None),
            "risk_snapshot_hash": getattr(run, "risk_snapshot_hash", None),
            "approval_id": (
                str(getattr(run, "approval_id", None))
                if getattr(run, "approval_id", None)
                else None
            ),
            "generated_documents_count": len(state.get("generated_documents", [])),
            "emails_count": len(state.get("email_outbox", [])),
            "calendar_events_count": len(state.get("calendar_events", [])),
            "tasks_count": len(state.get("tasks", [])),
            "notifications_count": len(state.get("notifications", [])),
            "invocations": invocations,
            "generated_at": utcnow().isoformat(),
        }

    def invoke_tool(
        self,
        process_id: UUID,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: UUID,
        correlation_id: str | None,
        permissions: frozenset[str],
        run_id: UUID | None = None,
        dry_run: bool | None = None,
    ) -> ToolInvocation:
        run = self._resolve_run(process_id, run_id)
        args = dict(arguments or {})
        self._ensure_tool_args(tool_name, args, process_id=process_id, run=run)
        use_dry = bool(dry_run if dry_run is not None else getattr(run, "dry_run", False))
        context = ToolContext(
            organization_id=self.organization_id,
            process_id=process_id,
            process_run_id=run.id,
            process_version_id=run.process_version_id,
            actor_user_id=user_id,
            correlation_id=correlation_id,
            permissions=permissions,
            plan_snapshot_hash=getattr(run, "plan_snapshot_hash", None),
            risk_snapshot_hash=getattr(run, "risk_snapshot_hash", None),
            approval_id=getattr(run, "approval_id", None),
            allowed_tools=list(getattr(run, "allowed_tools", None) or list(TOOL_CATALOG.keys())),
            dry_run=use_dry,
            provider_mode="live",
        )
        invocation = self.gateway.invoke(
            tool_name=tool_name,
            arguments=args,
            context=context,
        )
        if invocation.error and invocation.status in {"denied", "failed"}:
            code = invocation.error.code.value
            # Soft-fail optional lookups — do not freeze the whole plan.
            soft_fail_tools = {
                "company.manager_lookup",
                "company.employee_lookup",
                "supplier.contact_lookup",
                "supplier.approved_status",
                "policy.search",
                "document.search",
            }
            if tool_name in soft_fail_tools or tool_name == "notification.send":
                run.updated_at = utcnow()
            elif code in {"APPROVAL_REQUIRED", "MISSING_INFORMATION"}:
                run.status = ProcessRunStatus.PAUSED
                run.pause_reason = invocation.error.message
                run.updated_at = utcnow()
            elif code == "PROVIDER_FAILURE" and invocation.error.retryable:
                run.status = ProcessRunStatus.PAUSED
                run.pause_reason = f"Recoverable integration failure: {invocation.error.message}"
                run.updated_at = utcnow()
        elif (
            invocation.status == "executed"
            and invocation.result
            and invocation.result.data.get("checkpoint")
        ):
            run.status = ProcessRunStatus.AWAITING_APPROVAL
            run.pause_reason = "Additional approval requested"
            run.updated_at = utcnow()
        elif invocation.status in {"executed", "replayed", "dry_run"}:
            run.updated_at = utcnow()
            self.store.run_events.setdefault(run.id, []).append(
                {
                    "type": "tool.completed",
                    "tool": tool_name,
                    "status": invocation.status,
                    "at": utcnow().isoformat(),
                    "summary": self._invocation_summary(invocation),
                }
            )
        from app.database.persist_helpers import persist_if_postgres

        persist_if_postgres(self.store, "process_runs", run.id)
        return invocation

    def get_execution(self, process_id: UUID, *, run_id: UUID | None = None) -> dict[str, Any]:
        self.processes.get(process_id)
        run = self._resolve_run(process_id, run_id)
        invocations = [
            ToolInvocation.model_validate(v)
            for v in self.store.tool_invocations.values()
            if v.get("organization_id") == str(self.organization_id)
            and v.get("process_run_id") == str(run.id)
        ]
        invocations.sort(key=lambda i: i.created_at or utcnow())
        state = ExecutionState(
            process_id=process_id,
            process_run_id=run.id,
            status=run.status.value,
            current_step_index=int(getattr(run, "current_step_index", 0) or 0),
            pause_reason=getattr(run, "pause_reason", None),
            dry_run=bool(getattr(run, "dry_run", False)),
            plan_snapshot_hash=getattr(run, "plan_snapshot_hash", None),
            risk_snapshot_hash=getattr(run, "risk_snapshot_hash", None),
            approval_id=getattr(run, "approval_id", None),
            tool_invocations=invocations,
            human_checkpoints=[
                i.result.data.get("reason", "checkpoint")
                for i in invocations
                if i.result and i.result.data.get("checkpoint")
            ],
            stop_conditions=[c for c in [getattr(run, "pause_reason", None)] if c],
        )
        return {
            "process_id": process_id,
            "process_run_id": run.id,
            "status": state.status,
            "dry_run": state.dry_run,
            "current_step_index": state.current_step_index,
            "pause_reason": state.pause_reason,
            "plan_snapshot_hash": state.plan_snapshot_hash,
            "risk_snapshot_hash": state.risk_snapshot_hash,
            "approval_id": state.approval_id,
            "tool_invocations": [i.model_dump(mode="json") for i in invocations],
            "human_checkpoints": state.human_checkpoints,
            "stop_conditions": state.stop_conditions,
            "available_tools": list(TOOL_CATALOG.keys()),
            "email_outbox": self._recent_emails(limit=10),
            "generated_documents": self._merge_artifacts(
                self._artifacts_from_invocations(invocations, "document.generate"),
                self._store_artifacts(
                    getattr(self.store, "generated_documents", {}) or {}, process_id
                ),
            ),
            "calendar_events": self._merge_artifacts(
                self._artifacts_from_invocations(invocations, "calendar.create_event"),
                self._store_artifacts(self.store.calendar_events, process_id),
            ),
            "tasks": self._merge_artifacts(
                self._artifacts_from_invocations(invocations, "task.assign"),
                self._store_artifacts(getattr(self.store, "tasks", {}) or {}, process_id),
            ),
            "notifications": self._merge_artifacts(
                self._artifacts_from_invocations(invocations, "notification.send"),
                self._store_artifacts(self.store.notifications, process_id),
            ),
            "execution_intelligence": self._execution_intelligence(process_id, run),
            "playbook": self._build_playbook(process_id, run),
            "scorecard": self._build_scorecard(process_id, run),
            "operator": self._operator_state(run),
            "agent_activity": list(self._run_meta(run).get("agent_activity") or [])[-40:],
        }

    def _trace(
        self,
        run: Any,
        message: str,
        *,
        kind: str = "note",
        tool: str | None = None,
        step: int | None = None,
    ) -> None:
        meta = self._run_meta(run)
        trail = list(meta.get("agent_activity") or [])
        trail.append(
            {
                "at": utcnow().isoformat(),
                "kind": kind,
                "message": (message or "").strip()[:400],
                "tool": tool,
                "step": step,
            }
        )
        meta["agent_activity"] = trail[-60:]
        run.metadata = meta

    def _run_meta(self, run: Any) -> dict[str, Any]:
        meta = getattr(run, "metadata", None)
        if not isinstance(meta, dict):
            meta = {}
            run.metadata = meta
        return meta

    def _operator_state(self, run: Any) -> dict[str, Any]:
        meta = self._run_meta(run)
        return {
            "guidance": meta.get("operator_guidance") or "",
            "blocked_tools": list(meta.get("blocked_tools") or []),
            "skipped_proposals": list(meta.get("skipped_proposals") or [])[-10:],
            "guidance_history": list(meta.get("guidance_history") or [])[-8:],
            "email_guard_enabled": bool(meta.get("email_guard_enabled", True)),
            "stuck_strikes": int(meta.get("stuck_strikes") or 0),
        }

    def steer_execution(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        guidance: str,
        block_tools: list[str] | None = None,
        unblock_tools: list[str] | None = None,
        email_guard_enabled: bool | None = None,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Operator guidance that shapes the next proposals."""
        run = self._resolve_run(process_id, run_id)
        meta = self._run_meta(run)
        text = (guidance or "").strip()
        if text:
            meta["operator_guidance"] = text[:2000]
            history = list(meta.get("guidance_history") or [])
            history.append(
                {
                    "at": utcnow().isoformat(),
                    "user_id": str(user_id),
                    "guidance": text[:500],
                }
            )
            meta["guidance_history"] = history[-20:]
        blocked = set(meta.get("blocked_tools") or [])
        for name in block_tools or []:
            if name in TOOL_CATALOG:
                blocked.add(name)
        for name in unblock_tools or []:
            blocked.discard(name)
        meta["blocked_tools"] = sorted(blocked)
        if email_guard_enabled is not None:
            meta["email_guard_enabled"] = bool(email_guard_enabled)
        run.metadata = meta
        run.updated_at = utcnow()
        from app.database.persist_helpers import persist_if_postgres

        persist_if_postgres(self.store, "process_runs", run.id)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="execution.steered",
            resource_type="process_run",
            resource_id=run.id,
            correlation_id=correlation_id,
            payload={
                "guidance": text[:200],
                "blocked_tools": meta["blocked_tools"],
                "email_guard_enabled": meta.get("email_guard_enabled", True),
            },
        )
        return self.get_execution(process_id, run_id=run.id)

    def skip_proposal(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        tool_name: str,
        reason: str | None = None,
        advance_step: bool = False,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Reject the current proposed tool and optionally advance the plan step."""
        run = self._resolve_run(process_id, run_id)
        meta = self._run_meta(run)
        skips = list(meta.get("skipped_proposals") or [])
        skips.append(
            {
                "at": utcnow().isoformat(),
                "tool_name": tool_name,
                "reason": (reason or "Operator skipped").strip()[:500],
                "step_index": int(getattr(run, "current_step_index", 0) or 0),
            }
        )
        meta["skipped_proposals"] = skips[-30:]
        # Temporarily block this tool so the next propose picks something else.
        blocked = set(meta.get("blocked_tools") or [])
        if tool_name in TOOL_CATALOG:
            blocked.add(tool_name)
        meta["blocked_tools"] = sorted(blocked)
        run.metadata = meta
        if advance_step:
            version = self.processes.get_version(process_id, run.process_version_id)
            steps = (version.plan_snapshot or {}).get("steps") or []
            curr = int(getattr(run, "current_step_index", 0) or 0)
            run.current_step_index = min(curr + 1, len(steps) if steps else curr + 1)
        run.updated_at = utcnow()
        from app.database.persist_helpers import persist_if_postgres

        persist_if_postgres(self.store, "process_runs", run.id)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="execution.proposal_skipped",
            resource_type="process_run",
            resource_id=run.id,
            correlation_id=correlation_id,
            payload={"tool_name": tool_name, "reason": reason, "advance_step": advance_step},
        )
        return self.get_execution(process_id, run_id=run.id)

    def _build_playbook(self, process_id: UUID, run: Any) -> list[dict[str, Any]]:
        version = self.processes.get_version(process_id, run.process_version_id)
        steps = (version.plan_snapshot or {}).get("steps") or []
        curr_idx = int(getattr(run, "current_step_index", 0) or 0)
        executed = self._successful_tool_names(run)
        playbook: list[dict[str, Any]] = []
        for idx, step in enumerate(steps):
            checklist = self._step_checklist(step=step, run=run)
            status = "pending"
            if idx < curr_idx:
                status = "done"
            elif idx == curr_idx:
                status = "complete" if checklist.get("complete") else "active"
            playbook.append(
                {
                    "index": idx,
                    "title": step.get("title") or f"Step {idx + 1}",
                    "description": (step.get("description") or "")[:240],
                    "action_type": step.get("action_type"),
                    "status": status,
                    "step_kind": checklist.get("step_kind"),
                    "remaining": checklist.get("remaining") if idx == curr_idx else [],
                    "allowed_tools": list(step.get("allowed_tools") or []),
                    "success_criteria": list(step.get("success_criteria") or []),
                    "tools_done_on_step": sorted(
                        set(checklist.get("executed_tools") or []) & executed
                    )
                    if idx == curr_idx
                    else [],
                }
            )
        return playbook

    def _build_scorecard(self, process_id: UUID, run: Any) -> dict[str, Any]:
        rows = self._run_invocation_rows(run)
        ok = [r for r in rows if r.get("status") in {"executed", "replayed"}]
        failed = [r for r in rows if r.get("status") in {"failed", "denied"}]
        replayed = [r for r in rows if r.get("status") == "replayed"]
        by_tool: dict[str, int] = {}
        for r in ok:
            name = str(r.get("tool_name") or "unknown")
            by_tool[name] = by_tool.get(name, 0) + 1
        sent = self._outbound_sent_records(run)
        version = self.processes.get_version(process_id, run.process_version_id)
        steps = (version.plan_snapshot or {}).get("steps") or []
        curr = int(getattr(run, "current_step_index", 0) or 0)
        created = getattr(run, "created_at", None)
        updated = getattr(run, "updated_at", None)
        duration_s = None
        if created and updated:
            try:
                duration_s = max(0, int((updated - created).total_seconds()))
            except Exception:  # noqa: BLE001
                duration_s = None
        return {
            "tools_total": len(rows),
            "tools_successful": len(ok),
            "tools_failed_or_denied": len(failed),
            "tools_replayed": len(replayed),
            "success_rate": round((len(ok) / len(rows)) * 100, 1) if rows else 0.0,
            "unique_tools": len(by_tool),
            "tool_counts": by_tool,
            "email_sends": len([r for r in sent if r["tool"] == "email.send"]),
            "notifications": len([r for r in sent if r["tool"] == "notification.send"]),
            "documents": by_tool.get("document.generate", 0),
            "purchase_orders_submitted": by_tool.get("purchase_order.submit", 0),
            "quotes_requested": by_tool.get("supplier.request_quote", 0),
            "steps_total": len(steps),
            "steps_completed": min(curr, len(steps)),
            "duration_seconds": duration_s,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        }

    def _execution_intelligence(self, process_id: UUID, run: Any) -> dict[str, Any]:
        version = self.processes.get_version(process_id, run.process_version_id)
        steps = (version.plan_snapshot or {}).get("steps") or []
        curr_idx = int(getattr(run, "current_step_index", 0) or 0)
        current_step = steps[curr_idx] if curr_idx < len(steps) else None
        sent = self._outbound_sent_records(run)
        op = self._operator_state(run)
        return {
            "executed_tools": sorted(self._successful_tool_names(run)),
            "outbound_already_sent": sent,
            "step_checklist": self._step_checklist(step=current_step, run=run),
            "email_send_count": len([r for r in sent if r["tool"] == "email.send"]),
            "max_email_send_per_run": 2,
            "plan_step_count": len(steps),
            "current_step_title": (current_step or {}).get("title") if current_step else None,
            "operator_guidance": op.get("guidance") or "",
            "blocked_tools": op.get("blocked_tools") or [],
            "email_guard_enabled": op.get("email_guard_enabled", True),
            "next_recommended": (self._step_checklist(step=current_step, run=run).get("remaining") or [None])[0],
        }

    def _artifacts_from_invocations(
        self, invocations: list[Any], tool_name: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for inv in invocations:
            if getattr(inv, "tool_name", None) != tool_name:
                continue
            if inv.status not in {"executed", "replayed"}:
                continue
            data = (inv.result.data if inv.result else None) or {}
            if isinstance(data, dict) and data:
                items.append(dict(data))
        return items

    def _store_artifacts(
        self, collection: dict[Any, Any], process_id: UUID, *, limit: int = 40
    ) -> list[dict[str, Any]]:
        org = str(self.organization_id)
        pid = str(process_id)
        items: list[dict[str, Any]] = []
        for raw in collection.values():
            if not isinstance(raw, dict):
                continue
            if str(raw.get("organization_id")) != org:
                continue
            if str(raw.get("process_id") or "") != pid:
                continue
            items.append(dict(raw))
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return items[:limit]

    def _merge_artifacts(
        self, primary: list[dict[str, Any]], secondary: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for item in primary + secondary:
            key = str(item.get("id") or item.get("idempotency_key") or id(item))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out[:40]

    def compare_quotations(
        self,
        process_id: UUID,
        *,
        quotation_ids: list[str],
        explain: bool = True,
    ) -> dict[str, Any]:
        self.processes.get(process_id)
        quotes = []
        for qid in quotation_ids:
            raw = self.store.quotations.get(UUID(qid))
            if raw is None or raw.get("organization_id") != str(self.organization_id):
                continue
            quotes.append(normalize_quotation(raw))
        result = compare_quotations(quotes)
        if explain and result.winner_quotation_id:
            result.llm_used = False
            result.explanation = (
                result.explanation + " Scoring is deterministic across cost, delivery, warranty, "
                "payment terms, supplier risk, and policy compliance."
            )
        return result.model_dump(mode="json")

    def list_quotations(self, process_id: UUID) -> list[dict[str, Any]]:
        self.processes.get(process_id)
        return [
            q
            for q in self.store.quotations.values()
            if q.get("organization_id") == str(self.organization_id)
        ]

    def list_purchase_orders(self, process_id: UUID) -> list[dict[str, Any]]:
        self.processes.get(process_id)
        return [
            p
            for p in self.store.purchase_orders.values()
            if p.get("organization_id") == str(self.organization_id)
        ]

    def _supplier_name(self, supplier_id: Any) -> str:
        if not supplier_id:
            return "Supplier"
        try:
            sid = UUID(str(supplier_id))
            sup = SupplierRepository(self.organization_id).get(sid)
            return sup.name
        except Exception:
            return str(supplier_id)

    def _resolve_run(self, process_id: UUID, run_id: UUID | None) -> Any:
        if run_id is not None:
            return self.runs.get(run_id)
        runs = [r for r in self.runs.list_all() if r.process_id == process_id]
        if not runs:
            raise NotFoundError("Execution run not found")
        return max(runs, key=lambda r: r.updated_at)

    def _latest_risk(self, process_id: UUID) -> dict[str, Any] | None:
        records = [
            r
            for r in self.store.risk_results.values()
            if r.organization_id == self.organization_id and r.process_id == process_id
        ]
        if not records:
            return None
        latest = max(records, key=lambda r: r.updated_at)
        snap = dict(latest.result_snapshot)
        snap["valid"] = latest.valid
        return snap

    def _latest_approved(self, process_id: UUID) -> Any:
        approvals = [
            a
            for a in self.store.approvals.values()
            if a.organization_id == self.organization_id
            and a.process_id == process_id
            and a.status == ApprovalStatus.APPROVED
        ]
        if not approvals:
            return None
        return max(approvals, key=lambda a: a.updated_at)

    def _latest_allocation(self, process_id: UUID) -> dict[str, Any] | None:
        records: list[Any] = []
        for r in getattr(self.store, "allocations", {}).values():
            if hasattr(r, "organization_id"):
                if r.organization_id == self.organization_id and r.process_id == process_id:
                    records.append(r)
            elif isinstance(r, dict):
                if r.get("organization_id") == str(self.organization_id) and r.get(
                    "process_id"
                ) == str(process_id):
                    records.append(r)
        if not records:
            return None

        def _updated(r: Any) -> Any:
            return (
                getattr(r, "updated_at", None)
                or (r.get("updated_at") if isinstance(r, dict) else None)
                or utcnow()
            )

        latest = max(records, key=_updated)
        if isinstance(latest, dict):
            return latest.get("result_snapshot") or latest
        snap = getattr(latest, "result_snapshot", None) or {}
        if isinstance(snap, dict) and snap:
            return snap
        return {"assignments": [], "status": getattr(latest, "status", None)}

    def _directory_context(self) -> dict[str, Any]:
        employees = [
            {
                "id": str(e.id),
                "full_name": e.full_name,
                "email": e.email,
                "is_manager": e.is_manager,
                "role_code": e.role_code,
            }
            for e in EmployeeRepository(self.organization_id).list_all()
            if e.status == "active"
        ][:40]
        suppliers = [
            {
                "id": str(s.id),
                "name": s.name,
                "approval_status": s.approval_status,
            }
            for s in SupplierRepository(self.organization_id).list_all()
            if s.status == "active"
        ][:30]
        contacts = [
            {
                "id": str(c.id),
                "supplier_id": str(c.supplier_id),
                "full_name": c.full_name,
                "email": c.email,
            }
            for c in SupplierContactRepository(self.organization_id).list_all()
        ][:40]
        return {"employees": employees, "suppliers": suppliers, "supplier_contacts": contacts}

    def _assignment_dicts(self, allocation: dict[str, Any] | None) -> list[dict[str, Any]]:
        raw = (allocation or {}).get("assignments") or []
        out: list[dict[str, Any]] = []
        for a in raw:
            if isinstance(a, dict):
                out.append(a)
            elif hasattr(a, "model_dump"):
                out.append(a.model_dump(mode="json"))
            else:
                out.append(
                    {
                        "step_id": getattr(a, "step_id", None),
                        "requirement": getattr(a, "requirement", None),
                        "resource_id": getattr(a, "resource_id", None),
                        "resource_type": getattr(a, "resource_type", None),
                        "display_name": getattr(a, "display_name", None),
                        "metadata": getattr(a, "metadata", None) or {},
                    }
                )
        return out

    def _email_for_assignment(self, assignment: dict[str, Any]) -> str | None:
        """Resolve a real mailbox from an Agent 2 assignment."""
        meta = assignment.get("metadata") or {}
        if isinstance(meta, dict):
            email = (meta.get("email") or "").strip()
            if email and "@" in email:
                return email.lower()

        rid = str(assignment.get("resource_id") or "").strip()
        rtype = str(assignment.get("resource_type") or "").lower()
        if not rid:
            return None

        directory = self._directory_context()
        if rtype in {"employee", "manager", "approval_authority"}:
            for e in directory.get("employees") or []:
                if e.get("id") == rid and e.get("email"):
                    return str(e["email"]).lower()
            try:
                emp = EmployeeRepository(self.organization_id).get(UUID(rid))
                if emp.email:
                    return emp.email.lower()
            except Exception:
                pass

        if rtype == "supplier_contact":
            for c in directory.get("supplier_contacts") or []:
                if c.get("id") == rid and c.get("email"):
                    return str(c["email"]).lower()
            try:
                contact = next(
                    (
                        c
                        for c in SupplierContactRepository(self.organization_id).list_all()
                        if str(c.id) == rid
                    ),
                    None,
                )
                if contact and contact.email:
                    return contact.email.lower()
            except Exception:
                pass

        if rtype == "supplier":
            for c in directory.get("supplier_contacts") or []:
                if c.get("supplier_id") == rid and c.get("email"):
                    return str(c["email"]).lower()
            try:
                contacts = SupplierContactRepository(self.organization_id).list_all(
                    supplier_id=UUID(rid)
                )
                for c in contacts:
                    if c.email:
                        return c.email.lower()
            except Exception:
                pass

        # Last resort: resource_id itself is an email
        if "@" in rid:
            return rid.lower()
        return None

    def _resolve_email_recipient_from_allocation(
        self,
        *,
        process_id: UUID,
        run: Any,
        current_step: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Pick the Agent 2–allocated person/supplier contact who should receive email
        for the current execution step.
        """
        allocation = self._latest_allocation(process_id) or {}
        assignments = self._assignment_dicts(allocation)
        if not assignments:
            return None

        if current_step is None:
            try:
                version = self.processes.get_version(process_id, run.process_version_id)
                steps = (version.plan_snapshot or {}).get("steps") or []
                idx = int(getattr(run, "current_step_index", 0) or 0)
                current_step = steps[idx] if idx < len(steps) else None
            except Exception:
                current_step = None

        step_id = str((current_step or {}).get("step_id") or (current_step or {}).get("id") or "")
        step_text = " ".join(
            str(x)
            for x in [
                (current_step or {}).get("title"),
                (current_step or {}).get("description"),
                " ".join((current_step or {}).get("required_resources") or []),
            ]
            if x
        ).lower()

        people_types = {
            "supplier_contact",
            "employee",
            "manager",
            "approval_authority",
            "supplier",
        }
        contactish = (
            "contact",
            "email",
            "vendor",
            "supplier",
            "rfq",
            "quote",
            "notify",
            "message",
            "reach",
        )
        peopleish = (
            "approver",
            "approval",
            "manager",
            "attention",
            "employee",
            "buyer",
            "owner",
            "jordan",
            "authority",
        )

        scored: list[tuple[float, dict[str, Any]]] = []
        for a in assignments:
            rtype = str(a.get("resource_type") or "").lower()
            if rtype not in people_types:
                continue
            req = str(a.get("requirement") or "").lower()
            score = 0.0
            if step_id and str(a.get("step_id") or "") == step_id:
                score += 5.0
            if any(k in req for k in contactish):
                score += 3.0
            if any(k in req for k in peopleish):
                score += 2.5
            if any(k in step_text for k in contactish) and rtype in {
                "supplier_contact",
                "supplier",
            }:
                score += 2.0
            if any(k in step_text for k in peopleish) and rtype in {
                "employee",
                "manager",
                "approval_authority",
            }:
                score += 2.0
            if rtype == "supplier_contact":
                score += 1.5
            if rtype in {"employee", "manager", "approval_authority"}:
                score += 1.0
            if rtype == "supplier":
                score += 0.5
            email = self._email_for_assignment(a)
            if not email:
                continue
            scored.append((score, {**a, "_resolved_email": email}))

        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]
        email = best["_resolved_email"]
        return {
            "to_employee_id": email,  # adapter accepts raw email
            "email": email,
            "resource_id": best.get("resource_id"),
            "resource_type": best.get("resource_type"),
            "display_name": best.get("display_name"),
            "requirement": best.get("requirement"),
            "step_id": best.get("step_id"),
            "reason": (
                f"Agent 2 allocated {best.get('display_name')} "
                f"for '{best.get('requirement')}'"
            ),
        }

    def _allowed_tools_from_plan(self, plan_snapshot: dict[str, Any]) -> list[str]:
        catalog = set(TOOL_CATALOG.keys())
        step_tools: set[str] = set()
        for step in plan_snapshot.get("steps") or []:
            for t in step.get("allowed_tools") or []:
                if t in catalog:
                    step_tools.add(t)
        if not step_tools:
            return sorted(catalog)

        allowed = set(step_tools)
        # Read-only tools are always safe to keep available.
        for name, tool in TOOL_CATALOG.items():
            if tool.side_effect_status.value == "none":
                allowed.add(name)
        # Draft / commercial progression helpers — not free-form email spam.
        for name in (
            "email.create_draft",
            "supplier.request_quote",
            "supplier.collect_quote",
            "quotation.compare",
            "purchase_order.create_draft",
            "purchase_order.submit",
            "document.generate",
            "calendar.create_event",
            "task.assign",
            "notification.send",
            "approval.request",
        ):
            if name in catalog:
                allowed.add(name)
        # Only keep email.send when the plan itself named it.
        if "email.send" in step_tools and "email.send" in catalog:
            allowed.add("email.send")
        return sorted(allowed)

    def _run_invocation_rows(self, run: Any) -> list[dict[str, Any]]:
        return [
            v
            for v in self.store.tool_invocations.values()
            if v.get("organization_id") == str(self.organization_id)
            and v.get("process_run_id") == str(run.id)
        ]

    def _successful_tool_names(self, run: Any) -> set[str]:
        return {
            str(v.get("tool_name"))
            for v in self._run_invocation_rows(run)
            if v.get("status") in {"executed", "replayed"}
        }

    def _stable_idempotency_key(
        self, *, run: Any, tool_name: str, purpose: str
    ) -> str:
        step = int(getattr(run, "current_step_index", 0) or 0)
        digest = hashlib.sha256(
            f"{run.id}:{step}:{tool_name}:{purpose}".encode()
        ).hexdigest()
        return f"{tool_name.split('.')[-1]}-{digest[:24]}"

    def _normalize_recipient(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def _outbound_sent_records(self, run: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for row in self._run_invocation_rows(run):
            tool = str(row.get("tool_name") or "")
            if tool not in {
                "email.send",
                "notification.send",
                "supplier.request_quote",
                "purchase_order.submit",
            }:
                continue
            if row.get("status") not in {"executed", "replayed"}:
                continue
            args = row.get("arguments") or {}
            recipient = (
                args.get("to_employee_id")
                or args.get("user_id")
                or args.get("contact_email")
                or args.get("supplier_id")
            )
            records.append(
                {
                    "tool": tool,
                    "recipient": self._normalize_recipient(recipient),
                    "subject": str(args.get("subject") or args.get("title") or "")[:120],
                    "status": row.get("status"),
                    "idempotency_key": args.get("idempotency_key"),
                }
            )
        return records

    def _outbound_block_reason(
        self, tool_name: str, args: dict[str, Any], *, run: Any
    ) -> str | None:
        op = self._operator_state(run)
        if tool_name in set(op.get("blocked_tools") or []):
            return f"{tool_name} blocked by operator"
        if tool_name == "email.send" and not op.get("email_guard_enabled", True):
            # Guard disabled: still prevent exact same-key spam via gateway, but allow new sends.
            sent = self._outbound_sent_records(run)
            email_sends = [r for r in sent if r["tool"] == "email.send"]
            recipient = self._normalize_recipient(args.get("to_employee_id"))
            if recipient and any(r["recipient"] == recipient for r in email_sends):
                return (
                    f"email.send blocked: already emailed {recipient} in this run"
                )
            return None
        sent = self._outbound_sent_records(run)
        email_sends = [r for r in sent if r["tool"] == "email.send"]
        if tool_name == "email.send":
            if len(email_sends) >= 2:
                return "email.send blocked: this run already sent two confirmation emails"
            recipient = self._normalize_recipient(args.get("to_employee_id"))
            if recipient and any(r["recipient"] == recipient for r in email_sends):
                return (
                    f"email.send blocked: already emailed {recipient} in this run — "
                    "use document.generate, notification.send, or advance the step"
                )
        if tool_name == "notification.send":
            recipient = self._normalize_recipient(args.get("user_id"))
            notifs = [r for r in sent if r["tool"] == "notification.send"]
            if recipient and any(r["recipient"] == recipient for r in notifs):
                return f"notification.send blocked: already notified {recipient}"
            if len(notifs) >= 2:
                return "notification.send blocked: notification budget for this run is used"
        return None

    def _step_text(self, step: dict[str, Any] | None) -> str:
        if not step:
            return ""
        return " ".join(
            str(x)
            for x in (
                step.get("title"),
                step.get("description"),
                step.get("action_type"),
                " ".join(step.get("allowed_tools") or []),
            )
            if x
        ).lower()

    def _step_checklist(
        self, *, step: dict[str, Any] | None, run: Any
    ) -> dict[str, Any]:
        executed = self._successful_tool_names(run)
        text = self._step_text(step)
        sent = self._outbound_sent_records(run)
        is_rfq = any(
            k in text
            for k in (
                "quote",
                "rfq",
                "quotation",
                "dual quote",
                "request for quote",
            )
        )
        is_order = any(
            k in text
            for k in (
                "purchase order",
                "create po",
                "submit po",
                "order fulfillment",
                "issue purchase",
            )
        ) or bool(re.search(r"\b(po|order)\b", text)) and "quote" not in text
        quotes = [
            q
            for q in self.store.quotations.values()
            if q.get("organization_id") == str(self.organization_id)
            and (
                not getattr(run, "process_id", None)
                or q.get("process_id") in {None, str(getattr(run, "process_id", None))}
            )
        ]
        pos = [
            p
            for p in self.store.purchase_orders.values()
            if p.get("organization_id") == str(self.organization_id)
            and (
                not getattr(run, "process_id", None)
                or p.get("process_id") in {None, str(getattr(run, "process_id", None))}
            )
        ]
        submitted = any(p.get("submitted") for p in pos)
        checklist = {
            "step_kind": "rfq" if is_rfq else "order" if is_order else "general",
            "executed_tools": sorted(executed),
            "email_sends": len([r for r in sent if r["tool"] == "email.send"]),
            "notifications": len([r for r in sent if r["tool"] == "notification.send"]),
            "quotes_collected": len(quotes),
            "po_drafted": any(True for _ in pos),
            "po_submitted": submitted,
            "document_generated": "document.generate" in executed,
            "calendar_created": "calendar.create_event" in executed,
            "task_assigned": "task.assign" in executed,
            "complete": False,
            "remaining": [],
        }
        remaining: list[str] = []
        if is_rfq:
            reqs = [
                r
                for r in self.store.quote_requests.values()
                if r.get("organization_id") == str(self.organization_id)
                and (
                    not getattr(run, "process_id", None)
                    or r.get("process_id")
                    in {None, str(getattr(run, "process_id", None))}
                )
            ]
            if len(reqs) < 2:
                remaining.append("supplier.request_quote")
            if len(quotes) < 2:
                remaining.append("supplier.collect_quote")
            if "quotation.compare" not in executed and len(quotes) >= 2:
                remaining.append("quotation.compare")
            checklist["complete"] = (
                len(reqs) >= 2
                and len(quotes) >= 2
                and "quotation.compare" in executed
            )
        elif is_order:
            if not any(True for _ in pos):
                remaining.append("purchase_order.create_draft")
            if not submitted:
                remaining.append("purchase_order.submit")
            if "document.generate" not in executed:
                remaining.append("document.generate")
            if "calendar.create_event" not in executed:
                remaining.append("calendar.create_event")
            if "task.assign" not in executed:
                remaining.append("task.assign")
            if "notification.send" not in executed and "email.send" not in executed:
                remaining.append("notification.send")
            checklist["complete"] = (
                submitted
                and "document.generate" in executed
                and "calendar.create_event" in executed
                and "task.assign" in executed
                and (
                    "notification.send" in executed
                    or "email.send" in executed
                )
            )
        else:
            action = str((step or {}).get("action_type") or "")
            is_discovery = action in {"collect_info", "discovery"} or any(
                k in text
                for k in (
                    "identify staff",
                    "discover staff",
                    "staff & suppliers",
                    "directory lookup",
                    "supplier lookup",
                )
            )
            allowed = [
                str(t)
                for t in (step or {}).get("allowed_tools") or []
                if isinstance(t, str) and t in TOOL_CATALOG
            ]
            if is_discovery:
                core = [
                    t
                    for t in ("supplier.search", "company.employee_lookup")
                    if not allowed or t in allowed
                ]
                for t in core:
                    if t not in executed:
                        remaining.append(t)
                checklist["step_kind"] = "discovery"
                checklist["complete"] = len(remaining) == 0
                checklist["remaining"] = remaining
                return checklist
            outcome_priority = [
                "supplier.search",
                "supplier.request_quote",
                "supplier.collect_quote",
                "quotation.compare",
                "purchase_order.create_draft",
                "purchase_order.submit",
                "document.generate",
                "calendar.create_event",
                "task.assign",
                "notification.send",
                "email.create_draft",
                "email.send",
                "company.employee_lookup",
                "company.manager_lookup",
                "policy.search",
                "document.search",
            ]
            preferred = [t for t in outcome_priority if t in allowed]
            if not preferred:
                preferred = allowed[:]
            # Deduplicate while preserving order
            seen: set[str] = set()
            ordered: list[str] = []
            for t in preferred:
                if t not in seen:
                    seen.add(t)
                    ordered.append(t)
            # Cap how many tools a general step needs so runs finish, but never after just one lookup.
            target = ordered[: min(len(ordered), 5)] if ordered else [
                "document.generate",
                "notification.send",
            ]
            for t in target:
                if t not in executed:
                    remaining.append(t)
            checklist["complete"] = len(remaining) == 0
            if not target:
                meaningful = executed & {
                    "document.generate",
                    "notification.send",
                    "task.assign",
                    "calendar.create_event",
                    "email.send",
                    "email.create_draft",
                    "approval.request",
                    "policy.search",
                    "document.search",
                    "company.employee_lookup",
                    "supplier.search",
                }
                checklist["complete"] = bool(meaningful)
                if not meaningful:
                    remaining.append("document.generate")
            checklist["remaining"] = remaining
            return checklist
        checklist["remaining"] = remaining
        return checklist

    def _apply_step_progress(
        self,
        run: Any,
        *,
        steps: list[Any],
        curr_idx: int,
        proposal: ToolProposalOutput,
        invocation_status: str,
    ) -> None:
        if not steps:
            return
        checklist = self._step_checklist(
            step=steps[curr_idx] if curr_idx < len(steps) else None,
            run=run,
        )
        advance_to: int | None = None
        # Never jump more than one plan step at a time.
        if checklist.get("complete") or proposal.tool_name == "__noop__":
            if proposal.next_step_index is not None and proposal.next_step_index > curr_idx:
                advance_to = curr_idx + 1
            elif checklist.get("complete"):
                advance_to = curr_idx + 1
            elif proposal.tool_name == "__noop__":
                advance_to = curr_idx + 1
        elif invocation_status == "replayed" and checklist.get("complete"):
            advance_to = curr_idx + 1

        if advance_to is None:
            return
        run.current_step_index = min(advance_to, len(steps))
        run.updated_at = utcnow()

    def _refine_proposal(
        self,
        proposal: ToolProposalOutput,
        *,
        process_id: UUID,
        run: Any,
        steps: list[Any],
        curr_idx: int,
        allowed: list[str],
    ) -> ToolProposalOutput:
        op = self._operator_state(run)
        blocked = set(op.get("blocked_tools") or [])
        step = steps[curr_idx] if curr_idx < len(steps) else None
        step_tools = [
            str(t)
            for t in (step or {}).get("allowed_tools") or []
            if isinstance(t, str) and t in TOOL_CATALOG
        ]
        if step_tools:
            allowed = [t for t in (allowed or step_tools) if t in step_tools]
        if blocked:
            allowed = [t for t in allowed if t not in blocked]
        checklist = self._step_checklist(
            step=steps[curr_idx] if curr_idx < len(steps) else None,
            run=run,
        )
        executed = set(checklist.get("executed_tools") or [])
        remaining = [t for t in (checklist.get("remaining") or []) if t not in blocked]

        if checklist.get("complete"):
            if curr_idx + 1 >= len(steps):
                return ToolProposalOutput(
                    tool_name="__noop__",
                    arguments={},
                    rationale="All plan steps are complete — finishing the run.",
                    next_step_index=len(steps),
                )
            # Force advance without another outbound mail.
            return ToolProposalOutput(
                tool_name="__noop__",
                arguments={},
                rationale="Current step outcomes are complete — advancing to the next step.",
                next_step_index=curr_idx + 1,
            )

        # Nothing left on this step — move on. Do not borrow tools from later steps.
        if not remaining:
            return ToolProposalOutput(
                tool_name="__noop__",
                arguments={},
                rationale="This step has no remaining work — advancing.",
                next_step_index=curr_idx + 1,
            )

        if proposal.tool_name not in allowed and proposal.tool_name != "__noop__":
            if remaining:
                proposal.tool_name = remaining[0]
                proposal.rationale += " (Coerced to unfinished step outcome)"
            elif allowed:
                proposal.tool_name = allowed[0]
                proposal.rationale += " (Selected fallback tool from allowed catalog)"

        # Unfinished outcomes always beat side work.
        if remaining and proposal.tool_name not in remaining:
            preferred_remaining = [t for t in remaining if t in allowed or t in TOOL_CATALOG]
            if preferred_remaining:
                proposal.tool_name = preferred_remaining[0]
                proposal.rationale = (
                    f"Still need {preferred_remaining[0]} before this step can move on."
                )
                proposal.next_step_index = curr_idx
                proposal.arguments = {}

        # Never re-pick email.send once it already succeeded this run.
        if proposal.tool_name == "email.send" and "email.send" in executed:
            for candidate in remaining + [
                "document.generate",
                "notification.send",
                "task.assign",
                "calendar.create_event",
                "email.create_draft",
            ]:
                if candidate in allowed and candidate not in executed:
                    proposal.tool_name = candidate
                    proposal.rationale += (
                        " (Replaced duplicate email.send with unfinished execution tool)"
                    )
                    proposal.next_step_index = curr_idx
                    break
            else:
                return ToolProposalOutput(
                    tool_name="__noop__",
                    arguments={},
                    rationale="Email already sent for this run — advancing without resending.",
                    next_step_index=curr_idx + 1,
                )

        # Prefer completing commercial outcomes before notifying/emailing.
        if proposal.tool_name in {"email.send", "notification.send"} and remaining:
            preferred = [
                t
                for t in remaining
                if t
                not in {
                    "email.send",
                    "notification.send",
                }
            ]
            if preferred and preferred[0] in allowed:
                proposal.tool_name = preferred[0]
                proposal.rationale += (
                    f" (Deferred outbound mail until {preferred[0]} completes)"
                )
                proposal.next_step_index = curr_idx

        # Cap next_step_index so multi-action steps stay put until checklist is complete.
        if not checklist.get("complete") and proposal.next_step_index is not None:
            if proposal.next_step_index > curr_idx and remaining:
                proposal.next_step_index = curr_idx

        return proposal

    def propose_next_tool(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        run_id: UUID | None = None,
        permissions: frozenset[str],
    ) -> ToolProposalOutput:
        """Intelligently propose the next tool call using Vertex Gemini."""
        run = self._resolve_run(process_id, run_id)
        version = self.processes.get_version(process_id, run.process_version_id)
        plan_dict = version.plan_snapshot or {}
        steps = plan_dict.get("steps", [])
        curr_idx = int(getattr(run, "current_step_index", 0) or 0)
        current_step = steps[curr_idx] if curr_idx < len(steps) else None

        allowed = list(getattr(run, "allowed_tools", None) or list(TOOL_CATALOG.keys()))
        op = self._operator_state(run)
        blocked = set(op.get("blocked_tools") or [])
        if blocked:
            allowed = [t for t in allowed if t not in blocked]
        if not op.get("email_guard_enabled", True):
            # Guard off still keeps anti-repeat soft, but allows email in allowlist.
            pass
        elif "email.send" in blocked:
            allowed = [t for t in allowed if t != "email.send"]
        recent_invocations = [
            {
                "tool": v.get("tool_name"),
                "status": v.get("status"),
                "args": {k: v2 for k, v2 in (v.get("arguments") or {}).items() if k != "body"},
                "result_preview": (v.get("result") or {}).get("data"),
            }
            for v in self.store.tool_invocations.values()
            if v.get("process_run_id") == str(run.id)
        ][-8:]
        allocation = self._latest_allocation(process_id) or {}
        assignments = self._assignment_dicts(allocation)
        email_recipients = []
        for a in assignments:
            email = self._email_for_assignment(a)
            if not email:
                continue
            email_recipients.append(
                {
                    "requirement": a.get("requirement"),
                    "step_id": a.get("step_id"),
                    "display_name": a.get("display_name"),
                    "resource_id": a.get("resource_id"),
                    "resource_type": a.get("resource_type"),
                    "email": email,
                }
            )
        preferred = self._resolve_email_recipient_from_allocation(
            process_id=process_id, run=run, current_step=current_step
        )
        active_requests = [
            {
                "request_id": str(r.get("id")),
                "supplier_id": str(r.get("supplier_id")),
                "supplier_name": r.get("supplier_name")
                or self._supplier_name(r.get("supplier_id")),
                "product_sku": r.get("product_sku"),
                "quantity": r.get("quantity"),
                "status": r.get("status"),
            }
            for r in self.store.quote_requests.values()
            if r.get("organization_id") == str(self.organization_id)
        ]
        collected_quotes = [
            {
                "quotation_id": str(q.get("id")),
                "request_id": str(q.get("request_id")),
                "supplier_id": str(q.get("supplier_id")),
                "supplier_name": q.get("supplier_name")
                or self._supplier_name(q.get("supplier_id")),
                "unit_price": q.get("unit_price"),
                "total": q.get("total") or q.get("subtotal"),
                "currency": q.get("currency", "USD"),
                "delivery_days": q.get("delivery_days"),
                "warranty_months": q.get("warranty_months"),
            }
            for q in self.store.quotations.values()
            if q.get("organization_id") == str(self.organization_id)
        ]
        pos = [
            {
                "purchase_order_id": str(p.get("id")),
                "po_number": p.get("po_number"),
                "supplier_id": str(p.get("supplier_id")),
                "supplier_name": self._supplier_name(p.get("supplier_id")),
                "amount_total": p.get("amount_total"),
                "currency_code": p.get("currency_code"),
                "status": p.get("status"),
                "submitted": p.get("submitted", False),
            }
            for p in self.store.purchase_orders.values()
            if p.get("organization_id") == str(self.organization_id)
        ]
        snapshot_summary = {
            "process_id": str(process_id),
            "run_id": str(run.id),
            "goal": plan_dict.get("goal"),
            "current_step_index": curr_idx,
            "current_step": current_step,
            "remaining_steps": steps[curr_idx : curr_idx + 5],
            "allowed_tools": allowed,
            "tool_schemas": {
                name: TOOL_ARGS[name].model_json_schema() for name in allowed if name in TOOL_ARGS
            },
            "allocated_resources": [
                {
                    "requirement": a.get("requirement"),
                    "display_name": a.get("display_name"),
                    "resource_id": a.get("resource_id"),
                    "resource_type": a.get("resource_type"),
                    "email": self._email_for_assignment(a),
                    "step_id": a.get("step_id"),
                }
                for a in assignments[:20]
            ],
            "agent2_email_recipients": email_recipients[:20],
            "preferred_email_recipient": preferred,
            "directory": self._directory_context(),
            "recent_tool_results": recent_invocations,
            "executed_tools": sorted(self._successful_tool_names(run)),
            "outbound_already_sent": self._outbound_sent_records(run),
            "step_checklist": self._step_checklist(step=current_step, run=run),
            "active_quote_requests": active_requests,
            "collected_quotations": collected_quotes,
            "purchase_orders": pos,
            "status": run.status.value,
            "execution_rules": {
                "max_email_send_per_run": 2,
                "never_resend_same_recipient": True,
                "prefer_document_and_notification_before_email": True,
                "advance_only_when_step_checklist_complete": True,
                "email_guard_enabled": op.get("email_guard_enabled", True),
                "blocked_tools": list(op.get("blocked_tools") or []),
            },
            "operator_guidance": op.get("guidance") or "",
        }

        if isinstance(self.client, FakeGeminiClient) and not self.client.structured_queue:
            proposal = self._heuristic_proposal(
                current_step=current_step,
                allowed=allowed,
                curr_idx=curr_idx,
                allocation=allocation,
                process_id=process_id,
                run=run,
            )
            return self._refine_proposal(
                proposal,
                process_id=process_id,
                run=run,
                steps=steps,
                curr_idx=curr_idx,
                allowed=allowed,
            )

        system, user_prompt = self.prompts.render(
            AgentKind.EXECUTION,
            "propose_tools",
            snapshot_json=json.dumps(snapshot_summary, default=str),
        )
        system += (
            f" You must select a tool from this exact allowed list: {allowed}. "
            "Never invent tools. Provide structured JSON matching ToolProposalOutput schema. "
            "You are a disciplined execution agent — complete commercial outcomes, not inbox spam. "
            "Read step_checklist.remaining and executed_tools before choosing. "
            "Never propose a tool already listed in executed_tools unless it is required for a "
            "distinct supplier/request (e.g. a second supplier.request_quote). "
            "NEVER propose email.send if outbound_already_sent already contains email.send, "
            "or if the same recipient was already emailed. Max two email.send calls per run. "
            "Prefer this order: gather evidence → RFQ/collect/compare → draft/submit PO → "
            "document.generate → task.assign / calendar.create_event → notification.send → "
            "email.send only once as a final confirmation if still needed. "
            "For RFQ steps: request quotes from at least 2 suppliers, collect each quote, "
            "run quotation.compare, then set next_step_index to the next step. "
            "For Order steps: create_draft → submit → document.generate, then one notification "
            "or one confirmation email — only then advance next_step_index. "
            "Keep next_step_index equal to current_step_index until step_checklist.complete "
            "would be true after this tool. "
            "Write professional subjects/bodies for outbound tools when needed. "
            "CRITICAL: recipients MUST prefer preferred_email_recipient / Agent 2 allocations. "
            "Use a STABLE idempotency_key derived from run+step+tool+recipient purpose — "
            "do not invent a fresh random UUID for the same intent. "
            "Prefer concrete operational tools (RFQ, PO, document, calendar, task, notify) "
            "over repeated email.send. Do not propose dry-run placeholders."
        )
        guidance = str(op.get("guidance") or "").strip()
        if guidance:
            system += (
                f" OPERATOR GUIDANCE (highest priority for tool choice): {guidance} "
            )
        if blocked:
            system += f" Do not propose these blocked tools: {sorted(blocked)}. "

        ctx = AgentExecutionContext(
            organization_id=self.organization_id,
            process_id=process_id,
            correlation_id=correlation_id,
            trace_id=correlation_id,
            actor_user_id=user_id,
            agent=AgentKind.EXECUTION,
            permissions=permissions,
        )
        try:
            res = self.structured.generate(
                context=ctx,
                output_model=ToolProposalOutput,
                system_instruction=system,
                user_prompt=user_prompt,
                max_output_tokens=2048,
            )
            proposal: ToolProposalOutput = res.data
            return self._refine_proposal(
                proposal,
                process_id=process_id,
                run=run,
                steps=steps,
                curr_idx=curr_idx,
                allowed=allowed,
            )
        except Exception as exc:
            logger.warning("execution.propose_tool_failed", error=str(exc))
            proposal = self._heuristic_proposal(
                current_step=current_step,
                allowed=allowed,
                curr_idx=curr_idx,
                allocation=allocation,
                error=str(exc),
                process_id=process_id,
                run=run,
            )
            return self._refine_proposal(
                proposal,
                process_id=process_id,
                run=run,
                steps=steps,
                curr_idx=curr_idx,
                allowed=allowed,
            )

    def _heuristic_proposal(
        self,
        *,
        current_step: dict[str, Any] | None,
        allowed: list[str],
        curr_idx: int,
        allocation: dict[str, Any],
        error: str | None = None,
        process_id: UUID | None = None,
        run: Any | None = None,
    ) -> ToolProposalOutput:
        text = " ".join(
            str(x)
            for x in [
                (current_step or {}).get("title"),
                (current_step or {}).get("description"),
                (current_step or {}).get("action_type"),
            ]
            if x
        ).lower()
        assignments = self._assignment_dicts(allocation)
        people = [
            a
            for a in assignments
            if a.get("resource_type")
            in {"employee", "manager", "approval_authority", "supplier_contact"}
        ]
        allocated_suppliers = [a for a in assignments if a.get("resource_type") == "supplier"]
        contacts = [a for a in assignments if a.get("resource_type") == "supplier_contact"]
        idem = str(uuid.uuid4())

        def _pick(*names: str) -> str | None:
            for n in names:
                if n in allowed:
                    return n
            return None

        def _allocated_recipient() -> str | None:
            for pool in (contacts, people, allocated_suppliers):
                for a in pool:
                    email = self._email_for_assignment(a)
                    if email:
                        return email
                    if a.get("resource_id"):
                        return str(a["resource_id"])
            return None

        dir_ctx = self._directory_context()
        dir_suppliers = dir_ctx.get("suppliers") or []
        avail_suppliers = list(allocated_suppliers)
        for s in dir_suppliers:
            if not any(str(a.get("resource_id")) == str(s.get("id")) for a in allocated_suppliers):
                avail_suppliers.append({"resource_id": s.get("id"), "display_name": s.get("name")})

        run_id_str = str(run.id) if run and getattr(run, "id", None) else None
        proc_id_str = str(process_id) if process_id else None

        run_invs = [
            inv
            for inv in self.store.tool_invocations.values()
            if (run_id_str and inv.get("process_run_id") == run_id_str)
        ]
        executed_tools = {
            inv.get("tool_name")
            for inv in run_invs
            if inv.get("status") in {"executed", "replayed"}
        }

        reqs = [
            r
            for r in self.store.quote_requests.values()
            if r.get("organization_id") == str(self.organization_id)
            and (
                (run_id_str and r.get("process_run_id") == run_id_str)
                or (proc_id_str and r.get("process_id") == proc_id_str)
                or not (run_id_str or proc_id_str)
            )
        ]
        req_id_set = {str(r.get("id")) for r in reqs}
        quotes = [
            q
            for q in self.store.quotations.values()
            if q.get("organization_id") == str(self.organization_id)
            and (
                (proc_id_str and q.get("process_id") == proc_id_str)
                or (str(q.get("request_id")) in req_id_set)
                or not proc_id_str
            )
        ]
        pos = [
            p
            for p in self.store.purchase_orders.values()
            if p.get("organization_id") == str(self.organization_id)
            and (
                (run_id_str and p.get("process_run_id") == run_id_str)
                or (proc_id_str and p.get("process_id") == proc_id_str)
                or not (run_id_str or proc_id_str)
            )
        ]

        # 1. Discovery / Lookup step handling (First phase: Discover staff and suppliers)
        is_discovery_step = (
            (current_step or {}).get("action_type") in {"collect_info", "discovery"}
            or any(
                k in text
                for k in (
                    "identify staff",
                    "discover staff",
                    "staff & suppliers",
                    "directory lookup",
                    "supplier lookup",
                    "identify",
                    "discover",
                )
            )
        ) and not any(
            k in text
            for k in (
                "quote",
                "quotation",
                "rfq",
                "purchase order",
                "submit po",
                "create po",
                "issue purchase order",
            )
        )
        if is_discovery_step:
            if _pick("supplier.search") and "supplier.search" not in executed_tools:
                return ToolProposalOutput(
                    tool_name="supplier.search",
                    arguments={"query": "hardware", "approved_only": True},
                    rationale="Heuristic: search approved hardware suppliers",
                    next_step_index=curr_idx + 1,
                )
            if _pick("company.employee_lookup") and "company.employee_lookup" not in executed_tools:
                return ToolProposalOutput(
                    tool_name="company.employee_lookup",
                    arguments={"query": "IT"},
                    rationale="Heuristic: discover procurement and IT staff",
                    next_step_index=curr_idx + 1,
                )
            return ToolProposalOutput(
                tool_name=allowed[0] if allowed else "company.employee_lookup",
                arguments={"query": "procurement"},
                rationale="Heuristic: discovery completed",
                next_step_index=curr_idx + 1,
            )

        # 2. Quotation / RFQ step handling (Dual quotes + Collection + Comparison)
        if any(k in text for k in ("quote", "quotation", "rfq", "dual quote")):
            if _pick("supplier.request_quote") and len(reqs) == 0:
                s1_id = avail_suppliers[0].get("resource_id") if avail_suppliers else "supp-001"
                return ToolProposalOutput(
                    tool_name="supplier.request_quote",
                    arguments={
                        "supplier_id": str(s1_id),
                        "product_sku": "LAPTOP-PRO-01",
                        "quantity": 5,
                        "subject": "RFQ: Enterprise Laptops (Primary Source)",
                        "body": "Please provide formal quotation for 5 high-performance laptops.",
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: issue initial quotation request (RFQ 1 of 2)",
                    next_step_index=curr_idx,
                )
            if _pick("supplier.request_quote") and len(reqs) == 1:
                s1_used = str(reqs[0].get("supplier_id"))
                s2_id = next(
                    (
                        str(s.get("resource_id"))
                        for s in avail_suppliers
                        if str(s.get("resource_id")) != s1_used
                    ),
                    str(avail_suppliers[1].get("resource_id"))
                    if len(avail_suppliers) > 1
                    else "supp-002",
                )
                return ToolProposalOutput(
                    tool_name="supplier.request_quote",
                    arguments={
                        "supplier_id": s2_id,
                        "product_sku": "LAPTOP-PRO-01",
                        "quantity": 5,
                        "subject": "RFQ: Enterprise Laptops (Dual Source Benchmark)",
                        "body": (
                            "Please provide competitive quotation for 5 "
                            "high-performance laptops."
                        ),
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: issue dual quotation request (RFQ 2 of 2)",
                    next_step_index=curr_idx,
                )
            if _pick("supplier.collect_quote") and reqs:
                collected_req_ids = {str(q.get("request_id")) for q in quotes}
                uncollected = [r for r in reqs if str(r.get("id")) not in collected_req_ids]
                if uncollected:
                    target_req = uncollected[0]
                    return ToolProposalOutput(
                        tool_name="supplier.collect_quote",
                        arguments={
                            "request_id": str(target_req.get("id")),
                            "idempotency_key": idem,
                        },
                        rationale=(
                            f"Heuristic: collect commercial quotation response for request "
                            f"{target_req.get('id')}"
                        ),
                        next_step_index=curr_idx,
                    )
            if _pick("quotation.compare") and len(quotes) >= 2:
                if "quotation.compare" not in executed_tools:
                    return ToolProposalOutput(
                        tool_name="quotation.compare",
                        arguments={
                            "quotation_ids": [str(q.get("id")) for q in quotes[:5]],
                            "explain": True,
                        },
                        rationale=(
                            "Heuristic: compare and rank collected quotations across price, "
                            "warranty, and lead time"
                        ),
                        next_step_index=curr_idx + 1,
                    )

        # 3. Purchase Order / Order & Stakeholder Notice step handling
        is_order_step = any(
            k in text
            for k in (
                "purchase order",
                "create po",
                "submit po",
                "issue po",
                "issue purchase order",
                "place order",
            )
        ) or (
            (current_step or {}).get("action_type") == "integration"
            and any(k in text for k in ("order", "stakeholder notice", "po"))
        )
        if is_order_step:
            draft_pos = [p for p in pos if not p.get("submitted")]
            submitted_pos = [p for p in pos if p.get("submitted")]

            if not pos and _pick("purchase_order.create_draft"):
                win_s_id = None
                win_amount = 2400.0
                if quotes:
                    sorted_quotes = sorted(
                        quotes, key=lambda q: float(q.get("total") or q.get("subtotal") or 999999.0)
                    )
                    win_quote = sorted_quotes[0]
                    win_s_id = str(win_quote.get("supplier_id"))
                    win_amount = float(
                        win_quote.get("total") or win_quote.get("subtotal") or 2400.0
                    )
                elif avail_suppliers:
                    win_s_id = str(avail_suppliers[0].get("resource_id"))
                else:
                    win_s_id = "supp-001"
                unit_price = round(win_amount / 5, 2)
                return ToolProposalOutput(
                    tool_name="purchase_order.create_draft",
                    arguments={
                        "supplier_id": win_s_id,
                        "amount_total": win_amount,
                        "currency_code": "USD",
                        "lines": [
                            {
                                "description": "High-performance laptops",
                                "quantity": 5,
                                "unit_price": unit_price,
                            }
                        ],
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: draft purchase order with selected winning supplier",
                    next_step_index=curr_idx,
                )

            if draft_pos and not submitted_pos and _pick("purchase_order.submit"):
                target_po = draft_pos[0]
                return ToolProposalOutput(
                    tool_name="purchase_order.submit",
                    arguments={
                        "purchase_order_id": str(target_po.get("id")),
                        "idempotency_key": idem,
                    },
                    rationale=f"Heuristic: submit approved purchase order {target_po.get('id')}",
                    next_step_index=curr_idx,
                )

            if submitted_pos or pos:
                if _pick("document.generate") and "document.generate" not in executed_tools:
                    po_tot = pos[0].get("amount_total", 2400.0)
                    return ToolProposalOutput(
                        tool_name="document.generate",
                        arguments={
                            "title": "Procurement Contract & PO Summary Memo",
                            "doc_type": "memo",
                            "content": (
                                f"Purchase order submitted. Total commitment: ${po_tot:.2f}. "
                                "Hardware fulfillment scheduled in accordance with vendor terms."
                            ),
                            "idempotency_key": idem,
                        },
                        rationale="Heuristic: generate commercial procurement summary memo",
                        next_step_index=curr_idx,
                    )
                if _pick("calendar.create_event") and "calendar.create_event" not in executed_tools:
                    recipient = _allocated_recipient() or "owner@demo.bpm.local"
                    from datetime import datetime, timedelta

                    start = datetime.now(UTC) + timedelta(days=2)
                    return ToolProposalOutput(
                        tool_name="calendar.create_event",
                        arguments={
                            "title": "Hardware Delivery & Asset Tagging Kickoff",
                            "start_at": start.replace(microsecond=0).isoformat(),
                            "attendees": [str(recipient)],
                            "description": (
                                "Stakeholder coordination meeting for hardware receipt "
                                "and asset tagging."
                            ),
                            "idempotency_key": idem,
                        },
                        rationale="Heuristic: schedule delivery and rollout kickoff meeting",
                        next_step_index=curr_idx,
                    )
                if _pick("task.assign") and "task.assign" not in executed_tools:
                    recipient = _allocated_recipient() or "owner@demo.bpm.local"
                    return ToolProposalOutput(
                        tool_name="task.assign",
                        arguments={
                            "title": "Verify hardware shipment & IT asset logging",
                            "assignee_id": str(recipient),
                            "description": (
                                "Confirm serial numbers match purchase order upon delivery."
                            ),
                            "idempotency_key": idem,
                        },
                        rationale="Heuristic: assign hardware verification task",
                        next_step_index=curr_idx,
                    )
                if _pick("notification.send") and "notification.send" not in executed_tools:
                    recipient = _allocated_recipient() or "owner@demo.bpm.local"
                    return ToolProposalOutput(
                        tool_name="notification.send",
                        arguments={
                            "user_id": str(recipient),
                            "title": "Procurement Process Completed",
                            "body": (
                                "Purchase order submitted, supplier confirmed, "
                                "and deployment meeting scheduled."
                            ),
                            "idempotency_key": idem,
                        },
                        rationale="Heuristic: notify stakeholders of completed procurement run",
                        next_step_index=curr_idx + 1,
                    )
                if _pick("email.send") and "email.send" not in executed_tools:
                    recipient = _allocated_recipient() or "owner@demo.bpm.local"
                    return ToolProposalOutput(
                        tool_name="email.send",
                        arguments={
                            "to_employee_id": str(recipient),
                            "subject": "Purchase Order Completed & Dispatched",
                            "body": (
                                "Hello,\n\nThe purchase order has been successfully submitted "
                                "and confirmed.\n\nRegards,\nBPM Agent"
                            ),
                            "idempotency_key": idem,
                        },
                        rationale="Heuristic: email confirmation to stakeholder",
                        next_step_index=curr_idx + 1,
                    )

        # 4. Standard Single-Action Triggers
        if any(k in text for k in ("meeting", "calendar", "schedule", "kickoff", "sync")):
            if _pick("calendar.create_event"):
                recipient = _allocated_recipient() or "owner@demo.bpm.local"
                from datetime import datetime, timedelta

                start = datetime.now(UTC) + timedelta(days=1)
                return ToolProposalOutput(
                    tool_name="calendar.create_event",
                    arguments={
                        "title": (current_step or {}).get("title") or "Process meeting",
                        "start_at": start.replace(microsecond=0).isoformat(),
                        "attendees": [str(recipient)],
                        "description": (current_step or {}).get("description") or "",
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: create calendar event with invite",
                    next_step_index=curr_idx + 1,
                )

        if any(
            k in text
            for k in ("assign task", "task assign", "follow up task", "todo", "action item")
        ):
            if _pick("task.assign"):
                recipient = _allocated_recipient() or "owner@demo.bpm.local"
                return ToolProposalOutput(
                    tool_name="task.assign",
                    arguments={
                        "title": (current_step or {}).get("title") or "Follow-up task",
                        "assignee_id": str(recipient),
                        "description": (current_step or {}).get("description") or "",
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: assign task and notify assignee",
                    next_step_index=curr_idx + 1,
                )

        if any(
            k in text
            for k in ("generate document", "write memo", "rfq pack", "summary doc", "documentation")
        ):
            if _pick("document.generate"):
                return ToolProposalOutput(
                    tool_name="document.generate",
                    arguments={
                        "title": (current_step or {}).get("title") or "Process document",
                        "doc_type": "memo",
                        "content": (current_step or {}).get("description")
                        or "Generated by Agent 4",
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: generate process document",
                    next_step_index=curr_idx + 1,
                )

        if any(k in text for k in ("approv",)):
            tool = _pick("approval.request", "notification.send", "email.send")
            if tool == "approval.request":
                return ToolProposalOutput(
                    tool_name=tool,
                    arguments={
                        "reason": (current_step or {}).get("title") or "Approval checkpoint",
                        "required_roles": ["manager"],
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: approval checkpoint",
                    next_step_index=curr_idx,
                    requires_approval=True,
                    approval_reason="Step requires human approval",
                )

        # 5. Generic communication or fallback
        tool = _pick("company.employee_lookup", "supplier.search", "notification.send") or (
            allowed[0] if allowed else "company.employee_lookup"
        )
        args: dict[str, Any] = {}
        if tool in {
            "company.employee_lookup",
            "supplier.search",
            "policy.search",
            "document.search",
        }:
            args = {"query": (current_step or {}).get("title") or "process"}
        elif tool == "notification.send":
            args = {
                "title": (current_step or {}).get("title") or "Process update",
                "body": (current_step or {}).get("description") or "Step executed",
                "idempotency_key": idem,
            }
        return ToolProposalOutput(
            tool_name=tool,
            arguments=args,
            rationale=f"Deterministic fallback proposal for step {curr_idx}"
            + (f" after LLM error: {error}" if error else ""),
            next_step_index=curr_idx + 1,
        )

    def _ensure_tool_args(
        self, tool_name: str, args: dict[str, Any], *, process_id: UUID, run: Any
    ) -> None:
        # Resolve recipient/purpose first for tools that need it, then stamp a stable key.
        if tool_name in {"email.send", "email.create_draft"}:
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            if preferred and preferred.get("email"):
                args["to_employee_id"] = preferred["email"]
            elif not args.get("to_employee_id"):
                directory = self._directory_context()
                contacts = directory.get("supplier_contacts") or []
                emps = directory.get("employees") or []
                if contacts:
                    args["to_employee_id"] = contacts[0].get("email") or contacts[0].get("id")
                elif emps:
                    args["to_employee_id"] = emps[0].get("id")
                else:
                    args["to_employee_id"] = "owner@demo.bpm.local"

            needs_compose = (
                not args.get("subject")
                or not args.get("body")
                or str(args.get("subject")).strip().lower()
                in {"process execution update", "action required"}
                or "authored during agent 4" in str(args.get("body") or "").lower()
            )
            if needs_compose:
                composed = self._compose_email_with_gemini(
                    process_id=process_id, run=run, args=args
                )
                if composed:
                    args["subject"] = (
                        composed.get("subject") or args.get("subject") or "Process update"
                    )
                    args["body"] = (
                        composed.get("body") or args.get("body") or "Please see process details."
                    )
            if not args.get("subject"):
                name = (preferred or {}).get("display_name") if preferred else None
                args["subject"] = (
                    f"Process update for {name}" if name else "Process execution update"
                )
            if not args.get("body"):
                greet = (preferred or {}).get("display_name") if preferred else "there"
                args["body"] = (
                    f"Hello {greet},\n\n"
                    "This message was authored during Agent 4 process execution.\n\n"
                    "Regards,\nBPM Agent"
                )
            args.pop("_allocated_recipient", None)

        elif tool_name == "supplier.request_quote":
            supplier_id = str(args.get("supplier_id") or "").strip()
            placeholder = supplier_id.lower() in {
                "",
                "sup-001",
                "supp-001",
                "supp-002",
                "supplier-1",
                "unknown",
            }
            if placeholder:
                # Prefer suppliers discovered earlier in THIS run via supplier.search.
                found_ids: list[str] = []
                for row in self._run_invocation_rows(run):
                    if row.get("tool_name") != "supplier.search":
                        continue
                    if row.get("status") not in {"executed", "replayed"}:
                        continue
                    data = ((row.get("result") or {}) if isinstance(row.get("result"), dict) else {})
                    # result may be nested under data
                    payload = data.get("data") if isinstance(data.get("data"), dict) else data
                    hits = []
                    if isinstance(payload, dict):
                        hits = payload.get("suppliers") or payload.get("items") or []
                    for hit in hits:
                        if isinstance(hit, dict) and hit.get("id"):
                            found_ids.append(str(hit["id"]))
                allocation = self._latest_allocation(process_id) or {}
                suppliers = [
                    a
                    for a in self._assignment_dicts(allocation)
                    if a.get("resource_type") == "supplier"
                ]
                for s in suppliers:
                    if s.get("resource_id"):
                        found_ids.append(str(s.get("resource_id")))
                dir_suppliers = self._directory_context().get("suppliers") or []
                for s in dir_suppliers:
                    if s.get("id"):
                        found_ids.append(str(s["id"]))
                # Prefer a supplier not already requested.
                requested = {
                    str(r.get("supplier_id"))
                    for r in self.store.quote_requests.values()
                    if r.get("organization_id") == str(self.organization_id)
                }
                unused = [sid for sid in found_ids if sid not in requested]
                pick = (unused or found_ids or [None])[0]
                if pick:
                    args["supplier_id"] = pick
            args.setdefault("product_sku", "LAPTOP-PRO-01")
            args.setdefault("quantity", 5)
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            if preferred and preferred.get("email"):
                args.setdefault("contact_email", preferred["email"])
            args.setdefault("subject", "RFQ: Enterprise High-Performance Laptops")
            args.setdefault(
                "body", "Please provide a formal quotation for 5 high-performance laptops."
            )

        elif tool_name == "supplier.collect_quote":
            if not args.get("request_id"):
                collected_req_ids = {
                    str(q.get("request_id"))
                    for q in self.store.quotations.values()
                    if q.get("organization_id") == str(self.organization_id)
                }
                uncollected = [
                    r
                    for r in self.store.quote_requests.values()
                    if r.get("organization_id") == str(self.organization_id)
                    and str(r.get("id")) not in collected_req_ids
                ]
                if uncollected:
                    args["request_id"] = str(uncollected[0].get("id"))
                else:
                    all_reqs = [
                        r
                        for r in self.store.quote_requests.values()
                        if r.get("organization_id") == str(self.organization_id)
                    ]
                    if all_reqs:
                        args["request_id"] = str(all_reqs[-1].get("id"))

        elif tool_name == "quotation.compare":
            if not args.get("quotation_ids"):
                q_ids = [
                    str(q.get("id"))
                    for q in self.store.quotations.values()
                    if q.get("organization_id") == str(self.organization_id)
                ]
                args["quotation_ids"] = q_ids if q_ids else ["dummy-quote-1"]
            args.setdefault("explain", True)

        elif tool_name == "purchase_order.create_draft":
            if not args.get("supplier_id") or not args.get("amount_total"):
                quotes = [
                    q
                    for q in self.store.quotations.values()
                    if q.get("organization_id") == str(self.organization_id)
                ]
                if quotes:
                    sorted_quotes = sorted(
                        quotes,
                        key=lambda q: float(q.get("total") or q.get("subtotal") or 999999.0),
                    )
                    best_quote = sorted_quotes[0]
                    if not args.get("supplier_id"):
                        args["supplier_id"] = str(best_quote.get("supplier_id"))
                    if not args.get("amount_total") or float(args["amount_total"]) <= 0:
                        args["amount_total"] = float(
                            best_quote.get("total") or best_quote.get("subtotal") or 2400.0
                        )
                else:
                    if not args.get("supplier_id"):
                        dir_suppliers = self._directory_context().get("suppliers") or []
                        args["supplier_id"] = (
                            str(dir_suppliers[0]["id"]) if dir_suppliers else "supp-001"
                        )
                    if not args.get("amount_total") or float(args["amount_total"]) <= 0:
                        args["amount_total"] = 2400.0
            args.setdefault("currency_code", "USD")
            if not args.get("lines"):
                tot = float(args.get("amount_total") or 2400.0)
                args["lines"] = [
                    {
                        "description": "High-performance laptops",
                        "quantity": 5,
                        "unit_price": round(tot / 5, 2),
                    }
                ]

        elif tool_name == "purchase_order.submit":
            if not args.get("purchase_order_id"):
                drafts = [
                    p
                    for p in self.store.purchase_orders.values()
                    if p.get("organization_id") == str(self.organization_id)
                    and not p.get("submitted")
                ]
                if drafts:
                    args["purchase_order_id"] = str(drafts[-1].get("id"))
                else:
                    all_pos = [
                        p
                        for p in self.store.purchase_orders.values()
                        if p.get("organization_id") == str(self.organization_id)
                    ]
                    if all_pos:
                        args["purchase_order_id"] = str(all_pos[-1].get("id"))

        elif tool_name == "notification.send":
            args.setdefault("title", "Process update")
            args.setdefault("body", "Agent 4 completed a process step.")
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            if not args.get("user_id"):
                if preferred and preferred.get("email"):
                    args["user_id"] = preferred["email"]
                elif preferred and preferred.get("resource_id"):
                    args["user_id"] = str(preferred["resource_id"])
                else:
                    args["user_id"] = "owner@demo.bpm.local"

        elif tool_name == "calendar.create_event":
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            args.setdefault("title", "Process meeting")
            if not args.get("start_at"):
                from datetime import datetime, timedelta

                args["start_at"] = (
                    (datetime.now(UTC) + timedelta(days=1))
                    .replace(microsecond=0)
                    .isoformat()
                )
            attendees = list(args.get("attendees") or [])
            if preferred and preferred.get("email") and preferred["email"] not in attendees:
                attendees.insert(0, preferred["email"])
            if not attendees:
                attendees = ["owner@demo.bpm.local"]
            args["attendees"] = attendees

        elif tool_name == "task.assign":
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            args.setdefault("title", "Process follow-up")
            if not args.get("assignee_id"):
                if preferred and preferred.get("email"):
                    args["assignee_id"] = preferred["email"]
                else:
                    args["assignee_id"] = "owner@demo.bpm.local"

        elif tool_name == "document.generate":
            args.setdefault("title", "Process document")
            args.setdefault("doc_type", "memo")
            if not args.get("content"):
                # Richer default content from run context.
                goal = ""
                try:
                    version = self.processes.get_version(
                        process_id, getattr(run, "process_version_id", None)
                    )
                    goal = str((version.plan_snapshot or {}).get("goal") or "")
                except Exception:  # noqa: BLE001
                    goal = ""
                pos = [
                    p
                    for p in self.store.purchase_orders.values()
                    if p.get("organization_id") == str(self.organization_id)
                ]
                quotes = [
                    q
                    for q in self.store.quotations.values()
                    if q.get("organization_id") == str(self.organization_id)
                ]
                lines = [
                    f"Process goal: {goal or 'N/A'}",
                    f"Quotations collected: {len(quotes)}",
                    f"Purchase orders: {len(pos)}",
                    "Generated by Agent 4 during controlled execution.",
                ]
                if pos:
                    po = pos[-1]
                    lines.insert(
                        1,
                        f"Latest PO {po.get('po_number') or po.get('id')} "
                        f"status={po.get('status')} submitted={po.get('submitted')}",
                    )
                args["content"] = "\n".join(lines)

        if tool_name in TOOL_ARGS and "idempotency_key" in TOOL_ARGS[tool_name].model_fields:
            purpose_bits = [
                self._normalize_recipient(
                    args.get("to_employee_id")
                    or args.get("user_id")
                    or args.get("assignee_id")
                    or args.get("contact_email")
                    or args.get("supplier_id")
                    or args.get("purchase_order_id")
                    or args.get("request_id")
                    or args.get("title")
                    or args.get("subject")
                    or "default"
                )
            ]
            if tool_name == "supplier.request_quote":
                purpose_bits.append(str(args.get("product_sku") or "sku"))
            if tool_name == "document.generate":
                purpose_bits.append(str(args.get("doc_type") or "memo"))
            purpose = "|".join(purpose_bits)
            existing = str(args.get("idempotency_key") or "").strip()
            # Replace missing keys and raw UUIDs the model invents; keep explicit operator keys.
            is_raw_uuid = bool(
                re.fullmatch(
                    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                    existing,
                )
            )
            if not existing or is_raw_uuid:
                args["idempotency_key"] = self._stable_idempotency_key(
                    run=run, tool_name=tool_name, purpose=purpose
                )
    def _compose_email_with_gemini(
        self, *, process_id: UUID, run: Any, args: dict[str, Any]
    ) -> dict[str, str] | None:
        """Ask Gemini to author subject/body for the current step."""
        if isinstance(self.client, FakeGeminiClient):
            return None
        try:
            version = self.processes.get_version(process_id, run.process_version_id)
            steps = (version.plan_snapshot or {}).get("steps") or []
            idx = int(getattr(run, "current_step_index", 0) or 0)
            step = steps[idx] if idx < len(steps) else {}
            allocation = self._latest_allocation(process_id) or {}
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run, current_step=step
            )
            prompt = {
                "goal": (version.plan_snapshot or {}).get("goal"),
                "step": step,
                "recipient": preferred or {"to": args.get("to_employee_id")},
                "instruction": (
                    "Address the email to the allocated recipient by name. "
                    "Do not invent another recipient."
                ),
                "allocated_resources": [
                    {
                        **a,
                        "email": self._email_for_assignment(a),
                    }
                    for a in self._assignment_dicts(allocation)[:12]
                ],
            }

            from pydantic import BaseModel, Field

            class EmailComposeOut(BaseModel):
                subject: str = Field(min_length=1, max_length=200)
                body: str = Field(min_length=1, max_length=8000)

            ctx = AgentExecutionContext(
                organization_id=self.organization_id,
                process_id=process_id,
                correlation_id=getattr(run, "correlation_id", None),
                trace_id=getattr(run, "correlation_id", None),
                actor_user_id=getattr(run, "initiated_by_user_id", None),
                agent=AgentKind.EXECUTION,
                permissions=frozenset({"execution.run"}),
            )
            res = self.structured.generate(
                context=ctx,
                output_model=EmailComposeOut,
                system_instruction=(
                    "You are Agent 4 writing a real business email for process execution. "
                    "Write a clear subject and complete professional body. No markdown fences. "
                    "Use facts from the process step and allocated resources only."
                ),
                user_prompt=json.dumps(prompt, default=str),
                max_output_tokens=1024,
            )
            return {"subject": res.data.subject, "body": res.data.body}
        except Exception as exc:  # noqa: BLE001
            logger.warning("execution.email_compose_failed", error=str(exc))
            return None

    def _invocation_summary(self, invocation: ToolInvocation) -> dict[str, Any]:
        data = (invocation.result.data if invocation.result else {}) or {}
        summary: dict[str, Any] = {"tool": invocation.tool_name, "status": invocation.status}
        for key in (
            "to",
            "subject",
            "status",
            "id",
            "provider",
            "mock",
            "supplier_id",
            "amount_total",
        ):
            if key in data:
                summary[key] = data[key]
        if data.get("body"):
            summary["body_preview"] = str(data["body"])[:240]
        return summary

    def _recent_emails(self, *, limit: int = 10) -> list[dict[str, Any]]:
        items = [
            e
            for e in self.store.email_outbox.values()
            if e.get("organization_id") == str(self.organization_id)
        ]
        items.sort(key=lambda e: e.get("updated_at") or e.get("created_at") or "", reverse=True)
        return [
            {
                "id": e.get("id"),
                "to": e.get("to"),
                "subject": e.get("subject") or "(no subject)",
                "body": e.get("body"),
                "body_preview": " ".join(str(e.get("body") or "").split())[:360],
                "summary": (
                    f"{str(e.get('status') or 'sent').title()} "
                    f"“{e.get('subject') or '(no subject)'}” "
                    f"to {', '.join(e.get('to') or []) or 'unknown recipient'}."
                ),
                "status": e.get("status"),
                "provider": e.get("provider"),
                "provider_message_id": e.get("provider_message_id"),
                "mock": e.get("mock"),
                "process_id": e.get("process_id"),
                "created_at": e.get("created_at"),
            }
            for e in items[:limit]
        ]
