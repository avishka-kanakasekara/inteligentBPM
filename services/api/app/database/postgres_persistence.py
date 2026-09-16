"""Hydrate and persist the in-memory store to hosted Postgres."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.contracts.common import utcnow
from app.database.memory import (
    AllocationResultRecord,
    ApprovalRecord,
    BudgetRecord,
    CostCenterRecord,
    DepartmentRecord,
    DiscoveryMessageRecord,
    DiscoverySessionRecord,
    EmployeeManagerLinkRecord,
    EmployeeRecord,
    MemoryStore,
    MembershipRecord,
    OrganizationRecord,
    PolicyRecord,
    ProcessDefinitionRecord,
    ProcessRunRecord,
    ProcessVersionRecord,
    RiskResultRecord,
    SupplierContactRecord,
    SupplierProductRecord,
    SupplierRecord,
    new_id,
)
from app.database.models import (
    AppProcessRunModel,
    BudgetModel,
    CostCenterModel,
    DepartmentModel,
    DiscoveryMessageModel,
    DiscoverySessionModel,
    EmployeeManagerLinkModel,
    EmployeeModel,
    ExecutionArtifactModel,
    OrganizationMembershipModel,
    OrganizationModel,
    PolicyModel,
    ProcessDefinitionModel,
    ProcessVersionModel,
    ProcessWorkflowArtifactModel,
    SupplierContactModel,
    SupplierModel,
    SupplierProductModel,
)
from app.database.sync_pg import sync_session_scope
from app.domain.enums import ApprovalStatus, MembershipStatus, OrgRole, ProcessRunStatus


def _approval_status(value: str | ApprovalStatus) -> ApprovalStatus:
    if isinstance(value, ApprovalStatus):
        return value
    return ApprovalStatus(value)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def bootstrap_organization(
    *,
    organization_id: UUID,
    user_id: UUID,
    name: str,
    slug: str,
    plan_code: str = "enterprise",
    membership_id: UUID | None = None,
) -> None:
    now = utcnow()
    with sync_session_scope() as session:
        session.execute(
            insert(OrganizationModel)
            .values(
                id=organization_id,
                name=name,
                slug=slug,
                status="active",
                plan_code=plan_code,
                legal_name="Acme Corporation Inc.",
                trading_name="Acme",
                industry="Technology / Professional Services",
                country_code="US",
                tax_id="US-98-7654321",
                row_version=1,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        session.execute(
            insert(OrganizationMembershipModel)
            .values(
                id=membership_id or new_id(),
                organization_id=organization_id,
                user_id=user_id,
                role=OrgRole.OWNER.value,
                status=MembershipStatus.ACTIVE.value,
                row_version=1,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["organization_id", "user_id"])
        )


def hydrate_store(store: MemoryStore) -> None:
    with sync_session_scope() as session:
        for row in session.scalars(select(OrganizationModel)).all():
            store.organizations[row.id] = OrganizationRecord(
                id=row.id,
                name=row.name,
                slug=row.slug,
                plan_code=row.plan_code,
                status=row.status,
                row_version=row.row_version,
                created_at=row.created_at,
                updated_at=row.updated_at,
                legal_name=row.legal_name,
                trading_name=row.trading_name,
                industry=row.industry,
                country_code=row.country_code,
                tax_id=row.tax_id,
                tax_registration=row.tax_registration,
                tax_country_code=row.tax_country_code,
            )
        for row in session.scalars(select(OrganizationMembershipModel)).all():
            store.memberships[row.id] = MembershipRecord(
                id=row.id,
                organization_id=row.organization_id,
                user_id=row.user_id,
                role=OrgRole(row.role),
                status=MembershipStatus(row.status),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        for row in session.scalars(select(DepartmentModel)).all():
            store.departments[row.id] = DepartmentRecord(
                id=row.id,
                organization_id=row.organization_id,
                name=row.name,
                code=row.code,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                parent_department_id=row.parent_department_id,
                manager_employee_id=row.manager_employee_id,
            )
        for row in session.scalars(select(CostCenterModel)).all():
            store.cost_centers[row.id] = CostCenterRecord(
                id=row.id,
                organization_id=row.organization_id,
                code=row.code,
                name=row.name,
                department_id=row.department_id,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        for row in session.scalars(select(EmployeeModel)).all():
            store.employees[row.id] = EmployeeRecord(
                id=row.id,
                organization_id=row.organization_id,
                full_name=row.full_name,
                email=row.email,
                title=row.title,
                department_id=row.department_id,
                is_manager=bool(row.is_manager),
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                employee_code=row.employee_code,
                role_code=row.role_code,
                approval_authority_limit=_as_float(row.approval_authority_limit),
                approval_authority_currency=row.approval_authority_currency or "USD",
            )
        for row in session.scalars(select(EmployeeManagerLinkModel)).all():
            store.employee_manager_links[row.id] = EmployeeManagerLinkRecord(
                id=row.id,
                organization_id=row.organization_id,
                employee_id=row.employee_id,
                manager_employee_id=row.manager_employee_id,
                link_type=row.link_type,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        for row in session.scalars(select(SupplierModel)).all():
            store.suppliers[row.id] = SupplierRecord(
                id=row.id,
                organization_id=row.organization_id,
                name=row.name,
                code=row.code,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                approval_status=row.approval_status,
                website=row.website,
                country_code=row.country_code,
            )
        for row in session.scalars(select(SupplierContactModel)).all():
            store.supplier_contacts[row.id] = SupplierContactRecord(
                id=row.id,
                organization_id=row.organization_id,
                supplier_id=row.supplier_id,
                full_name=row.full_name,
                email=row.email,
                is_primary=bool(row.is_primary),
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                phone=row.phone,
                role_title=row.role_title,
                allow_duplicate_email=bool(row.allow_duplicate_email),
            )
        for row in session.scalars(select(SupplierProductModel)).all():
            store.supplier_products[row.id] = SupplierProductRecord(
                id=row.id,
                organization_id=row.organization_id,
                supplier_id=row.supplier_id,
                name=row.name,
                sku=row.sku,
                unit_price=_as_float(row.unit_price),
                currency_code=row.currency_code,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                description=row.description,
                unit_of_measure=row.unit_of_measure,
            )
        for row in session.scalars(select(BudgetModel)).all():
            store.budgets[row.id] = BudgetRecord(
                id=row.id,
                organization_id=row.organization_id,
                name=row.name,
                fiscal_year=row.fiscal_year,
                amount_total=float(row.amount_total),
                currency_code=row.currency_code,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                department_id=row.department_id,
                cost_center_id=row.cost_center_id,
            )
        for row in session.scalars(select(PolicyModel)).all():
            store.policies[row.id] = PolicyRecord(
                id=row.id,
                organization_id=row.organization_id,
                code=row.code,
                title=row.title,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                category=row.category,
            )
        for row in session.scalars(select(ProcessDefinitionModel)).all():
            store.processes[row.id] = ProcessDefinitionRecord(
                id=row.id,
                organization_id=row.organization_id,
                name=row.name,
                description=row.description,
                status=row.status,
                created_by_user_id=row.created_by_user_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        for row in session.scalars(select(ProcessVersionModel)).all():
            confirmed_at = None
            confirmed_by_user_id = None
            if row.status == "confirmed" and row.is_immutable:
                confirmed_at = row.updated_at
            store.process_versions[row.id] = ProcessVersionRecord(
                id=row.id,
                organization_id=row.organization_id,
                process_id=row.process_definition_id,
                version_number=row.version_number,
                plan_snapshot=dict(row.plan_snapshot),
                plan_snapshot_hash=row.plan_snapshot_hash,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                confirmed_at=confirmed_at,
                confirmed_by_user_id=confirmed_by_user_id,
                is_immutable=row.is_immutable,
            )
        for row in session.scalars(select(DiscoverySessionModel)).all():
            store.discovery_sessions[row.id] = DiscoverySessionRecord(
                id=row.id,
                organization_id=row.organization_id,
                process_id=row.process_definition_id,
                status=row.status,
                created_by_user_id=row.created_by_user_id,
                document_ids=list(row.document_ids or []),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        for row in session.scalars(select(DiscoveryMessageModel)).all():
            store.discovery_messages[row.id] = DiscoveryMessageRecord(
                id=row.id,
                organization_id=row.organization_id,
                process_id=row.process_definition_id,
                session_id=row.session_id,
                role=row.role,
                content=row.content,
                document_ids=list(row.document_ids or []),
                clarifying_questions=list(row.clarifying_questions or []),
                intent=row.intent,
                plan_draft=row.plan_draft,
                source_refs=list(row.source_refs or []),
                suspicious_flags=list(row.suspicious_flags or []),
                created_by_user_id=row.created_by_user_id,
                created_at=row.created_at,
            )
        for row in session.scalars(select(ProcessWorkflowArtifactModel)).all():
            payload = dict(row.payload or {})
            if row.artifact_type == "allocation":
                store.allocations[row.id] = AllocationResultRecord(
                    id=row.id,
                    organization_id=row.organization_id,
                    process_id=row.process_definition_id,
                    process_version_id=row.process_version_id,
                    status=row.status,
                    result_snapshot=payload,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            elif row.artifact_type == "risk":
                store.risk_results[row.id] = RiskResultRecord(
                    id=row.id,
                    organization_id=row.organization_id,
                    process_id=row.process_definition_id,
                    process_version_id=row.process_version_id,
                    allocation_id=payload.get("allocation_id"),
                    status=row.status,
                    result_snapshot=payload,
                    plan_snapshot_hash=row.plan_snapshot_hash or "",
                    allocation_snapshot_hash=row.allocation_snapshot_hash,
                    risk_snapshot_hash=row.risk_snapshot_hash or "",
                    valid=bool(row.valid),
                    invalidated_reason=row.invalidated_reason,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            elif row.artifact_type == "approval":
                store.approvals[row.id] = ApprovalRecord(
                    id=row.id,
                    organization_id=row.organization_id,
                    process_run_id=payload.get("process_run_id"),
                    status=_approval_status(row.status),
                    snapshot_hash=payload.get("snapshot_hash") or "",
                    snapshot_payload=payload.get("snapshot_payload") or {},
                    decided_by_user_id=payload.get("decided_by_user_id"),
                    decision_note=payload.get("decision_note"),
                    row_version=row.row_version,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    process_id=row.process_definition_id,
                    process_version_id=row.process_version_id,
                    risk_result_id=payload.get("risk_result_id"),
                    plan_snapshot_hash=row.plan_snapshot_hash,
                    allocation_snapshot_hash=row.allocation_snapshot_hash,
                    risk_snapshot_hash=row.risk_snapshot_hash,
                    required_roles=list(payload.get("required_roles") or []),
                    prohibited_action=bool(payload.get("prohibited_action")),
                    override_required=bool(payload.get("override_required")),
                    requested_role=payload.get("requested_role"),
                    requested_user=payload.get("requested_user"),
                    decision=payload.get("decision"),
                    decision_reason=payload.get("decision_reason"),
                    requested_timestamp=payload.get("requested_timestamp"),
                    decision_timestamp=payload.get("decision_timestamp"),
                    expiration_timestamp=payload.get("expiration_timestamp"),
                    audit_reference=payload.get("audit_reference"),
                    risk_analysis_id=payload.get("risk_analysis_id"),
                )
        for row in session.scalars(select(AppProcessRunModel)).all():
            store.process_runs[row.id] = ProcessRunRecord(
                id=row.id,
                organization_id=row.organization_id,
                process_id=row.process_definition_id,
                process_version_id=row.process_version_id,
                status=ProcessRunStatus(row.status),
                initiated_by_user_id=row.initiated_by_user_id,
                correlation_id=row.correlation_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
                plan_snapshot_hash=row.plan_snapshot_hash,
                risk_snapshot_hash=row.risk_snapshot_hash,
                approval_id=row.approval_id,
                dry_run=row.dry_run,
                current_step_index=row.current_step_index,
                pause_reason=row.pause_reason,
                allowed_tools=list(row.allowed_tools or []),
            )
        _ensure_execution_artifacts_table(session)
        for row in session.scalars(select(ExecutionArtifactModel)).all():
            payload = dict(row.payload or {})
            payload.setdefault("id", str(row.id))
            payload.setdefault("organization_id", str(row.organization_id))
            if row.process_id:
                payload.setdefault("process_id", str(row.process_id))
            if row.process_run_id:
                payload.setdefault("process_run_id", str(row.process_run_id))
            kind = row.artifact_kind
            if kind == "notification":
                store.notifications[row.id] = payload
            elif kind == "calendar_event":
                store.calendar_events[row.id] = payload
            elif kind == "task":
                store.tasks[row.id] = payload
            elif kind == "generated_document":
                store.generated_documents[row.id] = payload
            elif kind == "tool_invocation":
                store.tool_invocations[row.id] = payload
            elif kind == "email":
                store.email_outbox[row.id] = payload


def _ensure_execution_artifacts_table(session: Any) -> None:
    session.execute(
        __import__("sqlalchemy").text(
            """
            create table if not exists public.app_execution_artifacts (
              id uuid primary key,
              organization_id uuid not null,
              process_id uuid,
              process_run_id uuid,
              artifact_kind text not null,
              payload jsonb not null default '{}'::jsonb,
              created_at timestamptz not null default now(),
              updated_at timestamptz not null default now()
            )
            """
        )
    )


def _persist_execution_artifact(
    *,
    artifact_id: UUID,
    organization_id: UUID,
    kind: str,
    payload: dict[str, Any],
) -> None:
    process_id = None
    process_run_id = None
    try:
        if payload.get("process_id"):
            process_id = UUID(str(payload["process_id"]))
    except Exception:
        process_id = None
    try:
        if payload.get("process_run_id"):
            process_run_id = UUID(str(payload["process_run_id"]))
    except Exception:
        process_run_id = None
    values = {
        "id": artifact_id,
        "organization_id": organization_id,
        "process_id": process_id,
        "process_run_id": process_run_id,
        "artifact_kind": kind,
        "payload": payload,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    with sync_session_scope() as session:
        _ensure_execution_artifacts_table(session)
        stmt = insert(ExecutionArtifactModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ExecutionArtifactModel.id],
            set_={
                "organization_id": stmt.excluded.organization_id,
                "process_id": stmt.excluded.process_id,
                "process_run_id": stmt.excluded.process_run_id,
                "artifact_kind": stmt.excluded.artifact_kind,
                "payload": stmt.excluded.payload,
                "updated_at": utcnow(),
            },
        )
        session.execute(stmt)


def _org_uuid(payload: dict[str, Any]) -> UUID | None:
    try:
        return UUID(str(payload.get("organization_id")))
    except Exception:
        return None


def persist_notification(store: MemoryStore, record: dict[str, Any]) -> None:
    org = _org_uuid(record)
    if org is None or not record.get("id"):
        return
    _persist_execution_artifact(
        artifact_id=UUID(str(record["id"])),
        organization_id=org,
        kind="notification",
        payload=dict(record),
    )


def persist_calendar_event(store: MemoryStore, record: dict[str, Any]) -> None:
    org = _org_uuid(record)
    if org is None or not record.get("id"):
        return
    _persist_execution_artifact(
        artifact_id=UUID(str(record["id"])),
        organization_id=org,
        kind="calendar_event",
        payload=dict(record),
    )


def persist_task(store: MemoryStore, record: dict[str, Any]) -> None:
    org = _org_uuid(record)
    if org is None or not record.get("id"):
        return
    _persist_execution_artifact(
        artifact_id=UUID(str(record["id"])),
        organization_id=org,
        kind="task",
        payload=dict(record),
    )


def persist_generated_document(store: MemoryStore, record: dict[str, Any]) -> None:
    org = _org_uuid(record)
    if org is None or not record.get("id"):
        return
    _persist_execution_artifact(
        artifact_id=UUID(str(record["id"])),
        organization_id=org,
        kind="generated_document",
        payload=dict(record),
    )


def persist_tool_invocation(store: MemoryStore, record: dict[str, Any]) -> None:
    org = _org_uuid(record)
    if org is None or not record.get("id"):
        return
    _persist_execution_artifact(
        artifact_id=UUID(str(record["id"])),
        organization_id=org,
        kind="tool_invocation",
        payload=dict(record),
    )


def persist_email_outbox(store: MemoryStore, record: dict[str, Any]) -> None:
    org = _org_uuid(record)
    if org is None or not record.get("id"):
        return
    _persist_execution_artifact(
        artifact_id=UUID(str(record["id"])),
        organization_id=org,
        kind="email",
        payload=dict(record),
    )


def persist_organization(store: MemoryStore, record: OrganizationRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            OrganizationModel(
                id=record.id,
                name=record.name,
                slug=record.slug,
                status=record.status,
                plan_code=record.plan_code,
                legal_name=record.legal_name,
                trading_name=record.trading_name,
                industry=record.industry,
                country_code=record.country_code,
                tax_id=record.tax_id,
                tax_registration=record.tax_registration,
                tax_country_code=record.tax_country_code,
                row_version=record.row_version,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_membership(store: MemoryStore, record: MembershipRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            OrganizationMembershipModel(
                id=record.id,
                organization_id=record.organization_id,
                user_id=record.user_id,
                role=record.role.value,
                status=record.status.value,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_department(store: MemoryStore, record: DepartmentRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            DepartmentModel(
                id=record.id,
                organization_id=record.organization_id,
                name=record.name,
                code=record.code,
                parent_department_id=record.parent_department_id,
                manager_employee_id=record.manager_employee_id,
                status=record.status,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_cost_center(store: MemoryStore, record: CostCenterRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            CostCenterModel(
                id=record.id,
                organization_id=record.organization_id,
                code=record.code,
                name=record.name,
                department_id=record.department_id,
                status=record.status,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_employee(store: MemoryStore, record: EmployeeRecord) -> None:
    user_id = (
        UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        if record.email == "owner@demo.bpm.local"
        else None
    )
    with sync_session_scope() as session:
        session.merge(
            EmployeeModel(
                id=record.id,
                organization_id=record.organization_id,
                user_id=user_id,
                employee_code=record.employee_code,
                full_name=record.full_name,
                email=record.email,
                title=record.title,
                department_id=record.department_id,
                status=record.status,
                is_manager=record.is_manager,
                role_code=record.role_code,
                approval_authority_limit=record.approval_authority_limit,
                approval_authority_currency=record.approval_authority_currency,
                metadata_json={},
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_manager_link(store: MemoryStore, record: EmployeeManagerLinkRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            EmployeeManagerLinkModel(
                id=record.id,
                organization_id=record.organization_id,
                employee_id=record.employee_id,
                manager_employee_id=record.manager_employee_id,
                link_type=record.link_type,
                status=record.status,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_supplier(store: MemoryStore, record: SupplierRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            SupplierModel(
                id=record.id,
                organization_id=record.organization_id,
                name=record.name,
                code=record.code,
                status=record.status,
                website=record.website,
                country_code=record.country_code,
                approval_status=record.approval_status,
                metadata_json={},
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_supplier_contact(store: MemoryStore, record: SupplierContactRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            SupplierContactModel(
                id=record.id,
                organization_id=record.organization_id,
                supplier_id=record.supplier_id,
                full_name=record.full_name,
                email=record.email,
                phone=record.phone,
                role_title=record.role_title,
                is_primary=record.is_primary,
                status=record.status,
                allow_duplicate_email=record.allow_duplicate_email,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_supplier_product(store: MemoryStore, record: SupplierProductRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            SupplierProductModel(
                id=record.id,
                organization_id=record.organization_id,
                supplier_id=record.supplier_id,
                sku=record.sku,
                name=record.name,
                description=record.description,
                unit_of_measure=record.unit_of_measure,
                unit_price=record.unit_price,
                currency_code=record.currency_code,
                status=record.status,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_budget(store: MemoryStore, record: BudgetRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            BudgetModel(
                id=record.id,
                organization_id=record.organization_id,
                department_id=record.department_id,
                cost_center_id=record.cost_center_id,
                name=record.name,
                fiscal_year=record.fiscal_year,
                currency_code=record.currency_code,
                amount_total=record.amount_total,
                amount_spent=0,
                status=record.status,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_policy(store: MemoryStore, record: PolicyRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            PolicyModel(
                id=record.id,
                organization_id=record.organization_id,
                code=record.code,
                title=record.title,
                category=record.category,
                status=record.status,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_process(store: MemoryStore, record: ProcessDefinitionRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            ProcessDefinitionModel(
                id=record.id,
                organization_id=record.organization_id,
                name=record.name,
                description=record.description,
                status=record.status,
                created_by_user_id=record.created_by_user_id,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_process_version(store: MemoryStore, record: ProcessVersionRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            ProcessVersionModel(
                id=record.id,
                organization_id=record.organization_id,
                process_definition_id=record.process_id,
                version_number=record.version_number,
                plan_snapshot=record.plan_snapshot,
                plan_snapshot_hash=record.plan_snapshot_hash,
                status=record.status,
                is_immutable=record.is_immutable,
                source_refs=record.plan_snapshot.get("source_refs") or [],
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_discovery_session(store: MemoryStore, record: DiscoverySessionRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            DiscoverySessionModel(
                id=record.id,
                organization_id=record.organization_id,
                process_definition_id=record.process_id,
                status=record.status,
                created_by_user_id=record.created_by_user_id,
                document_ids=list(record.document_ids),
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def persist_discovery_message(store: MemoryStore, record: DiscoveryMessageRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            DiscoveryMessageModel(
                id=record.id,
                organization_id=record.organization_id,
                process_definition_id=record.process_id,
                session_id=record.session_id,
                role=record.role,
                content=record.content,
                document_ids=list(record.document_ids),
                clarifying_questions=list(record.clarifying_questions),
                intent=record.intent,
                plan_draft=record.plan_draft,
                source_refs=list(record.source_refs),
                suspicious_flags=list(record.suspicious_flags),
                created_by_user_id=record.created_by_user_id,
                created_at=record.created_at,
            )
        )


def _upsert_workflow_artifact(
    *,
    record_id: UUID,
    organization_id: UUID,
    process_id: UUID,
    process_version_id: UUID,
    artifact_type: str,
    status: str,
    payload: dict[str, Any],
    created_at: datetime,
    updated_at: datetime,
    plan_snapshot_hash: str | None = None,
    allocation_snapshot_hash: str | None = None,
    risk_snapshot_hash: str | None = None,
    valid: bool | None = None,
    invalidated_reason: str | None = None,
    row_version: int = 1,
) -> None:
    """Insert or update by (process_version_id, artifact_type) unique key."""
    values = {
        "id": record_id,
        "organization_id": organization_id,
        "process_definition_id": process_id,
        "process_version_id": process_version_id,
        "artifact_type": artifact_type,
        "status": status,
        "payload": payload,
        "plan_snapshot_hash": plan_snapshot_hash,
        "allocation_snapshot_hash": allocation_snapshot_hash,
        "risk_snapshot_hash": risk_snapshot_hash,
        "valid": valid,
        "invalidated_reason": invalidated_reason,
        "row_version": row_version,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    stmt = insert(ProcessWorkflowArtifactModel).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["process_version_id", "artifact_type"],
        set_={
            "id": stmt.excluded.id,
            "organization_id": stmt.excluded.organization_id,
            "process_definition_id": stmt.excluded.process_definition_id,
            "status": stmt.excluded.status,
            "payload": stmt.excluded.payload,
            "plan_snapshot_hash": stmt.excluded.plan_snapshot_hash,
            "allocation_snapshot_hash": stmt.excluded.allocation_snapshot_hash,
            "risk_snapshot_hash": stmt.excluded.risk_snapshot_hash,
            "valid": stmt.excluded.valid,
            "invalidated_reason": stmt.excluded.invalidated_reason,
            "row_version": stmt.excluded.row_version,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    with sync_session_scope() as session:
        session.execute(stmt)


def persist_allocation(store: MemoryStore, record: AllocationResultRecord) -> None:
    _upsert_workflow_artifact(
        record_id=record.id,
        organization_id=record.organization_id,
        process_id=record.process_id,
        process_version_id=record.process_version_id,
        artifact_type="allocation",
        status=record.status,
        payload=record.result_snapshot,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def persist_risk_result(store: MemoryStore, record: RiskResultRecord) -> None:
    payload = dict(record.result_snapshot)
    payload["allocation_id"] = str(record.allocation_id) if record.allocation_id else None
    _upsert_workflow_artifact(
        record_id=record.id,
        organization_id=record.organization_id,
        process_id=record.process_id,
        process_version_id=record.process_version_id,
        artifact_type="risk",
        status=record.status,
        payload=payload,
        created_at=record.created_at,
        updated_at=record.updated_at,
        plan_snapshot_hash=record.plan_snapshot_hash,
        allocation_snapshot_hash=record.allocation_snapshot_hash,
        risk_snapshot_hash=record.risk_snapshot_hash,
        valid=record.valid,
        invalidated_reason=record.invalidated_reason,
    )


def persist_approval(store: MemoryStore, record: ApprovalRecord) -> None:
    if record.process_id is None or record.process_version_id is None:
        return
    payload: dict[str, Any] = {
        "process_run_id": str(record.process_run_id) if record.process_run_id else None,
        "snapshot_hash": record.snapshot_hash,
        "snapshot_payload": record.snapshot_payload,
        "decided_by_user_id": str(record.decided_by_user_id) if record.decided_by_user_id else None,
        "decision_note": record.decision_note,
        "risk_result_id": str(record.risk_result_id) if record.risk_result_id else None,
        "required_roles": list(record.required_roles),
        "prohibited_action": record.prohibited_action,
        "override_required": record.override_required,
        "requested_role": record.requested_role,
        "requested_user": str(record.requested_user) if record.requested_user else None,
        "decision": record.decision,
        "decision_reason": record.decision_reason,
        "requested_timestamp": record.requested_timestamp.isoformat()
        if isinstance(record.requested_timestamp, datetime)
        else record.requested_timestamp,
        "decision_timestamp": record.decision_timestamp.isoformat()
        if isinstance(record.decision_timestamp, datetime)
        else record.decision_timestamp,
        "expiration_timestamp": record.expiration_timestamp.isoformat()
        if isinstance(record.expiration_timestamp, datetime)
        else record.expiration_timestamp,
        "audit_reference": record.audit_reference,
        "risk_analysis_id": str(record.risk_analysis_id) if record.risk_analysis_id else None,
    }
    _upsert_workflow_artifact(
        record_id=record.id,
        organization_id=record.organization_id,
        process_id=record.process_id,
        process_version_id=record.process_version_id,
        artifact_type="approval",
        status=record.status.value if isinstance(record.status, ApprovalStatus) else str(record.status),
        payload=payload,
        created_at=record.created_at,
        updated_at=record.updated_at,
        plan_snapshot_hash=record.plan_snapshot_hash,
        allocation_snapshot_hash=record.allocation_snapshot_hash,
        risk_snapshot_hash=record.risk_snapshot_hash,
        row_version=record.row_version,
    )


def persist_process_run(store: MemoryStore, record: ProcessRunRecord) -> None:
    with sync_session_scope() as session:
        session.merge(
            AppProcessRunModel(
                id=record.id,
                organization_id=record.organization_id,
                process_definition_id=record.process_id,
                process_version_id=record.process_version_id,
                status=record.status.value if isinstance(record.status, ProcessRunStatus) else str(record.status),
                initiated_by_user_id=record.initiated_by_user_id,
                correlation_id=record.correlation_id,
                plan_snapshot_hash=record.plan_snapshot_hash,
                risk_snapshot_hash=record.risk_snapshot_hash,
                approval_id=record.approval_id,
                dry_run=record.dry_run,
                current_step_index=record.current_step_index,
                pause_reason=record.pause_reason,
                allowed_tools=list(record.allowed_tools),
                metadata_json={},
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


class _PersistedDict(dict[Any, Any]):
    def __init__(self, store: MemoryStore, saver: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._store = store
        self._saver = saver

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self._saver(self._store, value)

    def pop(self, key: Any, default: Any = None) -> Any:
        value = super().pop(key, default)
        return value


def enable_postgres_persistence(store: MemoryStore) -> None:
    store.organizations = _PersistedDict(store, persist_organization, store.organizations)
    store.memberships = _PersistedDict(store, persist_membership, store.memberships)
    store.departments = _PersistedDict(store, persist_department, store.departments)
    store.cost_centers = _PersistedDict(store, persist_cost_center, store.cost_centers)
    store.employees = _PersistedDict(store, persist_employee, store.employees)
    store.employee_manager_links = _PersistedDict(
        store, persist_manager_link, store.employee_manager_links
    )
    store.suppliers = _PersistedDict(store, persist_supplier, store.suppliers)
    store.supplier_contacts = _PersistedDict(
        store, persist_supplier_contact, store.supplier_contacts
    )
    store.supplier_products = _PersistedDict(
        store, persist_supplier_product, store.supplier_products
    )
    store.budgets = _PersistedDict(store, persist_budget, store.budgets)
    store.policies = _PersistedDict(store, persist_policy, store.policies)
    store.processes = _PersistedDict(store, persist_process, store.processes)
    store.process_versions = _PersistedDict(store, persist_process_version, store.process_versions)
    store.discovery_sessions = _PersistedDict(store, persist_discovery_session, store.discovery_sessions)
    store.discovery_messages = _PersistedDict(store, persist_discovery_message, store.discovery_messages)
    store.allocations = _PersistedDict(store, persist_allocation, store.allocations)
    store.risk_results = _PersistedDict(store, persist_risk_result, store.risk_results)
    store.approvals = _PersistedDict(store, persist_approval, store.approvals)
    store.process_runs = _PersistedDict(store, persist_process_run, store.process_runs)
    store.notifications = _PersistedDict(store, persist_notification, store.notifications)
    store.calendar_events = _PersistedDict(store, persist_calendar_event, store.calendar_events)
    store.tasks = _PersistedDict(store, persist_task, store.tasks)
    store.generated_documents = _PersistedDict(
        store, persist_generated_document, store.generated_documents
    )
    store.tool_invocations = _PersistedDict(store, persist_tool_invocation, store.tool_invocations)
    store.email_outbox = _PersistedDict(store, persist_email_outbox, store.email_outbox)


def persist_mutation(store: MemoryStore, collection: str, record_id: UUID) -> None:
    """Persist in-place mutations on records already stored in memory."""
    if collection == "process_versions":
        record = store.process_versions.get(record_id)
        if record is not None:
            persist_process_version(store, record)
    elif collection == "discovery_sessions":
        record = store.discovery_sessions.get(record_id)
        if record is not None:
            persist_discovery_session(store, record)
    elif collection == "approvals":
        record = store.approvals.get(record_id)
        if record is not None:
            persist_approval(store, record)
    elif collection == "process_runs":
        record = store.process_runs.get(record_id)
        if record is not None:
            persist_process_run(store, record)
