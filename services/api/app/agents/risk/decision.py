"""Deterministic decision engine for Agent 3 final risk decisions."""

from __future__ import annotations

from app.agents.risk.models import (
    RequiredApproval,
    RiskAmbiguityAssistOutput,
    RiskDecision,
    RiskItem,
)


def map_overall_status(decision: RiskDecision) -> str:
    return {
        RiskDecision.CLEAR: "pass",
        RiskDecision.APPROVAL_REQUIRED: "pass_with_conditions",
        RiskDecision.BLOCKED: "fail",
        RiskDecision.INSUFFICIENT_INFORMATION: "needs_human_review",
    }[decision]


def build_required_approvals(items: list[RiskItem]) -> list[RequiredApproval]:
    by_role: dict[str, RequiredApproval] = {}
    for item in items:
        if not item.required_approver:
            continue
        if item.blocking and item.required_approver:
            # still track for visibility; blocked items need override not normal approval
            pass
        role = item.required_approver
        if role not in by_role:
            by_role[role] = RequiredApproval(
                id=f"appr_{role}",
                role=role,
                reason=item.description,
                risk_item_ids=[item.id],
            )
        else:
            by_role[role].risk_item_ids.append(item.id)
            by_role[role].reason = f"{by_role[role].reason}; {item.description}"
    return list(by_role.values())


def decide_risk(
    *,
    items: list[RiskItem],
    missing_evidence: list[str],
    assist: RiskAmbiguityAssistOutput | None,
) -> tuple[RiskDecision, list[RiskItem], list[RequiredApproval], str]:
    """
    Final decision is deterministic.

    Gemini must not independently approve: any assist.independently_approves
    or proposed CLEAR is ignored when blocking/missing evidence exists.
    """
    blocking = [i for i in items if i.blocking]
    approvals_needed = [
        i
        for i in items
        if not i.blocking and i.required_approver and i.rule_type.value
        in {
            "spending_threshold",
            "manager_approval",
            "finance_approval",
            "required_quotation_count",
            "required_documentation",
            "deadline_restrictions",
            "vendor_risk",
        }
        or (not i.blocking and i.required_approver)
    ]
    # Deduplicate approval-needed list
    approvals_needed = [i for i in items if not i.blocking and i.required_approver]

    if assist and assist.independently_approves:
        # Record that we rejected Gemini self-approval; do not CLEAR
        pass

    if blocking:
        decision = RiskDecision.BLOCKED
        summary = (
            "Deterministic decision: BLOCKED due to policy violations. "
            "Gemini cannot approve or bypass blockers."
        )
    elif missing_evidence and not items:
        decision = RiskDecision.INSUFFICIENT_INFORMATION
        summary = "Deterministic decision: INSUFFICIENT_INFORMATION — missing policy evidence."
    elif missing_evidence and any(i.id == "risk_docs_missing" for i in items):
        # Missing docs with other soft findings → still may need approval
        if approvals_needed:
            decision = RiskDecision.APPROVAL_REQUIRED
            summary = (
                "Deterministic decision: APPROVAL_REQUIRED with incomplete evidence notes."
            )
        else:
            decision = RiskDecision.INSUFFICIENT_INFORMATION
            summary = "Deterministic decision: INSUFFICIENT_INFORMATION — attach policy evidence."
    elif any(i.id == "risk_spend_unknown" for i in items) and not approvals_needed:
        decision = RiskDecision.INSUFFICIENT_INFORMATION
        summary = "Deterministic decision: INSUFFICIENT_INFORMATION — spending amount unknown."
    elif approvals_needed:
        decision = RiskDecision.APPROVAL_REQUIRED
        summary = "Deterministic decision: APPROVAL_REQUIRED before execution."
    elif not items:
        # Only CLEAR when no findings and Gemini did not claim independent approval as sole basis
        if assist and assist.proposed_decision == RiskDecision.CLEAR and assist.independently_approves:
            decision = RiskDecision.INSUFFICIENT_INFORMATION
            summary = (
                "Rejected Gemini independent approval. "
                "INSUFFICIENT_INFORMATION until deterministic clear rules pass."
            )
        else:
            decision = RiskDecision.CLEAR
            summary = "Deterministic decision: CLEAR — no blocking or approval findings."
    else:
        decision = RiskDecision.APPROVAL_REQUIRED
        summary = "Deterministic decision: APPROVAL_REQUIRED for residual findings."

    # Never allow CLEAR if assist tried to approve while findings exist
    if (
        decision == RiskDecision.CLEAR
        and assist
        and assist.independently_approves
        and items
    ):
        decision = RiskDecision.APPROVAL_REQUIRED
        summary = "Gemini independent approval ignored; APPROVAL_REQUIRED retained."

    required = build_required_approvals(
        blocking + approvals_needed if decision != RiskDecision.BLOCKED else blocking + approvals_needed
    )
    if decision == RiskDecision.BLOCKED:
        # Blocked actions cannot proceed without override; keep approver visibility
        pass

    return decision, blocking, required, summary
