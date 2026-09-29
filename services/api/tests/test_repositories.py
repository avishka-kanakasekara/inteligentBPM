"""Unit and integration tests for memory and tenant-scoped repositories."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.database.memory import (
    get_memory_store,
    reset_memory_store,
)
from app.domain.enums import (
    ApprovalStatus,
    DocumentStatus,
    OrgRole,
    ProcessRunStatus,
)
from app.repositories.memory_repos import (
    ApprovalRepository,
    AuditRepository,
    DocumentRepository,
    EmployeeRepository,
    IdempotencyRepository,
    OrganizationRepository,
    ProcessRepository,
    ProcessRunRepository,
    SupplierContactRepository,
    SupplierProductRepository,
    SupplierRepository,
)
from app.security.errors import ConflictError, NotFoundError


@pytest.fixture(autouse=True)
def _clean_store() -> None:
    reset_memory_store()
    yield
    reset_memory_store()


def test_organization_repository_lifecycle() -> None:
    repo = OrganizationRepository()
    owner_id = uuid4()
    org = repo.create(name="Acme Corp", plan_code="pro", owner_user_id=owner_id)
    assert org.name == "Acme Corp"
    assert org.slug == "acme-corp"

    found = repo.get(org.id)
    assert found is not None
    assert found.id == org.id

    user_orgs = repo.list_for_user(owner_id)
    assert len(user_orgs) == 1
    assert user_orgs[0][0].id == org.id
    assert user_orgs[0][1].role == OrgRole.OWNER


def test_employee_repository_crud_and_tenant_isolation() -> None:
    org_1 = uuid4()
    org_2 = uuid4()
    repo_1 = EmployeeRepository(org_1)
    repo_2 = EmployeeRepository(org_2)

    emp1 = repo_1.create(
        full_name="Alice Smith",
        email="emp1@example.com",
        title="Procurement Specialist",
        status="active",
    )
    assert emp1.organization_id == org_1
    assert emp1.email == "emp1@example.com"

    # Verify repo_2 cannot see emp1
    with pytest.raises(NotFoundError):
        repo_2.get(emp1.id)
    assert len(repo_2.list_all()) == 0
    assert len(repo_1.list_all()) == 1

    # Conflict on duplicate email in same tenant when checked
    with pytest.raises(ConflictError):
        repo_1.assert_no_active_email_duplicate("emp1@example.com")

    # Allowed in different tenant
    emp2 = repo_2.create(
        full_name="Bob Jones",
        email="emp1@example.com",
    )
    assert emp2.organization_id == org_2

    # Update
    updated = repo_1.update(emp1.id, title="Lead Specialist")
    assert updated.title == "Lead Specialist"


def test_supplier_repository_lifecycle() -> None:
    org_id = uuid4()
    sup_repo = SupplierRepository(org_id)
    contact_repo = SupplierContactRepository(org_id)
    prod_repo = SupplierProductRepository(org_id)

    supplier = sup_repo.create(
        name="Global Tech Supplies",
        code="GTS-001",
        approval_status="approved",
    )
    assert supplier.id is not None
    assert supplier.approval_status == "approved"

    contact = contact_repo.create(
        supplier_id=supplier.id,
        full_name="Jane Doe",
        email="jane@globaltech.com",
        is_primary=True,
    )
    assert contact.full_name == "Jane Doe"

    product = prod_repo.create(
        supplier_id=supplier.id,
        sku="LAPTOP-PRO-16",
        name="16-inch Workstation Laptop",
        unit_price=2100.0,
        currency_code="USD",
    )
    assert product.sku == "LAPTOP-PRO-16"

    found = sup_repo.get(supplier.id)
    assert found is not None
    contacts = contact_repo.list_all(supplier.id)
    assert len(contacts) == 1
    assert contacts[0].email == "jane@globaltech.com"
    products = prod_repo.list_all(supplier.id)
    assert len(products) == 1
    assert products[0].sku == "LAPTOP-PRO-16"


def test_document_repository_lifecycle() -> None:
    org_id = uuid4()
    repo = DocumentRepository(org_id)
    user_id = uuid4()

    doc = repo.create(
        title="Procurement Policy 2026",
        file_name="policy_2026.pdf",
        mime_type="application/pdf",
        byte_size=10240,
        storage_path=f"{org_id}/docs/policy_2026.pdf",
        uploaded_by_user_id=user_id,
    )
    assert doc.status == DocumentStatus.UPLOADED

    doc_ready = repo.get(doc.id)
    assert doc_ready is not None
    assert doc_ready.storage_path == f"{org_id}/docs/policy_2026.pdf"


def test_process_repository_and_versions() -> None:
    org_id = uuid4()
    repo = ProcessRepository(org_id)
    user_id = uuid4()

    process = repo.create(
        name="Hardware Procurement Flow",
        description="Standard procurement for IT equipment",
        created_by_user_id=user_id,
    )
    assert process.name == "Hardware Procurement Flow"

    v1 = repo.create_version(
        process.id,
        plan_snapshot={"steps": ["quote", "approve", "purchase"]},
        status="active",
    )
    assert v1.version_number == 1

    versions = repo.list_versions(process.id)
    assert len(versions) == 1
    assert versions[0].id == v1.id


def test_approval_repository_decision_lifecycle() -> None:
    org_id = uuid4()
    repo = ApprovalRepository(org_id)
    plan_id = uuid4()
    run_id = uuid4()
    user_id = uuid4()

    store = get_memory_store()
    from app.contracts.common import utcnow
    from app.database.memory import ApprovalRecord, new_id

    app_id = new_id()
    now = utcnow()
    approval = ApprovalRecord(
        id=app_id,
        organization_id=org_id,
        process_run_id=run_id,
        process_version_id=plan_id,
        status=ApprovalStatus.PENDING,
        snapshot_hash="hash123",
        snapshot_payload={"plan": "v1"},
        decided_by_user_id=None,
        decision_note=None,
        row_version=1,
        created_at=now,
        updated_at=now,
    )
    store.approvals[app_id] = approval

    decided = repo.decide(
        approval_id=app_id,
        decision="approved",
        decided_by_user_id=user_id,
        note="Approved by Finance",
        expected_row_version=1,
    )
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decided_by_user_id == user_id
    assert decided.row_version == 2


def test_process_run_repository_lifecycle() -> None:
    org_id = uuid4()
    proc_repo = ProcessRepository(org_id)
    run_repo = ProcessRunRepository(org_id)
    user_id = uuid4()

    proc = proc_repo.create(name="Procurement", description=None, created_by_user_id=user_id)
    v1 = proc_repo.create_version(proc.id, plan_snapshot={"steps": []})

    run = run_repo.create(
        process_id=proc.id,
        process_version_id=v1.id,
        initiated_by_user_id=user_id,
        correlation_id="corr-1234",
    )
    assert run.status == ProcessRunStatus.DRAFT

    all_runs = run_repo.list_all()
    assert len(all_runs) == 1
    assert all_runs[0].id == run.id


def test_audit_event_repository() -> None:
    org_id = uuid4()
    repo = AuditRepository()
    actor_id = uuid4()
    entity_id = uuid4()

    event = repo.append(
        organization_id=org_id,
        actor_user_id=actor_id,
        action="approval.decided",
        resource_type="approval",
        resource_id=entity_id,
        correlation_id="corr-audit-1",
        payload={"decision": "approved"},
    )
    assert event.id is not None
    assert event.action == "approval.decided"

    events = repo.list_for_org(org_id)
    assert len(events) == 1
    assert events[0].resource_id == entity_id


def test_idempotency_repository() -> None:
    org_id = uuid4()
    repo = IdempotencyRepository()

    key = "idem-test-9999"
    repo.begin(
        organization_id=org_id,
        scope="process_runs",
        key=key,
        request_hash="hash-req-1",
    )

    repo.complete(
        organization_id=org_id,
        scope="process_runs",
        key=key,
        response_status=201,
        response_body={"run_id": "r1"},
    )

    cached = repo.get(organization_id=org_id, scope="process_runs", key=key)
    assert cached is not None
    assert cached.response_status == 201
    assert cached.response_body["run_id"] == "r1"
