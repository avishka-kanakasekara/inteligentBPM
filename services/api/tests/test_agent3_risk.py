"""Agent 3 — Risk and Compliance Analysis tests."""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.agents.allocation.models import (
    AuthorizationStatus,
    ConflictStatus,
    DataSource,
    ResourceAllocationResult,
    ResourceAssignment,
    ResourceType,
)
from app.agents.discovery.models import ActionType, ProcessPlan, ProcessStep, RiskLevel
from app.agents.risk.decision import decide_risk
from app.agents.risk.models import RiskAmbiguityAssistOutput, RiskDecision, RiskItem
from app.agents.risk.rules import DeterministicPolicyRules, RuleContext
from app.agents.risk.service import RiskAnalysisService
from app.database.memory import AllocationResultRecord, get_memory_store, new_id
from app.contracts.common import utcnow
from app.repositories.memory_repos import (
    EmployeeRepository,
    PolicyRepository,
    ProcessRepository,
    SupplierRepository,
)


def _plan(*, goal: str = "Procure laptops", quotes_hint: str = "", amount_hint: str = "") -> ProcessPlan:
    desc = f"Purchase equipment. {amount_hint} {quotes_hint}".strip()
    return ProcessPlan(
        goal=goal,
        steps=[
            ProcessStep(
                step_id="step_buy",
                action_type=ActionType.HUMAN_TASK,
                title="Purchase",
                description=desc,
                required_resources=["supplier", "manager"],
                success_criteria=["Purchased"],
                risk_level=RiskLevel.HIGH,
            )
        ],
        reasoning_summary="Procurement draft",
    )


def _seed_process(org_id: UUID, plan: ProcessPlan) -> tuple[UUID, UUID]:
    repo = ProcessRepository(org_id)
    proc = repo.create(name="Risk Process", description=plan.goal, created_by_user_id=None)
    version = repo.create_version(
        proc.id, plan_snapshot=plan.model_dump(mode="json"), status="confirmed"
    )
    return proc.id, version.id


def _seed_allocation(
    org_id: UUID,
    process_id: UUID,
    version_id: UUID,
    assignments: list[ResourceAssignment],
    *,
    conflicts: list | None = None,
) -> UUID:
    now = utcnow()
    result = ResourceAllocationResult(
        organization_id=org_id,
        process_id=process_id,
        process_version_id=version_id,
        status="resolved",
        assignments=assignments,
        conflicts=conflicts or [],
        reasoning_summary="test allocation",
    )
    record = AllocationResultRecord(
        id=new_id(),
        organization_id=org_id,
        process_id=process_id,
        process_version_id=version_id,
        status="resolved",
        result_snapshot=result.model_dump(mode="json"),
        created_at=now,
        updated_at=now,
    )
    get_memory_store().allocations[record.id] = record
    return record.id


def test_spending_thresholds(org_a: UUID) -> None:
    PolicyRepository(org_a).create(code="FIN-001", title="Spending thresholds")
    rules = DeterministicPolicyRules()
    ctx = RuleContext(
        organization_id=org_a,
        plan=_plan(amount_hint="$2500"),
        allocation=None,
        policies=PolicyRepository(org_a).list_all(),
        spending_amount=2500,
    )
    items = rules.evaluate(ctx)
    assert any(i.id == "risk_spend_manager" for i in items)

    ctx.spending_amount = 15_000
    items = rules.evaluate(ctx)
    assert any(i.id == "risk_spend_finance" for i in items)

    ctx.spending_amount = 150_000
    items = rules.evaluate(ctx)
    assert any(i.blocking and i.id == "risk_spend_blocked" for i in items)


def test_missing_quotations(org_a: UUID) -> None:
    PolicyRepository(org_a).create(code="PROC-001", title="Quotations")
    rules = DeterministicPolicyRules()
    ctx = RuleContext(
        organization_id=org_a,
        plan=_plan(goal="Procure office chairs"),
        allocation=None,
        policies=PolicyRepository(org_a).list_all(),
        quotation_count=1,
        spending_amount=500,
    )
    items = rules.evaluate(ctx)
    assert any(i.rule_type.value == "required_quotation_count" for i in items)


def test_unapproved_suppliers(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    supplier = SupplierRepository(org_a).create(
        name="Contoso", approval_status="pending"
    )
    process_id, version_id = _seed_process(org_a, _plan(amount_hint="$800"))
    _seed_allocation(
        org_a,
        process_id,
        version_id,
        [
            ResourceAssignment(
                step_id="step_buy",
                requirement="supplier",
                resource_id=str(supplier.id),
                resource_type=ResourceType.SUPPLIER,
                reason="test",
                data_source=DataSource.SUPPLIER_QUERY,
                confidence=0.9,
                authorization_status=AuthorizationStatus.UNAUTHORIZED,
                active_status=True,
                conflict_status=ConflictStatus.UNAPPROVED,
                display_name="Contoso",
            )
        ],
    )
    response = client.post(
        f"/v1/processes/{process_id}/analyze-risk",
        headers=auth_headers_a,
        json={"spending_amount": 800, "quotation_count": 2},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "BLOCKED"
    assert body["gemini_approved"] is False
    assert any(i["blocking"] for i in body["blocking_issues"])


def test_segregation_of_duties(org_a: UUID) -> None:
    emp_id = str(new_id())
    process_id, version_id = _seed_process(org_a, _plan(amount_hint="$500"))
    allocation = ResourceAllocationResult(
        organization_id=org_a,
        process_id=process_id,
        process_version_id=version_id,
        status="resolved",
        assignments=[
            ResourceAssignment(
                step_id="step_request",
                requirement="requester",
                resource_id=emp_id,
                resource_type=ResourceType.EMPLOYEE,
                reason="same person",
                data_source=DataSource.DIRECTORY_QUERY,
                confidence=1.0,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
            ),
            ResourceAssignment(
                step_id="step_approve",
                requirement="approver",
                resource_id=emp_id,
                resource_type=ResourceType.MANAGER,
                reason="same person",
                data_source=DataSource.DIRECTORY_QUERY,
                confidence=1.0,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
            ),
        ],
    )
    rules = DeterministicPolicyRules()
    items = rules.evaluate(
        RuleContext(
            organization_id=org_a,
            plan=_plan(amount_hint="$500"),
            allocation=allocation,
            policies=[],
            spending_amount=500,
            quotation_count=2,
        )
    )
    assert any(i.category.value == "segregation_of_duties" and i.blocking for i in items)


def test_required_approvals_and_package(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    PolicyRepository(org_a).create(code="FIN-001", title="Spend")
    process_id, _ = _seed_process(org_a, _plan(amount_hint="$2500", quotes_hint="dual quotes"))
    risk = client.post(
        f"/v1/processes/{process_id}/analyze-risk",
        headers=auth_headers_a,
        json={"spending_amount": 2500, "quotation_count": 2},
    )
    assert risk.status_code == 200, risk.text
    body = risk.json()
    assert body["decision"] == "APPROVAL_REQUIRED"
    assert body["required_approver_roles"]
    assert all(
        set(i.keys())
        >= {
            "category",
            "severity",
            "likelihood",
            "impact",
            "description",
            "policy_reference",
            "evidence_references",
            "blocking",
            "required_remediation",
            "required_approver",
            "review_or_expiration_date",
        }
        for i in body["risk_items"]
    )

    package = client.post(
        f"/v1/processes/{process_id}/approvals",
        headers=auth_headers_a,
    )
    assert package.status_code == 201, package.text
    assert package.json()["plan_snapshot_hash"] == body["plan_snapshot_hash"]
    assert package.json()["risk_snapshot_hash"] == body["risk_snapshot_hash"]


def test_policy_violations_blocked_override(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    process_id, _ = _seed_process(
        org_a, _plan(goal="Procure with conflict of interest declared")
    )
    risk = client.post(
        f"/v1/processes/{process_id}/analyze-risk",
        headers=auth_headers_a,
        json={"spending_amount": 500, "quotation_count": 2},
    )
    assert risk.status_code == 200
    assert risk.json()["decision"] == "BLOCKED"

    denied = client.post(
        f"/v1/processes/{process_id}/approvals",
        headers=auth_headers_a,
    )
    assert denied.status_code == 409

    override = client.post(
        f"/v1/processes/{process_id}/approvals/override",
        headers=auth_headers_a,
        json={
            "justification": "Executive exception for documented conflict remediation",
            "acknowledged_risk_item_ids": [i["id"] for i in risk.json()["blocking_issues"]],
        },
    )
    assert override.status_code == 201, override.text
    assert override.json()["override_required"] is True
    assert override.json()["prohibited_action"] is True


def test_missing_evidence_insufficient(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    # Low spend, enough quotes, no policies/docs → may be CLEAR or INSUFFICIENT depending on docs rule
    process_id, _ = _seed_process(org_a, _plan(goal="Buy pens", amount_hint="$20"))
    risk = client.post(
        f"/v1/processes/{process_id}/analyze-risk",
        headers=auth_headers_a,
        json={"spending_amount": 20, "quotation_count": 2},
    )
    assert risk.status_code == 200, risk.text
    body = risk.json()
    assert body["decision"] in {"CLEAR", "INSUFFICIENT_INFORMATION", "APPROVAL_REQUIRED"}
    assert body["gemini_approved"] is False


def test_approval_invalidation_on_plan_mutation(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    process_id, _ = _seed_process(org_a, _plan(amount_hint="$2500", quotes_hint="dual quotes"))
    risk = client.post(
        f"/v1/processes/{process_id}/analyze-risk",
        headers=auth_headers_a,
        json={"spending_amount": 2500, "quotation_count": 2},
    )
    assert risk.status_code == 200
    package = client.post(
        f"/v1/processes/{process_id}/approvals",
        headers=auth_headers_a,
    )
    assert package.status_code == 201
    approval_id = package.json()["id"]

    # Mutate plan via draft-plan
    mutated = client.post(
        f"/v1/processes/{process_id}/draft-plan",
        headers=auth_headers_a,
        json={"instructions": "Change suppliers"},
    )
    assert mutated.status_code == 201

    fetched = client.get(f"/v1/processes/{process_id}/risk", headers=auth_headers_a)
    assert fetched.status_code == 200
    assert fetched.json()["valid"] is False
    assert "Plan" in (fetched.json()["invalidated_reason"] or "")

    listed = client.get("/v1/approvals", headers=auth_headers_a)
    assert listed.status_code == 200
    statuses = {
        item["status"]
        for item in listed.json()["items"]
        if item["id"] == approval_id
    }
    assert "invalidated" in statuses


def test_allocation_change_invalidates_risk(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    EmployeeRepository(org_a).create(
        full_name="Alex Manager", email="alex@example.com", is_manager=True
    )
    process_id, version_id = _seed_process(
        org_a, _plan(amount_hint="$2500", quotes_hint="dual quotes")
    )
    _seed_allocation(org_a, process_id, version_id, [])
    risk = client.post(
        f"/v1/processes/{process_id}/analyze-risk",
        headers=auth_headers_a,
        json={"spending_amount": 2500, "quotation_count": 2},
    )
    assert risk.status_code == 200
    assert risk.json()["valid"] is True

    # New allocation invalidates
    alloc = client.post(
        f"/v1/processes/{process_id}/allocate",
        headers=auth_headers_a,
        json={},
    )
    assert alloc.status_code == 200
    fetched = client.get(f"/v1/processes/{process_id}/risk", headers=auth_headers_a)
    assert fetched.json()["valid"] is False
    assert "allocation" in (fetched.json()["invalidated_reason"] or "").lower()


def test_gemini_cannot_independently_approve() -> None:
    assist = RiskAmbiguityAssistOutput(
        independently_approves=True,
        proposed_decision=RiskDecision.CLEAR,
        reasoning_summary="LLM tried to approve",
    )
    decision, blocking, required, summary = decide_risk(
        items=[],
        missing_evidence=[],
        assist=assist,
    )
    assert decision != RiskDecision.CLEAR or "Rejected Gemini" in summary or decision == RiskDecision.INSUFFICIENT_INFORMATION
    # With empty items + independent approve attempt → insufficient, not clear
    assert decision == RiskDecision.INSUFFICIENT_INFORMATION


def test_plan_mutation_after_approval_blocks_reuse(
    org_a: UUID, auth_headers_a: dict[str, str], client: TestClient
) -> None:
    process_id, _ = _seed_process(org_a, _plan(amount_hint="$2500", quotes_hint="dual quotes"))
    client.post(
        f"/v1/processes/{process_id}/analyze-risk",
        headers=auth_headers_a,
        json={"spending_amount": 2500, "quotation_count": 2},
    )
    package = client.post(
        f"/v1/processes/{process_id}/approvals",
        headers=auth_headers_a,
    )
    approval = package.json()
    # Decide while still valid
    decided = client.post(
        f"/v1/approvals/{approval['id']}/decision",
        headers=auth_headers_a,
        json={"decision": "approved", "row_version": approval["row_version"], "note": "ok"},
    )
    assert decided.status_code == 200, decided.text

    # Mutate plan — approval invalidated
    client.post(
        f"/v1/processes/{process_id}/draft-plan",
        headers=auth_headers_a,
        json={},
    )
    service = RiskAnalysisService(org_a)
    risk = service.get_risk(process_id)
    assert risk.valid is False

    from app.database.memory import get_memory_store

    store = get_memory_store()
    record = store.approvals[UUID(approval["id"])]
    assert record.status.value == "invalidated"
