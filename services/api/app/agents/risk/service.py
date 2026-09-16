"""Agent 3 — Risk and Compliance Analysis service."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from app.agents.allocation.models import ResourceAllocationResult
from app.agents.discovery.models import ProcessPlan
from app.agents.risk.decision import decide_risk, map_overall_status
from app.agents.risk.models import (
    AnalyzeRiskRequest,
    EvidenceReference,
    RiskAmbiguityAssistOutput,
    RiskComplianceResult,
    RiskDecision,
)
from app.agents.risk.rules import DeterministicPolicyRules, RuleContext
from app.audit import AuditService
from app.contracts.common import utcnow
from app.database.memory import (
    ApprovalRecord,
    RiskResultRecord,
    get_memory_store,
    new_id,
)
from app.domain.enums import ApprovalStatus
from app.llm.client import FakeGeminiClient, GeminiClient, create_gemini_client
from app.llm.prompt_registry import PromptRegistry
from app.llm.structured import StructuredGenerationService
from app.llm.types import AgentExecutionContext, AgentKind, EvidenceRef
from app.repositories.memory_repos import (
    PolicyRepository,
    ProcessRepository,
)
from app.security.errors import ConflictError, NotFoundError, ValidationAppError
from app.services.documents.injection import assemble_agent_context, scan_for_injection
from app.services.documents.pipeline import DocumentSearchService
import structlog

logger = structlog.get_logger()


def _hash_payload(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode()
    else:
        raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


class RiskAnalysisService:
    """
    Architecture:
      1) Deterministic policy rules
      2) Retrieve policy documents
      3) Gemini for ambiguous relationships only
      4) Deterministic decision engine (Gemini cannot approve)
    """

    def __init__(
        self,
        organization_id: UUID,
        *,
        client: GeminiClient | None = None,
        structured: StructuredGenerationService | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.store = get_memory_store()
        self.processes = ProcessRepository(organization_id)
        self.policies = PolicyRepository(organization_id)
        self.rules = DeterministicPolicyRules()
        self.client = client or create_gemini_client()
        self.structured = structured or StructuredGenerationService(client=self.client)
        self.prompts = PromptRegistry()
        self.audit = AuditService()

    def analyze(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        permissions: frozenset[str],
        request: AnalyzeRiskRequest | None = None,
    ) -> RiskComplianceResult:
        request = request or AnalyzeRiskRequest()
        version, plan = self._resolve_plan(process_id, request.process_version_id)
        allocation, allocation_id, allocation_hash = self._resolve_allocation(
            process_id, request.allocation_id
        )
        plan_hash = version.plan_snapshot_hash

        evidence = self._retrieve_policy_evidence(plan)
        policies = self.policies.list_all()

        ctx = RuleContext(
            organization_id=self.organization_id,
            plan=plan,
            allocation=allocation,
            policies=policies,
            spending_amount=request.spending_amount,
            quotation_count=request.quotation_count,
            geographic_region=request.geographic_region,
            handles_restricted_data=request.handles_restricted_data,
            evidence_refs=evidence,
        )
        items = self.rules.evaluate(ctx)

        missing_evidence: list[str] = []
        if not evidence and any(
            k in plan.goal.lower() for k in ("procure", "purchase", "vendor", "supplier")
        ):
            missing_evidence.append("No indexed policy documents retrieved for procurement process")

        assist = self._gemini_ambiguity(
            plan=plan,
            items=items,
            evidence=evidence,
            user_id=user_id,
            correlation_id=correlation_id,
            permissions=permissions,
            process_id=process_id,
        )
        llm_used = assist is not None
        if assist and assist.independently_approves:
            # Explicit rejection path recorded in decision engine
            pass

        decision, blocking, required, summary = decide_risk(
            items=items,
            missing_evidence=missing_evidence,
            assist=assist,
        )
        if assist and assist.clarifying_questions:
            clarifying = list(assist.clarifying_questions)
        else:
            clarifying = []
        if decision == RiskDecision.INSUFFICIENT_INFORMATION:
            clarifying.append("Provide missing policy evidence or spending/quotation details.")

        ambiguous = list(assist.ambiguous_findings) if assist else []
        result_body = {
            "decision": decision.value,
            "items": [i.model_dump(mode="json") for i in items],
            "plan_hash": plan_hash,
            "allocation_hash": allocation_hash,
        }
        risk_hash = _hash_payload(result_body)
        now = utcnow()
        result = RiskComplianceResult(
            organization_id=self.organization_id,
            process_id=process_id,
            process_version_id=version.id,
            allocation_id=allocation_id,
            decision=decision,
            overall_status=map_overall_status(decision),  # type: ignore[arg-type]
            risk_items=items,
            blocking_issues=blocking,
            required_approvals=required,
            required_approver_roles=sorted({a.role for a in required}),
            policy_evidence=evidence,
            ambiguous_findings=ambiguous,
            clarifying_questions=clarifying,
            missing_evidence=missing_evidence,
            plan_snapshot_hash=plan_hash,
            allocation_snapshot_hash=allocation_hash,
            risk_snapshot_hash=risk_hash,
            reasoning_summary=(
                summary
                + (" " + assist.reasoning_summary if assist and assist.reasoning_summary else "")
            ),
            llm_used=llm_used,
            gemini_approved=False,
            valid=True,
            created_at=now,
            updated_at=now,
        )
        self._persist_result(result)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="risk.analyzed",
            resource_type="process",
            resource_id=process_id,
            correlation_id=correlation_id,
            payload={
                "decision": decision.value,
                "risk_snapshot_hash": risk_hash,
                "blocking_count": len(blocking),
                "gemini_approved": False,
            },
        )
        return result

    def get_risk(self, process_id: UUID) -> RiskComplianceResult:
        self.processes.get(process_id)
        records = [
            r
            for r in self.store.risk_results.values()
            if r.organization_id == self.organization_id and r.process_id == process_id
        ]
        if not records:
            raise NotFoundError("Risk result not found")
        latest = max(records, key=lambda r: r.updated_at)
        result = RiskComplianceResult.model_validate(latest.result_snapshot)
        # Live invalidation check
        if latest.valid:
            invalid = self._invalidation_reason(process_id, result)
            if invalid:
                latest.valid = False
                latest.invalidated_reason = invalid
                latest.updated_at = utcnow()
                result.valid = False
                result.invalidated_reason = invalid
                result.updated_at = latest.updated_at
                self._invalidate_approvals_for_process(process_id, reason=invalid)
        else:
            result.valid = False
            result.invalidated_reason = latest.invalidated_reason
        return result

    def create_approval_package(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        process_run_id: UUID | None = None,
    ) -> ApprovalRecord:
        result = self.get_risk(process_id)
        if not result.valid:
            raise ConflictError(
                "Risk result invalidated; re-run analysis before approval",
                code="RISK_INVALIDATED",
            )
        if result.decision == RiskDecision.BLOCKED:
            raise ConflictError(
                "Blocked actions cannot proceed without an audited override workflow",
                code="BLOCKED_REQUIRES_OVERRIDE",
            )
        if result.decision == RiskDecision.INSUFFICIENT_INFORMATION:
            raise ValidationAppError("Cannot create approval package with insufficient information")
        if result.decision == RiskDecision.CLEAR and not result.required_approvals:
            raise ValidationAppError("No approval required for CLEAR decision")

        approval_hash = _hash_payload(
            {
                "plan": result.plan_snapshot_hash,
                "allocation": result.allocation_snapshot_hash,
                "risk": result.risk_snapshot_hash,
                "process_id": str(process_id),
                "process_run_id": str(process_run_id) if process_run_id else None,
            }
        )
        # Approvals cannot be reused for another process run
        if process_run_id is not None:
            for existing in self.store.approvals.values():
                if (
                    existing.organization_id == self.organization_id
                    and existing.process_run_id == process_run_id
                    and existing.status == ApprovalStatus.APPROVED
                ):
                    raise ConflictError(
                        "Approval cannot be reused for another process run",
                        code="APPROVAL_REUSE_FORBIDDEN",
                    )

        risk_record = self._latest_risk_record(process_id)
        now = utcnow()
        record = ApprovalRecord(
            id=new_id(),
            organization_id=self.organization_id,
            process_run_id=process_run_id,
            status=ApprovalStatus.PENDING,
            snapshot_hash=approval_hash,
            snapshot_payload={
                "process_id": str(process_id),
                "process_version_id": str(result.process_version_id),
                "plan_snapshot_hash": result.plan_snapshot_hash,
                "allocation_snapshot_hash": result.allocation_snapshot_hash,
                "risk_snapshot_hash": result.risk_snapshot_hash,
                "decision": result.decision.value,
                "required_roles": result.required_approver_roles,
                "risk_items": [i.model_dump(mode="json") for i in result.risk_items],
                "policy_evidence": [e.model_dump(mode="json") for e in result.policy_evidence],
                "blocking_issues": [i.model_dump(mode="json") for i in result.blocking_issues],
            },
            decided_by_user_id=None,
            decision_note=None,
            row_version=1,
            created_at=now,
            updated_at=now,
            process_id=process_id,
            process_version_id=result.process_version_id,
            risk_result_id=risk_record.id if risk_record else None,
            plan_snapshot_hash=result.plan_snapshot_hash,
            allocation_snapshot_hash=result.allocation_snapshot_hash,
            risk_snapshot_hash=result.risk_snapshot_hash,
            required_roles=list(result.required_approver_roles),
            prohibited_action=False,
            override_required=False,
            requested_role=(result.required_approver_roles[0] if result.required_approver_roles else "manager"),
            requested_user=user_id,
            decision=None,
            decision_reason=None,
            requested_timestamp=now,
            decision_timestamp=None,
            expiration_timestamp=now + timedelta(hours=24),
            audit_reference=f"audit:{new_id()}",
            risk_analysis_id=risk_record.id if risk_record else None,
        )
        self.store.approvals[record.id] = record
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="approval.package_created",
            resource_type="approval",
            resource_id=record.id,
            correlation_id=correlation_id,
            payload={"approval_snapshot_hash": approval_hash},
        )
        return record

    def request_override(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        justification: str,
        acknowledged_risk_item_ids: list[str],
        authorized: bool,
    ) -> ApprovalRecord:
        """Audited override workflow for blocked actions — requires explicit authorization."""
        if not authorized:
            raise ValidationAppError(
                "Users cannot approve prohibited actions unless explicitly authorized"
            )
        result = self.get_risk(process_id)
        if result.decision != RiskDecision.BLOCKED:
            raise ValidationAppError("Override workflow only applies to BLOCKED decisions")
        if not justification.strip():
            raise ValidationAppError("Override justification is required")
        blocking_ids = {i.id for i in result.blocking_issues}
        if blocking_ids and not blocking_ids.issubset(set(acknowledged_risk_item_ids)):
            raise ValidationAppError("All blocking risk items must be acknowledged for override")

        now = utcnow()
        record = ApprovalRecord(
            id=new_id(),
            organization_id=self.organization_id,
            process_run_id=None,
            status=ApprovalStatus.PENDING,
            snapshot_hash=_hash_payload(
                {
                    "override": True,
                    "risk": result.risk_snapshot_hash,
                    "plan": result.plan_snapshot_hash,
                    "justification": justification,
                }
            ),
            snapshot_payload={
                "override": True,
                "justification": justification,
                "acknowledged_risk_item_ids": acknowledged_risk_item_ids,
                "process_id": str(process_id),
                "risk_snapshot_hash": result.risk_snapshot_hash,
                "plan_snapshot_hash": result.plan_snapshot_hash,
                "allocation_snapshot_hash": result.allocation_snapshot_hash,
                "blocking_issues": [i.model_dump(mode="json") for i in result.blocking_issues],
            },
            decided_by_user_id=None,
            decision_note=None,
            row_version=1,
            created_at=now,
            updated_at=now,
            process_id=process_id,
            process_version_id=result.process_version_id,
            risk_result_id=None,
            plan_snapshot_hash=result.plan_snapshot_hash,
            allocation_snapshot_hash=result.allocation_snapshot_hash,
            risk_snapshot_hash=result.risk_snapshot_hash,
            required_roles=["owner", "compliance"],
            prohibited_action=True,
            override_required=True,
        )
        self.store.approvals[record.id] = record
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="approval.override_requested",
            resource_type="approval",
            resource_id=record.id,
            correlation_id=correlation_id,
            payload={"justification": justification[:500]},
        )
        return record

    def invalidate_for_process(self, process_id: UUID, *, reason: str) -> None:
        now = utcnow()
        for record in self.store.risk_results.values():
            if (
                record.organization_id == self.organization_id
                and record.process_id == process_id
                and record.valid
            ):
                record.valid = False
                record.invalidated_reason = reason
                record.updated_at = now
        self._invalidate_approvals_for_process(process_id, reason=reason)

    def assert_approval_bound_to_snapshots(
        self,
        approval: ApprovalRecord,
        *,
        plan_hash: str,
        risk_hash: str,
        process_run_id: UUID | None = None,
    ) -> None:
        if approval.plan_snapshot_hash and approval.plan_snapshot_hash != plan_hash:
            raise ConflictError(
                "Approval snapshot does not match current plan hash",
                code="APPROVAL_PLAN_MISMATCH",
            )
        if approval.risk_snapshot_hash and approval.risk_snapshot_hash != risk_hash:
            raise ConflictError(
                "Approval snapshot does not match current risk hash",
                code="APPROVAL_RISK_MISMATCH",
            )
        if (
            approval.process_run_id is not None
            and process_run_id is not None
            and approval.process_run_id != process_run_id
        ):
            raise ConflictError(
                "Approval cannot be reused for another process run",
                code="APPROVAL_REUSE_FORBIDDEN",
            )
        if approval.prohibited_action and approval.status != ApprovalStatus.APPROVED:
            raise ConflictError(
                "Prohibited action requires completed override approval",
                code="OVERRIDE_REQUIRED",
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_plan(self, process_id: UUID, version_id: UUID | None):
        versions = self.processes.list_versions(process_id)
        if not versions:
            raise ValidationAppError("Process has no plan versions for risk analysis")
        if version_id is not None:
            version = self.processes.get_version(process_id, version_id)
        else:
            confirmed = [v for v in versions if v.status == "confirmed"]
            version = max(confirmed or versions, key=lambda v: v.version_number)
        plan = ProcessPlan.model_validate(version.plan_snapshot)
        return version, plan

    def _resolve_allocation(
        self, process_id: UUID, allocation_id: UUID | None
    ) -> tuple[ResourceAllocationResult | None, UUID | None, str | None]:
        records = [
            r
            for r in self.store.allocations.values()
            if r.organization_id == self.organization_id and r.process_id == process_id
        ]
        if allocation_id is not None:
            record = self.store.allocations.get(allocation_id)
            if record is None or record.organization_id != self.organization_id:
                raise NotFoundError("Allocation not found")
            records = [record]
        if not records:
            return None, None, None
        latest = max(records, key=lambda r: r.updated_at)
        allocation = ResourceAllocationResult.model_validate(latest.result_snapshot)
        return allocation, latest.id, _hash_payload(latest.result_snapshot)

    def _retrieve_policy_evidence(self, plan: ProcessPlan) -> list[EvidenceReference]:
        refs: list[EvidenceReference] = []
        # Indexed policies as structured evidence
        for policy in self.policies.list_all():
            if policy.status != "active":
                continue
            refs.append(
                EvidenceReference(
                    type="policy",
                    id=str(policy.id),
                    label=f"{policy.code} — {policy.title}",
                    excerpt=(policy.description or policy.title)[:300],
                )
            )
        # Document search (untrusted)
        try:
            search = DocumentSearchService(self.organization_id)
            hits = search.search(
                query=plan.goal or "policy compliance",
                mode="hybrid",
                limit=5,
                similarity_threshold=0.05,
                can_read_restricted=True,
            )
            for hit in hits:
                scan = scan_for_injection(hit.content)
                excerpt = hit.content[:400]
                if scan.suspicious:
                    excerpt = f"[injection_flags={scan.flags}] {excerpt}"
                refs.append(
                    EvidenceReference(
                        type="chunk",
                        id=str(hit.chunk_id),
                        label=hit.file_name,
                        excerpt=excerpt,
                        page_number=hit.page_number,
                    )
                )
        except Exception:
            pass
        return refs

    def _gemini_ambiguity(
        self,
        *,
        plan: ProcessPlan,
        items: list,
        evidence: list[EvidenceReference],
        user_id: UUID,
        correlation_id: str | None,
        permissions: frozenset[str],
        process_id: UUID,
    ) -> RiskAmbiguityAssistOutput | None:
        # Only skip when using fake client without queue
        soft = [i for i in items if not i.blocking]
        if isinstance(self.client, FakeGeminiClient) and not self.client.structured_queue:
            if not soft and evidence:
                return None
            return RiskAmbiguityAssistOutput(
                ambiguous_findings=[],
                clarifying_questions=[
                    "Confirm whether residual policy relationships are acceptable to approvers."
                ]
                if soft
                else [],
                reasoning_summary=(
                    "Ambiguity assist skipped (no structured queue). "
                    "Gemini must not independently approve."
                ),
                independently_approves=False,
                proposed_decision=None,
            )

        context = assemble_agent_context(
            citations=[],
            include_preamble=True,
        ) if False else ""
        evidence_blob = json.dumps([e.model_dump(mode="json") for e in evidence[:12]])
        findings_blob = json.dumps([i.model_dump(mode="json") for i in items[:20]])
        system, user_prompt = self.prompts.render(
            AgentKind.RISK,
            "analyze_risk",
            plan_json=plan.model_dump_json(),
            policies=f"{evidence_blob}\nFindings:\n{findings_blob}\n{context}",
        )
        system += (
            " Explain ambiguous policy relationships only. "
            "Never independently approve an action. "
            "Set independently_approves=false always. "
            "Do not set proposed_decision to CLEAR."
        )
        ctx = AgentExecutionContext(
            organization_id=self.organization_id,
            process_id=process_id,
            correlation_id=correlation_id,
            trace_id=correlation_id,
            actor_user_id=user_id,
            agent=AgentKind.RISK,
            permissions=permissions,
        )
        try:
            result = self.structured.generate(
                context=ctx,
                output_model=RiskAmbiguityAssistOutput,
                system_instruction=system,
                user_prompt=user_prompt,
                evidence_refs=[
                    EvidenceRef(type=e.type, id=e.id, label=e.label) for e in evidence[:8]
                ],
            )
            assist = result.data
            # Hard clamp: Gemini cannot approve
            assist.independently_approves = False
            if assist.proposed_decision == RiskDecision.CLEAR:
                assist.proposed_decision = None
            return assist
        except Exception as exc:
            logger.warning("risk.gemini_ambiguity_failed", error=str(exc))
            return RiskAmbiguityAssistOutput(
                reasoning_summary="Ambiguity assist unavailable; deterministic rules govern decision.",
                independently_approves=False,
            )

    def _persist_result(self, result: RiskComplianceResult) -> RiskResultRecord:
        # Invalidate prior results for process
        for prior in self.store.risk_results.values():
            if (
                prior.organization_id == self.organization_id
                and prior.process_id == result.process_id
                and prior.valid
            ):
                prior.valid = False
                prior.invalidated_reason = "Superseded by new risk analysis"
                prior.updated_at = utcnow()
        now = utcnow()
        record = RiskResultRecord(
            id=new_id(),
            organization_id=self.organization_id,
            process_id=result.process_id,
            process_version_id=result.process_version_id,
            allocation_id=result.allocation_id,
            status=result.decision.value,
            result_snapshot=result.model_dump(mode="json"),
            plan_snapshot_hash=result.plan_snapshot_hash,
            allocation_snapshot_hash=result.allocation_snapshot_hash,
            risk_snapshot_hash=result.risk_snapshot_hash,
            valid=True,
            invalidated_reason=None,
            created_at=now,
            updated_at=now,
        )
        self.store.risk_results[record.id] = record
        return record

    def _latest_risk_record(self, process_id: UUID) -> RiskResultRecord | None:
        records = [
            r
            for r in self.store.risk_results.values()
            if r.organization_id == self.organization_id and r.process_id == process_id
        ]
        if not records:
            return None
        return max(records, key=lambda r: r.updated_at)

    def _invalidation_reason(
        self, process_id: UUID, result: RiskComplianceResult
    ) -> str | None:
        versions = self.processes.list_versions(process_id)
        if versions:
            latest = max(versions, key=lambda v: v.version_number)
            if latest.plan_snapshot_hash != result.plan_snapshot_hash:
                return "Plan changes invalidate the risk result"
        allocs = [
            a
            for a in self.store.allocations.values()
            if a.organization_id == self.organization_id and a.process_id == process_id
        ]
        if allocs and result.allocation_snapshot_hash:
            latest_alloc = max(allocs, key=lambda a: a.updated_at)
            current_hash = _hash_payload(latest_alloc.result_snapshot)
            if current_hash != result.allocation_snapshot_hash:
                return "Resource allocation changes invalidate the risk result"
        return None

    def _invalidate_approvals_for_process(self, process_id: UUID, *, reason: str) -> None:
        now = utcnow()
        for approval in self.store.approvals.values():
            if (
                approval.organization_id == self.organization_id
                and approval.process_id == process_id
                and approval.status in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}
            ):
                approval.status = ApprovalStatus.INVALIDATED
                approval.decision_note = (
                    f"{approval.decision_note or ''} [invalidated: {reason}]".strip()
                )
                approval.updated_at = now
