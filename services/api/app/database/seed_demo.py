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
