"""Agent 4 — Controlled Process Execution orchestration."""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

from app.agents.execution.catalog import TOOL_ARGS, TOOL_CATALOG
from app.agents.execution.gateway import ToolGateway
from app.agents.execution.models import ExecutionState, ToolContext, ToolInvocation, ToolProposalOutput
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
import structlog

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
        max_steps = max(1, min(int(max_steps or 20), 40))

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

            args = dict(proposal.arguments or {})
            self._ensure_tool_args(proposal.tool_name, args, process_id=process_id, run=run)

            before_idx = int(getattr(run, "current_step_index", 0) or 0)
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

            if inv.status in {"denied", "failed"}:
                # Try one alternate read-only/notification tool before pausing
                if executed < max_steps and inv.error and inv.error.code.value != "APPROVAL_REQUIRED":
                    alt = self._heuristic_proposal(
                        current_step=steps[curr_idx] if curr_idx < len(steps) else None,
                        allowed=[
                            t
                            for t in (
                                getattr(run, "allowed_tools", None) or list(TOOL_CATALOG.keys())
                            )
                            if t
                            not in {
                                proposal.tool_name,
                                "purchase_order.submit",
                                "email.send",
                            }
                            or t
                            in {
                                "email.create_draft",
                                "notification.send",
                                "company.employee_lookup",
                                "supplier.search",
                            }
                        ],
                        curr_idx=curr_idx,
                        allocation=self._latest_allocation(process_id) or {},
                        error=inv.error.message,
                    )
                    if alt.tool_name != proposal.tool_name:
                        args2 = dict(alt.arguments or {})
                        self._ensure_tool_args(
                            alt.tool_name, args2, process_id=process_id, run=run
                        )
                        inv2 = self.invoke_tool(
                            process_id,
                            tool_name=alt.tool_name,
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
                            continue
                break
            if run.status in {
                ProcessRunStatus.PAUSED,
                ProcessRunStatus.AWAITING_APPROVAL,
                ProcessRunStatus.BLOCKED,
                ProcessRunStatus.FAILED,
            }:
                break
            after_idx = int(getattr(run, "current_step_index", 0) or 0)
            if after_idx == before_idx and inv.status == "replayed":
                run.current_step_index = after_idx + 1
                run.updated_at = utcnow()

        if steps and int(getattr(run, "current_step_index", 0) or 0) >= len(steps):
            if run.status == ProcessRunStatus.EXECUTING:
                run.status = ProcessRunStatus.COMPLETED
                run.pause_reason = None
                run.updated_at = utcnow()

        from app.database.persist_helpers import persist_if_postgres

        persist_if_postgres(self.store, "process_runs", run.id)
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

        persist_if_postgres(self.store, "process_runs", run.id)
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
        successful_tools = [
            i for i in invocations if i.get("status") in {"executed", "replayed"}
        ]
        failed_tools = [
            i for i in invocations if i.get("status") in {"failed", "denied"}
        ]

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
            if code in {"APPROVAL_REQUIRED", "MISSING_INFORMATION"}:
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
            run.current_step_index = int(getattr(run, "current_step_index", 0) or 0) + 1
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

    def get_execution(
        self, process_id: UUID, *, run_id: UUID | None = None
    ) -> dict[str, Any]:
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
                result.explanation
                + " Scoring is deterministic across cost, delivery, warranty, "
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

    def _resolve_run(self, process_id: UUID, run_id: UUID | None):
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

    def _latest_approved(self, process_id: UUID):
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

        def _updated(r: Any):
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

        step_id = str(
            (current_step or {}).get("step_id")
            or (current_step or {}).get("id")
            or ""
        )
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
            "reason": f"Agent 2 allocated {best.get('display_name')} for '{best.get('requirement')}'",
        }

    def _allowed_tools_from_plan(self, plan_snapshot: dict[str, Any]) -> list[str]:
        allowed: set[str] = set(TOOL_CATALOG.keys())
        step_tools: set[str] = set()
        for step in plan_snapshot.get("steps") or []:
            for t in step.get("allowed_tools") or []:
                step_tools.add(t)
        if step_tools:
            allowed &= step_tools
            for name, tool in TOOL_CATALOG.items():
                if tool.side_effect_status.value == "none":
                    allowed.add(name)
            for name in (
                "email.create_draft",
                "email.send",
                "notification.send",
                "supplier.request_quote",
                "supplier.collect_quote",
                "purchase_order.create_draft",
                "purchase_order.submit",
                "approval.request",
                "calendar.create_event",
                "task.assign",
                "document.generate",
            ):
                if name in TOOL_CATALOG:
                    allowed.add(name)
        return sorted(allowed)

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
        recent_invocations = [
            {
                "tool": v.get("tool_name"),
                "status": v.get("status"),
                "args": {
                    k: v2 for k, v2 in (v.get("arguments") or {}).items() if k != "body"
                },
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
        snapshot_summary = {
            "process_id": str(process_id),
            "run_id": str(run.id),
            "goal": plan_dict.get("goal"),
            "current_step_index": curr_idx,
            "current_step": current_step,
            "remaining_steps": steps[curr_idx : curr_idx + 5],
            "allowed_tools": allowed,
            "tool_schemas": {
                name: TOOL_ARGS[name].model_json_schema()
                for name in allowed
                if name in TOOL_ARGS
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
            "status": run.status.value,
        }

        if isinstance(self.client, FakeGeminiClient) and not self.client.structured_queue:
            return self._heuristic_proposal(
                current_step=current_step,
                allowed=allowed,
                curr_idx=curr_idx,
                allocation=allocation,
            )

        system, user_prompt = self.prompts.render(
            AgentKind.EXECUTION,
            "propose_tools",
            snapshot_json=json.dumps(snapshot_summary, default=str),
        )
        system += (
            f" You must select a tool from this exact allowed list: {allowed}. "
            "Never invent tools. Provide structured JSON matching ToolProposalOutput schema. "
            "For email.send / email.create_draft / notification.send / supplier.request_quote: "
            "write a professional subject and full body yourself (Gemini authors the message). "
            "Use calendar.create_event for meetings/kickoffs (title, start_at ISO, attendees emails). "
            "Use task.assign to hand work to an employee (title, assignee_id email or id). "
            "Use document.generate for RFQ packs, PO summaries, or memos (title, doc_type, content). "
            "CRITICAL: to_employee_id / attendees / assignee_id MUST prefer the Agent 2 allocated "
            "recipient — use preferred_email_recipient.email or agent2_email_recipients / "
            "allocated_resources. Never invent a random directory contact when Agent 2 "
            "already allocated a supplier contact or employee for this process. "
            "Always include a unique idempotency_key (uuid string) for side-effecting tools. "
            "Prefer concrete side-effecting tools: email, RFQ, PO, notify, calendar, task, document. "
            "Do not propose dry-run placeholders."
        )

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
            if proposal.tool_name not in allowed:
                proposal.tool_name = allowed[0] if allowed else "company.employee_lookup"
                proposal.rationale += " (Selected fallback tool from allowed catalog)"
            proposal.next_step_index = curr_idx
            return proposal
        except Exception as exc:
            logger.warning("execution.propose_tool_failed", error=str(exc))
            return self._heuristic_proposal(
                current_step=current_step,
                allowed=allowed,
                curr_idx=curr_idx,
                allocation=allocation,
                error=str(exc),
            )

    def _heuristic_proposal(
        self,
        *,
        current_step: dict[str, Any] | None,
        allowed: list[str],
        curr_idx: int,
        allocation: dict[str, Any],
        error: str | None = None,
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
        suppliers = [a for a in assignments if a.get("resource_type") == "supplier"]
        contacts = [a for a in assignments if a.get("resource_type") == "supplier_contact"]
        idem = str(uuid.uuid4())

        def _pick(*names: str) -> str | None:
            for n in names:
                if n in allowed:
                    return n
            return None

        def _allocated_recipient() -> str | None:
            # Prefer contact → people → supplier's contact email from Agent 2
            for pool in (contacts, people, suppliers):
                for a in pool:
                    email = self._email_for_assignment(a)
                    if email:
                        return email
                    if a.get("resource_id"):
                        return str(a["resource_id"])
            return None

        if any(k in text for k in ("meeting", "calendar", "schedule", "kickoff", "sync")):
            if _pick("calendar.create_event"):
                recipient = _allocated_recipient() or "owner@demo.bpm.local"
                from datetime import datetime, timedelta, timezone

                start = datetime.now(timezone.utc) + timedelta(days=1)
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
                    next_step_index=curr_idx,
                )

        if any(k in text for k in ("assign task", "task assign", "follow up task", "todo", "action item")):
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
                    next_step_index=curr_idx,
                )

        if any(k in text for k in ("generate document", "write memo", "rfq pack", "summary doc", "documentation")):
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
                    next_step_index=curr_idx,
                )

        if any(k in text for k in ("email", "notify", "rfq", "request quote", "contact vendor")):
            tool = _pick(
                "email.send",
                "email.create_draft",
                "notification.send",
                "supplier.request_quote",
            )
            recipient = _allocated_recipient()
            if not recipient:
                directory = self._directory_context()
                emps = directory.get("employees") or []
                recipient = (emps[0].get("id") if emps else None) or "owner@demo.bpm.local"
            subject = f"Action required: {(current_step or {}).get('title') or 'Process step'}"
            body = (
                f"Hello,\n\n"
                f"Regarding: {(current_step or {}).get('title') or 'current process step'}.\n\n"
                f"{(current_step or {}).get('description') or 'Please proceed with the requested action.'}\n\n"
                f"This message was generated by Agent 4 during process execution.\n\n"
                f"Regards,\nAcme BPM Agent"
            )
            if tool == "notification.send":
                return ToolProposalOutput(
                    tool_name=tool,
                    arguments={
                        "user_id": str(recipient),
                        "title": subject,
                        "body": body[:1900],
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: notify for communication step",
                    next_step_index=curr_idx,
                )
            if tool == "supplier.request_quote" and suppliers:
                return ToolProposalOutput(
                    tool_name=tool,
                    arguments={
                        "supplier_id": str(suppliers[0].get("resource_id")),
                        "product_sku": "ITEM-001",
                        "quantity": 1,
                        "subject": subject[:200],
                        "body": body[:8000],
                        "contact_email": str(recipient) if "@" in str(recipient) else None,
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: RFQ email via supplier.request_quote",
                    next_step_index=curr_idx,
                )
            if tool:
                return ToolProposalOutput(
                    tool_name=tool,
                    arguments={
                        "to_employee_id": str(recipient),
                        "subject": subject[:200],
                        "body": body[:8000],
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: email Agent 2 allocated recipient"
                    + (f" (LLM fallback: {error})" if error else ""),
                    next_step_index=curr_idx,
                )

        if any(k in text for k in ("quote", "quotation", "rfq", "dual quote")):
            if suppliers and _pick("supplier.request_quote"):
                return ToolProposalOutput(
                    tool_name="supplier.request_quote",
                    arguments={
                        "supplier_id": str(suppliers[0].get("resource_id")),
                        "product_sku": "ITEM-001",
                        "quantity": 1,
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: request supplier quote",
                    next_step_index=curr_idx,
                )
            tool = _pick("supplier.search", "email.send", "email.create_draft")
            if tool == "supplier.search":
                return ToolProposalOutput(
                    tool_name=tool,
                    arguments={"query": "approved", "approved_only": True},
                    rationale="Heuristic: search suppliers before quote",
                    next_step_index=curr_idx,
                )
            if tool in {"email.send", "email.create_draft"}:
                recipient = _allocated_recipient() or "owner@demo.bpm.local"
                return ToolProposalOutput(
                    tool_name=tool,
                    arguments={
                        "to_employee_id": str(recipient),
                        "subject": f"RFQ: {(current_step or {}).get('title') or 'Quote request'}",
                        "body": (
                            "Hello,\n\nPlease provide a quotation for the requested items.\n\n"
                            f"Step: {(current_step or {}).get('description') or 'dual quotes'}\n\n"
                            "Regards,\nBPM Agent"
                        ),
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: email RFQ to Agent 2 allocated contact",
                    next_step_index=curr_idx,
                )

        if any(k in text for k in ("purchase order", "create po", "submit po", "buy", "procure")):
            tool = _pick("purchase_order.create_draft", "purchase_order.submit")
            if tool == "purchase_order.create_draft" and suppliers:
                return ToolProposalOutput(
                    tool_name=tool,
                    arguments={
                        "supplier_id": str(suppliers[0].get("resource_id")),
                        "amount_total": 100.0,
                        "currency_code": "USD",
                        "lines": [],
                        "idempotency_key": idem,
                    },
                    rationale="Heuristic: draft purchase order",
                    next_step_index=curr_idx,
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
            next_step_index=curr_idx,
        )

    def _ensure_tool_args(
        self, tool_name: str, args: dict[str, Any], *, process_id: UUID, run: Any
    ) -> None:
        if tool_name in TOOL_ARGS and "idempotency_key" in TOOL_ARGS[tool_name].model_fields:
            if not args.get("idempotency_key"):
                args["idempotency_key"] = str(uuid.uuid4())
        if tool_name in {"email.send", "email.create_draft"}:
            # Agent 2 allocation is source of truth for who receives the email
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            if preferred and preferred.get("email"):
                args["to_employee_id"] = preferred["email"]
                args["_allocated_recipient"] = {
                    "display_name": preferred.get("display_name"),
                    "requirement": preferred.get("requirement"),
                    "resource_type": preferred.get("resource_type"),
                    "resource_id": preferred.get("resource_id"),
                    "email": preferred.get("email"),
                }
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
                composed = self._compose_email_with_gemini(process_id=process_id, run=run, args=args)
                if composed:
                    args["subject"] = composed.get("subject") or args.get("subject") or "Process update"
                    args["body"] = composed.get("body") or args.get("body") or "Please see process details."
            if not args.get("subject"):
                name = (preferred or {}).get("display_name") if preferred else None
                args["subject"] = (
                    f"Process update for {name}" if name else "Process execution update"
                )
            if not args.get("body"):
                greet = (preferred or {}).get("display_name") if preferred else "there"
                args["body"] = (
                    f"Hello {greet},\n\n"
                    "This message was authored during Agent 4 process execution "
                    "using the recipient allocated by Agent 2.\n\n"
                    "Regards,\nBPM Agent"
                )
            # Gateway schema rejects unknown keys
            args.pop("_allocated_recipient", None)
        if tool_name == "notification.send":
            args.setdefault("title", "Process update")
            args.setdefault("body", "Agent 4 completed a process step.")
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            if preferred and preferred.get("email"):
                args.setdefault("user_id", preferred["email"])
            elif preferred and preferred.get("resource_id"):
                args.setdefault("user_id", str(preferred["resource_id"]))

        if tool_name == "calendar.create_event":
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            args.setdefault("title", "Process meeting")
            if not args.get("start_at"):
                from datetime import datetime, timedelta, timezone

                args["start_at"] = (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).replace(microsecond=0).isoformat()
            attendees = list(args.get("attendees") or [])
            if preferred and preferred.get("email") and preferred["email"] not in attendees:
                attendees.insert(0, preferred["email"])
            if not attendees:
                attendees = ["owner@demo.bpm.local"]
            args["attendees"] = attendees

        if tool_name == "task.assign":
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            args.setdefault("title", "Process follow-up")
            if preferred and preferred.get("email"):
                args["assignee_id"] = preferred["email"]
            elif not args.get("assignee_id"):
                args["assignee_id"] = "owner@demo.bpm.local"

        if tool_name == "document.generate":
            args.setdefault("title", "Process document")
            args.setdefault("doc_type", "memo")
            if not args.get("content"):
                args["content"] = "Generated by Agent 4 during process execution."

        if tool_name == "supplier.request_quote":
            preferred = self._resolve_email_recipient_from_allocation(
                process_id=process_id, run=run
            )
            if preferred and preferred.get("email"):
                args.setdefault("contact_email", preferred["email"])
            args.setdefault("product_sku", "ITEM-001")
            args.setdefault("quantity", 1)
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
                "recipient": preferred
                or {"to": args.get("to_employee_id")},
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
                    f"{str(e.get('status') or 'sent').title()} “{e.get('subject') or '(no subject)'}” "
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
