"""Deterministic policy rules for Agent 3 (run before Gemini)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from app.agents.allocation.models import ResourceAllocationResult, ResourceType
from app.agents.discovery.models import ProcessPlan
from app.agents.risk.models import (
    EvidenceReference,
    Impact,
    Likelihood,
    PolicyReference,
    PolicyRuleType,
    RiskCategory,
    RiskItem,
    RiskSeverity,
)
from app.database.memory import PolicyRecord


@dataclass
class RuleContext:
    organization_id: UUID
    plan: ProcessPlan
    allocation: ResourceAllocationResult | None
    policies: list[PolicyRecord]
    spending_amount: float | None = None
    quotation_count: int | None = None
    geographic_region: str | None = None
    handles_restricted_data: bool | None = None
    manager_threshold: float = 1_000.0
    finance_threshold: float = 10_000.0
    block_threshold: float = 100_000.0
    required_quotations: int = 2
    allowed_regions: set[str] = field(default_factory=lambda: {"US", "CA", "GB", "EU", "IN", "AU"})
    evidence_refs: list[EvidenceReference] = field(default_factory=list)


def _policy_ref(
    rule_type: PolicyRuleType,
    *,
    code: str,
    title: str,
    policy_id: str | None = None,
    section: str | None = None,
) -> PolicyReference:
    return PolicyReference(
        policy_id=policy_id,
        policy_code=code,
        title=title,
        rule_type=rule_type,
        section=section,
    )


def _extract_amount(plan: ProcessPlan, explicit: float | None) -> float | None:
    if explicit is not None:
        return explicit
    blob = plan.goal + " " + " ".join(s.description for s in plan.steps)
    if plan.intent:
        blob += " " + " ".join(plan.intent.inputs + plan.intent.outputs)
    matches = re.findall(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s*(k|m)?", blob, re.I)
    amounts: list[float] = []
    for raw, suffix in matches:
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if suffix and suffix.lower() == "k":
            value *= 1_000
        if suffix and suffix.lower() == "m":
            value *= 1_000_000
        if value >= 50:  # ignore tiny numbers that are likely counts
            amounts.append(value)
    return max(amounts) if amounts else None


def _count_quotes_in_plan(plan: ProcessPlan, explicit: int | None) -> int | None:
    if explicit is not None:
        return explicit
    blob = (plan.goal + " " + plan.reasoning_summary).lower()
    for step in plan.steps:
        blob += " " + step.description.lower()
    if "dual quote" in blob or "two quote" in blob or "2 quote" in blob:
        return 2
    if "three quote" in blob or "3 quote" in blob:
        return 3
    if "quote" in blob or "quotation" in blob:
        return 1
    return None


class DeterministicPolicyRules:
    """Evaluate hard policy rules. Never invents evidence or approves actions."""

    def evaluate(self, ctx: RuleContext) -> list[RiskItem]:
        items: list[RiskItem] = []
        amount = _extract_amount(ctx.plan, ctx.spending_amount)
        quotes = _count_quotes_in_plan(ctx.plan, ctx.quotation_count)
        policy_by_code = {p.code.lower(): p for p in ctx.policies if p.status == "active"}

        items.extend(self._spending_rules(ctx, amount, policy_by_code))
        items.extend(self._quotation_rules(ctx, quotes, policy_by_code))
        items.extend(self._supplier_rules(ctx, policy_by_code))
        items.extend(self._sod_rules(ctx, policy_by_code))
        items.extend(self._authority_limit_rules(ctx, amount, policy_by_code))
        items.extend(self._restricted_data_rules(ctx, policy_by_code))
        items.extend(self._geo_rules(ctx, policy_by_code))
        items.extend(self._documentation_rules(ctx, policy_by_code))
        items.extend(self._vendor_and_contract_rules(ctx, policy_by_code))
        items.extend(self._deadline_and_coi_rules(ctx, policy_by_code))
        return items

    def _spending_rules(
        self, ctx: RuleContext, amount: float | None, policies: dict[str, Any]
    ) -> list[RiskItem]:
        items: list[RiskItem] = []
        pol = policies.get("proc-001") or policies.get("fin-001")
        pid = str(pol.id) if pol else None
        if amount is None:
            items.append(
                RiskItem(
                    id="risk_spend_unknown",
                    category=RiskCategory.FINANCIAL,
                    severity=RiskSeverity.MEDIUM,
                    likelihood=Likelihood.POSSIBLE,
                    impact=Impact.MODERATE,
                    description="Spending amount is not established; cannot clear financial risk.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.SPENDING_THRESHOLD,
                        code="FIN-001",
                        title="Spending threshold policy",
                        policy_id=pid,
                        section="§1",
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=False,
                    required_remediation="Provide a verified spending amount before execution.",
                    required_approver="manager",
                    rule_type=PolicyRuleType.SPENDING_THRESHOLD,
                    review_or_expiration_date=date.today() + timedelta(days=30),
                )
            )
            return items

        if amount >= ctx.block_threshold:
            items.append(
                RiskItem(
                    id="risk_spend_blocked",
                    category=RiskCategory.FINANCIAL,
                    severity=RiskSeverity.CRITICAL,
                    likelihood=Likelihood.LIKELY,
                    impact=Impact.SEVERE,
                    description=f"Spending amount {amount:,.2f} exceeds hard block threshold {ctx.block_threshold:,.2f}.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.SPENDING_THRESHOLD,
                        code="FIN-001",
                        title="Spending threshold policy",
                        policy_id=pid,
                        section="§3 hard limit",
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=True,
                    required_remediation="Reduce spend or obtain audited executive override.",
                    required_approver="owner",
                    rule_type=PolicyRuleType.SPENDING_THRESHOLD,
                    review_or_expiration_date=date.today() + timedelta(days=7),
                )
            )
        elif amount >= ctx.finance_threshold:
            items.append(
                RiskItem(
                    id="risk_spend_finance",
                    category=RiskCategory.FINANCIAL,
                    severity=RiskSeverity.HIGH,
                    likelihood=Likelihood.LIKELY,
                    impact=Impact.MAJOR,
                    description=f"Spending amount {amount:,.2f} requires finance approval.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.FINANCE_APPROVAL,
                        code="FIN-001",
                        title="Spending threshold policy",
                        policy_id=pid,
                        section="§2 finance",
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=False,
                    required_remediation="Obtain finance approval against frozen snapshot.",
                    required_approver="finance",
                    rule_type=PolicyRuleType.FINANCE_APPROVAL,
                    review_or_expiration_date=date.today() + timedelta(days=14),
                )
            )
        elif amount >= ctx.manager_threshold:
            items.append(
                RiskItem(
                    id="risk_spend_manager",
                    category=RiskCategory.FINANCIAL,
                    severity=RiskSeverity.MEDIUM,
                    likelihood=Likelihood.POSSIBLE,
                    impact=Impact.MODERATE,
                    description=f"Spending amount {amount:,.2f} requires manager approval.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.MANAGER_APPROVAL,
                        code="FIN-001",
                        title="Spending threshold policy",
                        policy_id=pid,
                        section="§1 manager",
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=False,
                    required_remediation="Obtain manager approval against frozen snapshot.",
                    required_approver="manager",
                    rule_type=PolicyRuleType.MANAGER_APPROVAL,
                    review_or_expiration_date=date.today() + timedelta(days=14),
                )
            )
        return items

    def _quotation_rules(
        self, ctx: RuleContext, quotes: int | None, policies: dict[str, Any]
    ) -> list[RiskItem]:
        is_procurement = any(
            s.action_type.value in {"integration", "human_task"}
            or "procure" in s.description.lower()
            or "purchase" in s.description.lower()
            or "supplier" in " ".join(s.required_resources).lower()
            for s in ctx.plan.steps
        ) or "procure" in ctx.plan.goal.lower() or "purchase" in ctx.plan.goal.lower()
        if not is_procurement:
            return []
        pol = policies.get("proc-001")
        pid = str(pol.id) if pol else None
        if quotes is None or quotes < ctx.required_quotations:
            return [
                RiskItem(
                    id="risk_quotes_missing",
                    category=RiskCategory.PROCUREMENT,
                    severity=RiskSeverity.HIGH,
                    likelihood=Likelihood.LIKELY,
                    impact=Impact.MAJOR,
                    description=(
                        f"Required quotation count is {ctx.required_quotations}; "
                        f"found {quotes if quotes is not None else 0}."
                    ),
                    policy_reference=_policy_ref(
                        PolicyRuleType.REQUIRED_QUOTATION_COUNT,
                        code="PROC-001",
                        title="Procurement quotation policy",
                        policy_id=pid,
                        section="§2 quotes",
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=quotes is not None and quotes < ctx.required_quotations,
                    required_remediation="Collect additional vendor quotations before proceeding.",
                    required_approver="procurement",
                    rule_type=PolicyRuleType.REQUIRED_QUOTATION_COUNT,
                    review_or_expiration_date=date.today() + timedelta(days=14),
                )
            ]
        return []

    def _supplier_rules(self, ctx: RuleContext, policies: dict[str, Any]) -> list[RiskItem]:
        if ctx.allocation is None:
            return []
        pol = policies.get("proc-001") or policies.get("vnd-001")
        pid = str(pol.id) if pol else None
        items: list[RiskItem] = []
        for assignment in ctx.allocation.assignments:
            if assignment.resource_type != ResourceType.SUPPLIER:
                continue
            if (
                assignment.authorization_status.value != "authorized"
                or assignment.conflict_status.value == "unapproved"
                or not assignment.active_status
            ):
                items.append(
                    RiskItem(
                        id=f"risk_supplier_{assignment.resource_id}",
                        category=RiskCategory.VENDOR,
                        severity=RiskSeverity.CRITICAL,
                        likelihood=Likelihood.ALMOST_CERTAIN,
                        impact=Impact.MAJOR,
                        description=(
                            f"Supplier {assignment.display_name or assignment.resource_id} "
                            "is not approved/active for use."
                        ),
                        policy_reference=_policy_ref(
                            PolicyRuleType.APPROVED_SUPPLIER,
                            code="PROC-001",
                            title="Approved supplier requirement",
                            policy_id=pid,
                            section="§3 suppliers",
                        ),
                        evidence_references=[
                            EvidenceReference(
                                type="allocation",
                                id=assignment.resource_id,
                                label=assignment.display_name,
                            ),
                            *ctx.evidence_refs,
                        ],
                        blocking=True,
                        required_remediation="Replace with an approved supplier or complete supplier approval.",
                        required_approver="compliance",
                        rule_type=PolicyRuleType.APPROVED_SUPPLIER,
                        review_or_expiration_date=date.today() + timedelta(days=7),
                    )
                )
        # Also surface unresolved unapproved supplier conflicts from allocation
        for conflict in ctx.allocation.conflicts:
            if conflict.conflict_status.value == "unapproved":
                items.append(
                    RiskItem(
                        id=f"risk_supplier_conflict_{conflict.id}",
                        category=RiskCategory.VENDOR,
                        severity=RiskSeverity.CRITICAL,
                        likelihood=Likelihood.ALMOST_CERTAIN,
                        impact=Impact.MAJOR,
                        description=conflict.message,
                        policy_reference=_policy_ref(
                            PolicyRuleType.APPROVED_SUPPLIER,
                            code="PROC-001",
                            title="Approved supplier requirement",
                            policy_id=pid,
                        ),
                        evidence_references=list(ctx.evidence_refs),
                        blocking=True,
                        required_remediation="Use only approved suppliers.",
                        required_approver="compliance",
                        rule_type=PolicyRuleType.APPROVED_SUPPLIER,
                        review_or_expiration_date=date.today() + timedelta(days=7),
                    )
                )
        return items

    def _sod_rules(self, ctx: RuleContext, policies: dict[str, Any]) -> list[RiskItem]:
        if ctx.allocation is None:
            return []
        pol = policies.get("sod-001")
        pid = str(pol.id) if pol else None
        by_step: dict[str, list[str]] = {}
        for a in ctx.allocation.assignments:
            if a.resource_type.value in {"employee", "manager", "approval_authority"}:
                by_step.setdefault(a.step_id, []).append(a.resource_id)
        # Same person assigned as both requester-like and approver-like across steps
        people_roles: dict[str, set[str]] = {}
        for a in ctx.allocation.assignments:
            if a.resource_type.value not in {"employee", "manager", "approval_authority"}:
                continue
            role = a.requirement.lower()
            people_roles.setdefault(a.resource_id, set()).add(role)
        items: list[RiskItem] = []
        for resource_id, roles in people_roles.items():
            has_request = any(
                r in roles for r in ("requester", "buyer", "employee", "initiator", "requestor")
            )
            has_approve = any(
                r in roles for r in ("manager", "approver", "finance", "approval", "approval_authority")
            )
            if has_request and has_approve:
                items.append(
                    RiskItem(
                        id=f"risk_sod_{resource_id}",
                        category=RiskCategory.SEGREGATION_OF_DUTIES,
                        severity=RiskSeverity.CRITICAL,
                        likelihood=Likelihood.LIKELY,
                        impact=Impact.SEVERE,
                        description=(
                            "Same person is assigned both requestor and approver roles "
                            f"(resource {resource_id})."
                        ),
                        policy_reference=_policy_ref(
                            PolicyRuleType.SEGREGATION_OF_DUTIES,
                            code="SOD-001",
                            title="Segregation of duties",
                            policy_id=pid,
                        ),
                        evidence_references=[
                            EvidenceReference(type="allocation", id=resource_id, label="SoD conflict"),
                            *ctx.evidence_refs,
                        ],
                        blocking=True,
                        required_remediation="Assign a different approver than the requester.",
                        required_approver="compliance",
                        rule_type=PolicyRuleType.SEGREGATION_OF_DUTIES,
                        review_or_expiration_date=date.today() + timedelta(days=7),
                    )
                )
        return items

    def _authority_limit_rules(
        self, ctx: RuleContext, amount: float | None, policies: dict[str, Any]
    ) -> list[RiskItem]:
        if ctx.allocation is None or amount is None:
            return []
        pol = policies.get("fin-001")
        pid = str(pol.id) if pol else None
        items: list[RiskItem] = []
        for a in ctx.allocation.assignments:
            if a.resource_type.value not in {"manager", "approval_authority", "employee"}:
                continue
            limit = a.metadata.get("approval_authority_limit")
            if limit is None:
                continue
            try:
                limit_f = float(limit)
            except (TypeError, ValueError):
                continue
            if amount > limit_f:
                items.append(
                    RiskItem(
                        id=f"risk_auth_{a.resource_id}",
                        category=RiskCategory.FINANCIAL,
                        severity=RiskSeverity.HIGH,
                        likelihood=Likelihood.LIKELY,
                        impact=Impact.MAJOR,
                        description=(
                            f"Assigned approver authority limit {limit_f:,.2f} is below "
                            f"spending amount {amount:,.2f}."
                        ),
                        policy_reference=_policy_ref(
                            PolicyRuleType.EMPLOYEE_AUTHORITY_LIMIT,
                            code="FIN-001",
                            title="Employee authority limits",
                            policy_id=pid,
                        ),
                        evidence_references=list(ctx.evidence_refs),
                        blocking=True,
                        required_remediation="Assign an approver with sufficient authority.",
                        required_approver="finance",
                        rule_type=PolicyRuleType.EMPLOYEE_AUTHORITY_LIMIT,
                        review_or_expiration_date=date.today() + timedelta(days=7),
                    )
                )
        return items

    def _restricted_data_rules(self, ctx: RuleContext, policies: dict[str, Any]) -> list[RiskItem]:
        blob = (ctx.plan.goal + " " + ctx.plan.reasoning_summary).lower()
        for step in ctx.plan.steps:
            blob += " " + step.description.lower()
        flagged = ctx.handles_restricted_data
        if flagged is None:
            flagged = any(
                k in blob
                for k in ("pii", "personal data", "ssn", "restricted data", "gdpr", "phi", "hipaa")
            )
        if not flagged:
            return []
        pol = policies.get("prv-001")
        pid = str(pol.id) if pol else None
        has_privacy_step = any(
            "privacy" in s.description.lower() or "redact" in s.description.lower()
            for s in ctx.plan.steps
        )
        if has_privacy_step:
            return []
        return [
            RiskItem(
                id="risk_privacy_handling",
                category=RiskCategory.PRIVACY,
                severity=RiskSeverity.HIGH,
                likelihood=Likelihood.POSSIBLE,
                impact=Impact.MAJOR,
                description="Process appears to handle restricted data without a handling control step.",
                policy_reference=_policy_ref(
                    PolicyRuleType.RESTRICTED_DATA_HANDLING,
                    code="PRV-001",
                    title="Restricted data handling",
                    policy_id=pid,
                ),
                evidence_references=list(ctx.evidence_refs),
                blocking=True,
                required_remediation="Add restricted-data handling controls and privacy review.",
                required_approver="compliance",
                rule_type=PolicyRuleType.RESTRICTED_DATA_HANDLING,
                review_or_expiration_date=date.today() + timedelta(days=14),
            )
        ]

    def _geo_rules(self, ctx: RuleContext, policies: dict[str, Any]) -> list[RiskItem]:
        region = ctx.geographic_region
        if region is None:
            return []
        if region.upper() in {r.upper() for r in ctx.allowed_regions}:
            return []
        pol = policies.get("geo-001")
        pid = str(pol.id) if pol else None
        return [
            RiskItem(
                id="risk_geo",
                category=RiskCategory.DATA_RESIDENCY,
                severity=RiskSeverity.HIGH,
                likelihood=Likelihood.POSSIBLE,
                impact=Impact.MAJOR,
                description=f"Geographic region '{region}' is outside allowed residency set.",
                policy_reference=_policy_ref(
                    PolicyRuleType.GEOGRAPHIC_RESTRICTION,
                    code="GEO-001",
                    title="Geographic restrictions",
                    policy_id=pid,
                ),
                evidence_references=list(ctx.evidence_refs),
                blocking=True,
                required_remediation="Change region or obtain geo-exception via override workflow.",
                required_approver="compliance",
                rule_type=PolicyRuleType.GEOGRAPHIC_RESTRICTION,
                review_or_expiration_date=date.today() + timedelta(days=14),
            )
        ]

    def _documentation_rules(self, ctx: RuleContext, policies: dict[str, Any]) -> list[RiskItem]:
        required_docs = []
        if ctx.plan.intent:
            required_docs.extend(ctx.plan.intent.inputs)
        missing = [d for d in required_docs if "policy" in d.lower() or "contract" in d.lower()]
        # Missing evidence when no policy docs retrieved
        if not ctx.evidence_refs and any(
            "procure" in ctx.plan.goal.lower() or "purchase" in ctx.plan.goal.lower()
            for _ in [0]
        ):
            pol = policies.get("proc-001")
            pid = str(pol.id) if pol else None
            return [
                RiskItem(
                    id="risk_docs_missing",
                    category=RiskCategory.OPERATIONAL,
                    severity=RiskSeverity.MEDIUM,
                    likelihood=Likelihood.POSSIBLE,
                    impact=Impact.MODERATE,
                    description="Required policy documentation evidence was not retrieved.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.REQUIRED_DOCUMENTATION,
                        code="PROC-001",
                        title="Required documentation",
                        policy_id=pid,
                    ),
                    evidence_references=[],
                    blocking=False,
                    required_remediation="Attach or index applicable policy documents.",
                    required_approver="manager",
                    rule_type=PolicyRuleType.REQUIRED_DOCUMENTATION,
                    review_or_expiration_date=date.today() + timedelta(days=30),
                )
            ]
        return []

    def _vendor_and_contract_rules(
        self, ctx: RuleContext, policies: dict[str, Any]
    ) -> list[RiskItem]:
        items: list[RiskItem] = []
        blob = ctx.plan.goal.lower()
        if "expired contract" in blob or "contract expired" in blob:
            pol = policies.get("leg-001")
            pid = str(pol.id) if pol else None
            items.append(
                RiskItem(
                    id="risk_contract_expired",
                    category=RiskCategory.LEGAL,
                    severity=RiskSeverity.HIGH,
                    likelihood=Likelihood.LIKELY,
                    impact=Impact.MAJOR,
                    description="Plan references an expired contract.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.CONTRACT_EXPIRATION,
                        code="LEG-001",
                        title="Contract expiration",
                        policy_id=pid,
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=True,
                    required_remediation="Renew or replace the expired contract before execution.",
                    required_approver="legal",
                    rule_type=PolicyRuleType.CONTRACT_EXPIRATION,
                    review_or_expiration_date=date.today() + timedelta(days=7),
                )
            )
        if ctx.allocation:
            for c in ctx.allocation.conflicts:
                if c.conflict_status.value == "missing_contact":
                    items.append(
                        RiskItem(
                            id=f"risk_vendor_contact_{c.id}",
                            category=RiskCategory.VENDOR,
                            severity=RiskSeverity.MEDIUM,
                            likelihood=Likelihood.POSSIBLE,
                            impact=Impact.MODERATE,
                            description=c.message,
                            policy_reference=_policy_ref(
                                PolicyRuleType.VENDOR_RISK,
                                code="VND-001",
                                title="Vendor risk",
                            ),
                            evidence_references=list(ctx.evidence_refs),
                            blocking=False,
                            required_remediation="Add an active supplier contact before outreach.",
                            required_approver="procurement",
                            rule_type=PolicyRuleType.VENDOR_RISK,
                            review_or_expiration_date=date.today() + timedelta(days=14),
                        )
                    )
        return items

    def _deadline_and_coi_rules(
        self, ctx: RuleContext, policies: dict[str, Any]
    ) -> list[RiskItem]:
        items: list[RiskItem] = []
        blob = (ctx.plan.goal + " " + ctx.plan.reasoning_summary).lower()
        if "conflict of interest" in blob or "coi" in blob:
            items.append(
                RiskItem(
                    id="risk_coi",
                    category=RiskCategory.FRAUD,
                    severity=RiskSeverity.HIGH,
                    likelihood=Likelihood.POSSIBLE,
                    impact=Impact.MAJOR,
                    description="Conflict of interest indicator present in plan context.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.CONFLICT_OF_INTEREST,
                        code="COI-001",
                        title="Conflict of interest",
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=True,
                    required_remediation="Disclose and remediate conflict before approval.",
                    required_approver="compliance",
                    rule_type=PolicyRuleType.CONFLICT_OF_INTEREST,
                    review_or_expiration_date=date.today() + timedelta(days=7),
                )
            )
        if "past deadline" in blob or "overdue" in blob:
            items.append(
                RiskItem(
                    id="risk_deadline",
                    category=RiskCategory.OPERATIONAL,
                    severity=RiskSeverity.MEDIUM,
                    likelihood=Likelihood.LIKELY,
                    impact=Impact.MODERATE,
                    description="Process references a missed or overdue deadline.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.DEADLINE_RESTRICTION,
                        code="OPS-001",
                        title="Deadline restrictions",
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=False,
                    required_remediation="Update SLA/deadline and obtain manager acknowledgment.",
                    required_approver="manager",
                    rule_type=PolicyRuleType.DEADLINE_RESTRICTION,
                    review_or_expiration_date=date.today() + timedelta(days=7),
                )
            )
        # Reputational / security heuristics
        if "public disclosure" in blob or "press release" in blob:
            items.append(
                RiskItem(
                    id="risk_reputational",
                    category=RiskCategory.REPUTATIONAL,
                    severity=RiskSeverity.MEDIUM,
                    likelihood=Likelihood.POSSIBLE,
                    impact=Impact.MODERATE,
                    description="Public disclosure activity may create reputational exposure.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.REQUIRED_DOCUMENTATION,
                        code="REP-001",
                        title="Reputational review",
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=False,
                    required_remediation="Route through communications review.",
                    required_approver="manager",
                    rule_type=PolicyRuleType.REQUIRED_DOCUMENTATION,
                    review_or_expiration_date=date.today() + timedelta(days=14),
                )
            )
        if "admin privilege" in blob or "production access" in blob:
            items.append(
                RiskItem(
                    id="risk_security",
                    category=RiskCategory.SECURITY,
                    severity=RiskSeverity.HIGH,
                    likelihood=Likelihood.POSSIBLE,
                    impact=Impact.SEVERE,
                    description="Elevated production access indicated without security gate.",
                    policy_reference=_policy_ref(
                        PolicyRuleType.RESTRICTED_DATA_HANDLING,
                        code="SEC-001",
                        title="Security access control",
                    ),
                    evidence_references=list(ctx.evidence_refs),
                    blocking=True,
                    required_remediation="Add security review and least-privilege controls.",
                    required_approver="compliance",
                    rule_type=PolicyRuleType.RESTRICTED_DATA_HANDLING,
                    review_or_expiration_date=date.today() + timedelta(days=7),
                )
            )
        return items
