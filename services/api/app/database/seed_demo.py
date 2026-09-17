"""Idempotent demo process seed for local development (in-memory mode)."""

from __future__ import annotations

from uuid import UUID

from app.agents.discovery.models import PlanSourceReference, plan_to_snapshot
from app.agents.discovery.service import DiscoveryService
from app.database.memory import MemoryStore, get_memory_store
from app.domain.enums import OrgRole
from app.permissions.codes import permissions_for_role
from app.repositories.memory_repos import ProcessRepository

DEFAULT_ORG_ID = UUID("76ec608f-37a4-45fa-bb58-fb81c0710720")
DEFAULT_USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

DEMO_PROCESS_NAME = "Laptop procurement"
DEMO_PROCESS_DESCRIPTION = "Sample procurement process for local testing"
DEMO_USER_MESSAGE = (
    "We need to buy 5 laptops for new engineers. Budget is $2,500 total. "
    "Manager approval required. Get dual quotes from approved suppliers before purchase."
)


def seed_demo_processes(
    store: MemoryStore | None = None,
    *,
    organization_id: UUID = DEFAULT_ORG_ID,
    user_id: UUID = DEFAULT_USER_ID,
) -> None:
    """Ensure a sample discovery process + draft plan exists after API restarts."""
    store = store or get_memory_store()
    repo = ProcessRepository(organization_id, store)

    if any(p.name == DEMO_PROCESS_NAME for p in repo.list_all()):
        return

    process = repo.create(
        name=DEMO_PROCESS_NAME,
        description=DEMO_PROCESS_DESCRIPTION,
        created_by_user_id=user_id,
    )

    service = DiscoveryService(organization_id)
    session = service.get_or_create_session(process.id, user_id=user_id)
    source_refs = [
        PlanSourceReference(
            type="user",
            id=str(session.id),
            label="Discovery request",
        )
    ]

    service._append_message(
        process_id=process.id,
        session_id=session.id,
        role="user",
        content=DEMO_USER_MESSAGE,
        user_id=user_id,
        source_refs=[ref.model_dump(mode="json") for ref in source_refs],
    )
    service._append_message(
        process_id=process.id,
        session_id=session.id,
        role="assistant",
        content=(
            "I captured the laptop procurement request with budget, manager approval, "
            "and dual-quote requirements. A draft plan is ready for review."
        ),
        user_id=None,
        intent={
            "goal": (
                "Procure 5 laptops for new engineers within a $2,500 budget, "
                "with manager approval and dual quotes from approved suppliers."
            ),
            "actors": ["Procurement Officer", "Manager", "Approved Suppliers"],
            "systems": ["bpm_platform"],
        },
        source_refs=[ref.model_dump(mode="json") for ref in source_refs],
    )

    plan = service._heuristic_plan(DEMO_USER_MESSAGE, source_refs, None)
    repo.create_version(
        process.id,
        plan_snapshot=plan_to_snapshot(plan),
        status="draft",
    )


AGENT4_PROCESS_NAME = "Enterprise Hardware Procurement (Agent 4 Ready)"
AGENT4_PROCESS_DESC = "Pre-approved procurement process ready for autonomous or step-by-step execution by Agent 4."


def seed_agent4_demo_process(
    store: MemoryStore | None = None,
    *,
    organization_id: UUID = DEFAULT_ORG_ID,
    user_id: UUID = DEFAULT_USER_ID,
) -> None:
    """Seed a fully pre-approved process ready to test Agent 4 execution."""
    from app.agents.allocation.service import AllocationService
    from app.agents.discovery.models import ActionType, ProcessPlan, ProcessStep, RiskLevel
    from app.agents.risk.models import AnalyzeRiskRequest
    from app.agents.risk.service import RiskAnalysisService
    from app.contracts.common import utcnow
    from app.domain.enums import ApprovalStatus

    store = store or get_memory_store()
    repo = ProcessRepository(organization_id, store)

    if any(p.name == AGENT4_PROCESS_NAME for p in repo.list_all()):
        return

    proc = repo.create(
        name=AGENT4_PROCESS_NAME,
        description=AGENT4_PROCESS_DESC,
        created_by_user_id=user_id,
    )

    steps = [
        ProcessStep(
            step_id="step_discovery",
            action_type=ActionType.COLLECT_INFO,
            title="Identify Staff & Suppliers",
            description="Discover procurement officers, IT managers, and approved hardware vendors in company directory.",
            required_resources=["employee", "manager", "supplier"],
            allowed_tools=[
                "company.employee_lookup",
                "company.manager_lookup",
                "supplier.search",
                "supplier.contact_lookup",
                "supplier.approved_status",
            ],
            success_criteria=["Suppliers verified", "Staff identified"],
            risk_level=RiskLevel.LOW,
        ),
        ProcessStep(
            step_id="step_rfq",
            action_type=ActionType.HUMAN_TASK,
            title="Request & Collect Dual Quotations",
            description="Issue formal RFQs to approved vendors and extract quotation details for comparison.",
            required_resources=["supplier", "procurement_officer"],
            allowed_tools=[
                "supplier.request_quote",
                "supplier.collect_quote",
                "quotation.extract",
                "quotation.normalize",
                "quotation.compare",
                "email.send",
                "email.create_draft",
            ],
            success_criteria=["Dual quotes obtained and ranked"],
            risk_level=RiskLevel.MEDIUM,
        ),
        ProcessStep(
            step_id="step_order_and_notify",
            action_type=ActionType.INTEGRATION,
            title="Issue Purchase Order & Stakeholder Notice",
            description="Generate purchase order, dispatch supplier contract, and notify management and employees.",
            required_resources=["supplier", "finance_manager"],
            allowed_tools=[
                "purchase_order.create_draft",
                "purchase_order.submit",
                "document.generate",
                "notification.send",
                "calendar.create_event",
                "task.assign",
            ],
            success_criteria=["Purchase order submitted", "Confirmation notices dispatched"],
            risk_level=RiskLevel.HIGH,
        ),
    ]

    plan = ProcessPlan(
        goal="Procure 5 high-performance laptops with dual supplier quotations under $2,500 budget",
        steps=steps,
    )

    version = repo.create_version(
        proc.id,
        plan_snapshot=plan_to_snapshot(plan),
        status="confirmed",
    )

    # 1. Run Agent 2 (Allocation)
    try:
        alloc_service = AllocationService(organization_id)
        alloc_service.allocate(
            proc.id,
            user_id=user_id,
            correlation_id="seed-agent4",
            permissions=permissions_for_role(OrgRole.OWNER),
        )
    except Exception:
        pass

    # 2. Run Agent 3 (Risk Analysis)
    try:
        risk_service = RiskAnalysisService(organization_id)
        risk = risk_service.analyze(
            proc.id,
            user_id=user_id,
            correlation_id="seed-agent4",
            permissions=permissions_for_role(OrgRole.OWNER),
            request=AnalyzeRiskRequest(spending_amount=2500, quotation_count=2),
        )

        # 3. Create & Approve package
        package = risk_service.create_approval_package(
            proc.id,
            user_id=user_id,
            correlation_id="seed-agent4",
        )
        if package.id in store.approvals:
            record = store.approvals[package.id]
            record.status = ApprovalStatus.APPROVED
            record.decided_by_user_id = user_id
            record.decision_note = "Pre-approved sample process for Agent 4 execution testing."
            record.updated_at = utcnow()
    except Exception:
        pass
