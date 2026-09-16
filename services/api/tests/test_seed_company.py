"""Sample company seed tests."""

from __future__ import annotations

from app.database.memory import reset_memory_store, get_memory_store
from app.database.seed_company import EMP_OWNER, SUP_NORTHWIND, seed_sample_company
from app.domain.enums import MembershipStatus, OrgRole
from app.database.memory import MembershipRecord, OrganizationRecord
from app.contracts.common import utcnow
from uuid import UUID


def test_seed_sample_company_is_idempotent() -> None:
    reset_memory_store()
    store = get_memory_store()
    org_id = UUID("76ec608f-37a4-45fa-bb58-fb81c0710720")
    user_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    now = utcnow()
    store.organizations[org_id] = OrganizationRecord(
        id=org_id,
        name="Acme Corporation",
        slug="acme-corporation",
        plan_code="enterprise",
        status="active",
        row_version=1,
        created_at=now,
        updated_at=now,
    )
    store.memberships[UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")] = MembershipRecord(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        organization_id=org_id,
        user_id=user_id,
        role=OrgRole.OWNER,
        status=MembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )

    seed_sample_company(store, organization_id=org_id, user_id=user_id, include_process=False)
    seed_sample_company(store, organization_id=org_id, user_id=user_id, include_process=False)

    assert len(store.employees) == 8
    assert EMP_OWNER in store.employees
    assert len(store.suppliers) == 4
    assert SUP_NORTHWIND in store.suppliers
    assert len(store.departments) == 5
    assert len(store.policies) == 3
    assert len(store.budgets) == 2
    assert store.organizations[org_id].legal_name == "Acme Corporation Inc."
