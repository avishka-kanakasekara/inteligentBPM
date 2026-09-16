"""In-memory persistence for local/test foundation without requiring live Postgres."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from app.domain.enums import (
    ApprovalStatus,
    DocumentStatus,
    MembershipStatus,
    OrgRole,
    ProcessRunStatus,
)


@dataclass
class OrganizationRecord:
    id: UUID
    name: str
    slug: str
    plan_code: str
    status: str
    row_version: int
    created_at: datetime
    updated_at: datetime
    legal_name: str | None = None
    trading_name: str | None = None
    industry: str | None = None
    country_code: str | None = None
    tax_id: str | None = None
    tax_registration: str | None = None
    tax_country_code: str | None = None
    default_timezone: str = "UTC"
    default_currency: str = "USD"
    tax_information: dict[str, Any] = field(default_factory=dict)


@dataclass
class MembershipRecord:
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: OrgRole
    status: MembershipStatus
    created_at: datetime
    updated_at: datetime


@dataclass
class EmployeeRecord:
    id: UUID
    organization_id: UUID
    full_name: str
    email: str
    title: str | None
    department_id: UUID | None
    is_manager: bool
    status: str
    created_at: datetime
    updated_at: datetime
    employee_code: str | None = None
    role_code: str | None = None
    approval_authority_limit: float | None = None
    approval_authority_currency: str = "USD"


@dataclass
class EmployeeManagerLinkRecord:
    id: UUID
    organization_id: UUID
    employee_id: UUID
    manager_employee_id: UUID
    link_type: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass
class DepartmentRecord:
    id: UUID
    organization_id: UUID
    name: str
    code: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    parent_department_id: UUID | None = None
    manager_employee_id: UUID | None = None


@dataclass
class CostCenterRecord:
    id: UUID
    organization_id: UUID
    code: str
    name: str
    department_id: UUID | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass
class SupplierRecord:
    id: UUID
    organization_id: UUID
    name: str
    code: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    approval_status: str = "pending"
    website: str | None = None
    country_code: str | None = None


@dataclass
class SupplierContactRecord:
    id: UUID
    organization_id: UUID
    supplier_id: UUID
    full_name: str
    email: str | None
    is_primary: bool
    status: str
    created_at: datetime
    updated_at: datetime
    phone: str | None = None
    role_title: str | None = None
    allow_duplicate_email: bool = False


@dataclass
class SupplierProductRecord:
    id: UUID
    organization_id: UUID
    supplier_id: UUID
    name: str
    sku: str | None
    unit_price: float | None
    currency_code: str
    status: str
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    unit_of_measure: str | None = None


@dataclass
class BudgetRecord:
    id: UUID
    organization_id: UUID
    name: str
    fiscal_year: int
    amount_total: float
    currency_code: str
    status: str
    created_at: datetime
    updated_at: datetime
    department_id: UUID | None = None
    cost_center_id: UUID | None = None


@dataclass
class PolicyRecord:
    id: UUID
    organization_id: UUID
    code: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    category: str | None = None
    description: str | None = None
    owner_employee_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentRecord:
    id: UUID
    organization_id: UUID
    title: str
    storage_path: str
    status: DocumentStatus
    uploaded_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    file_name: str | None = None
    mime_type: str | None = None
    byte_size: int | None = None
    content_hash: str | None = None
    version_number: int = 1
    source_type: str = "upload"
    classification: str = "internal"
    access_scope: str = "organization"
    document_type: str = "general"
    owner_user_id: UUID | None = None
    created_by_user_id: UUID | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    page_count: int | None = None
    section_count: int | None = None
    chunk_count: int = 0
    failure_reason: str | None = None
    suspicious_flags: list[str] = field(default_factory=list)
    redacted: bool = False
    storage_bucket: str = "documents"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentChunkRecord:
    id: UUID
    organization_id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    created_at: datetime
    updated_at: datetime
    embedding: list[float] | None = None
    token_count: int | None = None
    page_number: int | None = None
    section_heading: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    embedding_model: str | None = None
    is_redacted: bool = False
    suspicious: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StoredObjectRecord:
    """In-memory private object store for foundation/tests."""

    organization_id: UUID
    path: str
    content: bytes
    content_type: str
    created_at: datetime


@dataclass
class ProcessDefinitionRecord:
    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    status: str
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ProcessVersionRecord:
    id: UUID
    organization_id: UUID
    process_id: UUID
    version_number: int
    plan_snapshot: dict[str, Any]
    plan_snapshot_hash: str
    status: str
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None = None
    confirmed_by_user_id: UUID | None = None
    is_immutable: bool = False
    parent_version_id: UUID | None = None


@dataclass
class DiscoverySessionRecord:
    id: UUID
    organization_id: UUID
    process_id: UUID
    status: str
    created_by_user_id: UUID | None
    document_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


@dataclass
class DiscoveryMessageRecord:
    id: UUID
    organization_id: UUID
    process_id: UUID
    session_id: UUID
    role: str
    content: str
    document_ids: list[UUID]
    clarifying_questions: list[str]
    intent: dict[str, Any] | None
    plan_draft: dict[str, Any] | None
    source_refs: list[dict[str, Any]]
    suspicious_flags: list[str]
    created_by_user_id: UUID | None
    created_at: datetime


@dataclass
class AllocationResultRecord:
    id: UUID
    organization_id: UUID
    process_id: UUID
    process_version_id: UUID
    status: str
    result_snapshot: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass
class RiskResultRecord:
    id: UUID
    organization_id: UUID
    process_id: UUID
    process_version_id: UUID
    allocation_id: UUID | None
    status: str
    result_snapshot: dict[str, Any]
    plan_snapshot_hash: str
    allocation_snapshot_hash: str | None
    risk_snapshot_hash: str
    valid: bool
    invalidated_reason: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ApprovalRecord:
    id: UUID
    organization_id: UUID
    process_run_id: UUID | None
    status: ApprovalStatus
    snapshot_hash: str
    snapshot_payload: dict[str, Any]
    decided_by_user_id: UUID | None
    decision_note: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    process_id: UUID | None = None
    process_version_id: UUID | None = None
    risk_result_id: UUID | None = None
    plan_snapshot_hash: str | None = None
    allocation_snapshot_hash: str | None = None
    risk_snapshot_hash: str | None = None
    required_roles: list[str] = field(default_factory=list)
    prohibited_action: bool = False
    override_required: bool = False
    # Workflow approval wait fields (durable orchestration)
    requested_role: str | None = None
    requested_user: UUID | None = None
    decision: str | None = None
    decision_reason: str | None = None
    requested_timestamp: datetime | None = None
    decision_timestamp: datetime | None = None
    expiration_timestamp: datetime | None = None
    audit_reference: str | None = None
    risk_analysis_id: UUID | None = None


@dataclass
class ProcessRunRecord:
    id: UUID
    organization_id: UUID
    process_id: UUID
    process_version_id: UUID | None
    status: ProcessRunStatus
    initiated_by_user_id: UUID | None
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime
    plan_snapshot_hash: str | None = None
    risk_snapshot_hash: str | None = None
    approval_id: UUID | None = None
    dry_run: bool = False
    current_step_index: int = 0
    pause_reason: str | None = None
    allowed_tools: list[str] = field(default_factory=list)


@dataclass
class AuditEventRecord:
    id: UUID
    organization_id: UUID
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    correlation_id: str | None
    payload: dict[str, Any]
    created_at: datetime


@dataclass
class IdempotencyRecord:
    organization_id: UUID
    scope: str
    key: str
    request_hash: str
    status: str
    response_status: int | None
    response_body: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@dataclass
class MemoryStore:
    organizations: dict[UUID, OrganizationRecord] = field(default_factory=dict)
    memberships: dict[UUID, MembershipRecord] = field(default_factory=dict)
    employees: dict[UUID, EmployeeRecord] = field(default_factory=dict)
    employee_manager_links: dict[UUID, EmployeeManagerLinkRecord] = field(default_factory=dict)
    departments: dict[UUID, DepartmentRecord] = field(default_factory=dict)
    cost_centers: dict[UUID, CostCenterRecord] = field(default_factory=dict)
    suppliers: dict[UUID, SupplierRecord] = field(default_factory=dict)
    supplier_contacts: dict[UUID, SupplierContactRecord] = field(default_factory=dict)
    supplier_products: dict[UUID, SupplierProductRecord] = field(default_factory=dict)
    budgets: dict[UUID, BudgetRecord] = field(default_factory=dict)
    policies: dict[UUID, PolicyRecord] = field(default_factory=dict)
    documents: dict[UUID, DocumentRecord] = field(default_factory=dict)
    document_chunks: dict[UUID, DocumentChunkRecord] = field(default_factory=dict)
    stored_objects: dict[str, StoredObjectRecord] = field(default_factory=dict)
    processes: dict[UUID, ProcessDefinitionRecord] = field(default_factory=dict)
    process_versions: dict[UUID, ProcessVersionRecord] = field(default_factory=dict)
    discovery_sessions: dict[UUID, DiscoverySessionRecord] = field(default_factory=dict)
    discovery_messages: dict[UUID, DiscoveryMessageRecord] = field(default_factory=dict)
    discovery_events: dict[UUID, list[dict[str, Any]]] = field(default_factory=dict)
    allocations: dict[UUID, AllocationResultRecord] = field(default_factory=dict)
    risk_results: dict[UUID, RiskResultRecord] = field(default_factory=dict)
    approvals: dict[UUID, ApprovalRecord] = field(default_factory=dict)
    process_runs: dict[UUID, ProcessRunRecord] = field(default_factory=dict)
    tool_invocations: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    email_outbox: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    quote_requests: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    quotations: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    purchase_orders: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    notifications: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    tasks: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    generated_documents: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    audit_events: list[AuditEventRecord] = field(default_factory=list)
    idempotency: dict[tuple[UUID, str, str], IdempotencyRecord] = field(default_factory=dict)
    run_events: dict[UUID, list[dict[str, Any]]] = field(default_factory=dict)
    # Durable workflow orchestration (mock Temporal / Temporal Cloud bridge)
    workflow_instances: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    workflow_outbox: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    workflow_inbox: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_run_records: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    workflow_dead_letters: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    workflow_trace_index: dict[str, UUID] = field(default_factory=dict)
    # Integration adapters (encrypted secrets + provider side caches)
    encrypted_credentials: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    email_threads: dict[str, list[str]] = field(default_factory=dict)
    billing_usage: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    calendar_events: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    # Subscriptions & entitlements
    plan_entitlements: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    subscriptions: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    usage_events: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    billing_webhook_events: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock)

    def clear(self) -> None:
        with self.lock:
            self.organizations.clear()
            self.memberships.clear()
            self.employees.clear()
            self.employee_manager_links.clear()
            self.departments.clear()
            self.cost_centers.clear()
            self.suppliers.clear()
            self.supplier_contacts.clear()
            self.supplier_products.clear()
            self.budgets.clear()
            self.policies.clear()
            self.documents.clear()
            self.document_chunks.clear()
            self.stored_objects.clear()
            self.processes.clear()
            self.process_versions.clear()
            self.discovery_sessions.clear()
            self.discovery_messages.clear()
            self.discovery_events.clear()
            self.allocations.clear()
            self.risk_results.clear()
            self.approvals.clear()
            self.process_runs.clear()
            self.tool_invocations.clear()
            self.email_outbox.clear()
            self.quote_requests.clear()
            self.quotations.clear()
            self.purchase_orders.clear()
            self.notifications.clear()
            self.tasks.clear()
            self.generated_documents.clear()
            self.audit_events.clear()
            self.idempotency.clear()
            self.run_events.clear()
            self.workflow_instances.clear()
            self.workflow_outbox.clear()
            self.workflow_inbox.clear()
            self.agent_run_records.clear()
            self.workflow_dead_letters.clear()
            self.workflow_trace_index.clear()
            self.encrypted_credentials.clear()
            self.email_threads.clear()
            self.billing_usage.clear()
            self.calendar_events.clear()
            self.plan_entitlements.clear()
            self.subscriptions.clear()
            self.usage_events.clear()
            self.billing_webhook_events.clear()


_STORE = MemoryStore()
_POSTGRES_PERSISTENCE_ENABLED = False


def seed_plan_entitlements(store: MemoryStore | None = None) -> None:
    """Load plan entitlement catalog into the memory store (idempotent)."""
    from app.billing.catalog import ENTITLEMENT_SEED

    target = store or _STORE
    for feature_code, by_plan in ENTITLEMENT_SEED.items():
        for plan_code, values in by_plan.items():
            target.plan_entitlements[(plan_code, feature_code)] = {
                "plan_code": plan_code,
                "feature_code": feature_code,
                "numeric_limit": values.get("numeric_limit"),
                "boolean_value": values.get("boolean_value"),
                "text_value": values.get("text_value"),
            }


seed_plan_entitlements(_STORE)


def get_memory_store() -> MemoryStore:
    return _STORE


def initialize_postgres_persistence() -> None:
    """Load workflow data from Postgres and persist subsequent writes."""
    global _POSTGRES_PERSISTENCE_ENABLED
    from app.config import get_settings
    from app.database.postgres_persistence import enable_postgres_persistence, hydrate_store
    from app.database.sync_pg import init_sync_engine

    settings = get_settings()
    if settings.persistence_mode != "postgres" or not settings.database_url:
        return
    if _POSTGRES_PERSISTENCE_ENABLED:
        return
    init_sync_engine(settings)
    hydrate_store(_STORE)
    enable_postgres_persistence(_STORE)
    _POSTGRES_PERSISTENCE_ENABLED = True


def reset_memory_store() -> None:
    global _POSTGRES_PERSISTENCE_ENABLED
    _POSTGRES_PERSISTENCE_ENABLED = False
    _STORE.clear()
    seed_plan_entitlements(_STORE)


def new_id() -> UUID:
    return uuid4()
