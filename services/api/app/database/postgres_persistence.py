"""Hydrate and persist the in-memory store to hosted Postgres."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts.common import utcnow
from app.security.errors import AppError
from app.database.employee_compat import (
    HostedRole,
    employee_model_values,
    resolve_role_id,
    role_code_for_tenant,
)
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
    EmployeeManagerLinkModel,
    EmployeeModel,
    ExecutionArtifactModel,
    OrganizationMembershipModel,
    OrganizationModel,
    PolicyModel,
    ProcessDefinitionModel,
    ProcessVersionModel,
    ProcessWorkflowArtifactModel,
    RoleModel,
    SupplierContactModel,
    SupplierModel,
    SupplierProductModel,
    TenantMembershipModel,
    TenantModel,
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


def _is_missing_relation(exc: BaseException) -> bool:
    """True only for PostgreSQL undefined-table errors."""
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return sqlstate == "42P01"


def _public_relation_exists(session: Session, table_name: str) -> bool:
    if not table_name.replace("_", "").isalnum():
        raise ValueError(f"Unexpected table name: {table_name}")
    found = session.execute(
        text("select to_regclass(:qualified)"),
        {"qualified": f"public.{table_name}"},
    ).scalar_one()
    return found is not None


_DEPARTMENT_OPTIONAL_COLUMNS = (
    "code",
    "parent_department_id",
    "manager_employee_id",
    "status",
    "row_version",
    "created_at",
    "updated_at",
)


def _department_columns(session: Session) -> set[str]:
    rows = session.execute(
        text(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = 'departments'"
        )
    ).all()
    names: set[str] = set()
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        name = mapping["column_name"] if "column_name" in mapping else row[0]
        if isinstance(name, str) and name.replace("_", "").isalnum():
            names.add(name)
    return names


def department_scope_column(columns: set[str]) -> str:
    """Physical tenant column on public.departments.

    Hosted departments use tenant_id. The repository schema uses organization_id.
    """
    if "tenant_id" in columns:
        return "tenant_id"
    if "organization_id" in columns:
        return "organization_id"
    raise ValueError("public.departments has no tenant scope column")


_ORGANIZATION_CREATE_UNSUPPORTED = (
    "Creating a workspace is not available for this database. "
    "No workspace or membership was written."
)
_HOSTED_TENANT_COLUMNS = frozenset(
    {"id", "code", "name", "is_active", "created_at", "updated_at"}
)
_HOSTED_MEMBERSHIP_COLUMNS = frozenset(
    {"id", "tenant_id", "user_id", "role", "status", "created_at", "updated_at"}
)


_DISCOVERY_STORAGE_UNAVAILABLE = (
    "Discovery chat storage is not available for this database. "
    "No chat message was written."
)
_HOSTED_PROCESS_TYPE = "discovered"
_SESSION_OPTIONAL_COLUMNS = (
    "status",
    "created_by_user_id",
    "document_ids",
    "row_version",
    "created_at",
    "updated_at",
)
_MESSAGE_OPTIONAL_COLUMNS = (
    "document_ids",
    "clarifying_questions",
    "intent",
    "plan_draft",
    "source_refs",
    "suspicious_flags",
    "created_by_user_id",
)
_JSON_COLUMNS = frozenset(
    {"clarifying_questions", "intent", "plan_draft", "source_refs", "suspicious_flags"}
)


def _discovery_storage_error() -> AppError:
    return AppError(
        _DISCOVERY_STORAGE_UNAVAILABLE,
        code="DISCOVERY_STORAGE_UNAVAILABLE",
        status_code=503,
    )


def _discovery_identity(columns: set[str]) -> tuple[str, str] | None:
    """Physical scope and process columns for a discovery table.

    Original tables use organization_id and process_definition_id.
    Hosted tables use tenant_id and process_id, matching public.processes.
    """
    if "organization_id" in columns and "process_definition_id" in columns:
        return "organization_id", "process_definition_id"
    if "tenant_id" in columns and "process_id" in columns:
        return "tenant_id", "process_id"
    return None


def _uuid_list(value: object) -> list[UUID]:
    if not value:
        return []
    result: list[UUID] = []
    for item in value:  # type: ignore[union-attr]
        result.append(item if isinstance(item, UUID) else UUID(str(item)))
    return result


def _json_value(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)


def _public_column_names(session: Session, table_name: str) -> set[str]:
    if not table_name.replace("_", "").isalnum():
        raise ValueError(f"Unexpected table name: {table_name}")
    rows = session.execute(
        text(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = :table_name"
        ),
        {"table_name": table_name},
    ).all()
    names: set[str] = set()
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        name = mapping["column_name"] if "column_name" in mapping else row[0]
        if isinstance(name, str) and name.replace("_", "").isalnum():
            names.add(name)
    return names


def _bind_expression(column: str) -> str:
    if column == "document_ids":
        return "cast(:document_ids as uuid[])"
    if column in _JSON_COLUMNS:
        return f"cast(:{column} as jsonb)"
    return f":{column}"


def _upsert_sql(table: str, columns: list[str], update_columns: list[str]) -> str:
    if table not in {"discovery_sessions", "discovery_messages", "processes"}:
        raise ValueError(f"Unexpected table name: {table}")
    for column in [*columns, *update_columns]:
        if not column.replace("_", "").isalnum():
            raise ValueError(f"Unexpected column name: {column}")
    assignments = ", ".join(f"{column} = excluded.{column}" for column in update_columns)
    if assignments:
        conflict = f" on conflict (id) do update set {assignments}"
    else:
        conflict = " on conflict (id) do nothing"
    return (
        f"insert into public.{table} ({', '.join(columns)}) "
        f"values ({', '.join(_bind_expression(column) for column in columns)})"
        f"{conflict}"
    )


def _load_processes(session: Session, store: MemoryStore) -> None:
    """Load process definitions, or hosted processes scoped by tenant_id."""
    definition_columns = _public_column_names(session, "process_definitions")
    if "organization_id" in definition_columns:
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
        return
    columns = _public_column_names(session, "processes")
    required = {"id", "tenant_id", "name", "status", "created_at", "updated_at"}
    if not required <= columns:
        return
    selected = [
        "id",
        "tenant_id as organization_id",
        "name",
        "status",
        "created_at",
        "updated_at",
    ]
    for column in ("description", "created_by"):
        if column in columns:
            alias = "created_by_user_id" if column == "created_by" else column
            selected.append(f"{column} as {alias}" if column == "created_by" else column)
    rows = session.execute(
        text(
            "select "
            + ", ".join(selected)
            + " from public.processes where tenant_id is not null"
        )
    ).mappings().all()
    for row in rows:
        store.processes[row["id"]] = ProcessDefinitionRecord(
            id=row["id"],
            organization_id=row["organization_id"],
            name=row["name"],
            description=row["description"] if "description" in row else None,
            status=row["status"],
            created_by_user_id=row.get("created_by_user_id"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _discovery_select_sql(table: str, columns: set[str], identity: tuple[str, str]) -> str:
    scope, process_column = identity
    selected = [
        "id",
        f"{scope} as organization_id",
        f"{process_column} as process_id",
    ]
    if table == "discovery_messages":
        selected.extend(["session_id", "role", "content", "created_at"])
        optional = _MESSAGE_OPTIONAL_COLUMNS
    else:
        optional = _SESSION_OPTIONAL_COLUMNS
    selected.extend(column for column in optional if column in columns and column not in selected)
    return (
        f"select {', '.join(selected)} from public.{table} "
        "order by created_at asc, id asc"
    )


def _load_discovery(session: Session, store: MemoryStore) -> None:
    session_columns = _public_column_names(session, "discovery_sessions")
    session_identity = _discovery_identity(session_columns)
    if session_identity is not None and {"created_at", "status"} <= session_columns:
        rows = session.execute(
            text(_discovery_select_sql("discovery_sessions", session_columns, session_identity))
        ).mappings().all()
        for row in rows:
            store.discovery_sessions[row["id"]] = DiscoverySessionRecord(
                id=row["id"],
                organization_id=row["organization_id"],
                process_id=row["process_id"],
                status=row["status"],
                created_by_user_id=row.get("created_by_user_id"),
                document_ids=_uuid_list(row.get("document_ids") or []),
                created_at=row["created_at"],
                updated_at=row["updated_at"] if "updated_at" in row else row["created_at"],
            )
    message_columns = _public_column_names(session, "discovery_messages")
    message_identity = _discovery_identity(message_columns)
    if message_identity is None or "created_at" not in message_columns:
        return
    rows = session.execute(
        text(_discovery_select_sql("discovery_messages", message_columns, message_identity))
    ).mappings().all()
    for row in rows:
        store.discovery_messages[row["id"]] = DiscoveryMessageRecord(
            id=row["id"],
            organization_id=row["organization_id"],
            process_id=row["process_id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            document_ids=_uuid_list(row.get("document_ids") or []),
            clarifying_questions=_text_list(
                row["clarifying_questions"] if "clarifying_questions" in row else []
            ),
            intent=row["intent"] if "intent" in row else None,
            plan_draft=row["plan_draft"] if "plan_draft" in row else None,
            source_refs=list(row.get("source_refs") or []),
            suspicious_flags=_text_list(
                row["suspicious_flags"] if "suspicious_flags" in row else []
            ),
            created_by_user_id=row.get("created_by_user_id"),
            created_at=row["created_at"],
        )


def _hosted_workspace_ready(session: Session) -> bool:
    """True when a workspace can be stored on the verified hosted tenant tables."""
    if _public_relation_exists(session, "organizations"):
        return False
    if not _public_relation_exists(session, "tenants"):
        return False
    if not _public_relation_exists(session, "tenant_memberships"):
        return False
    tenant_columns = _public_column_names(session, "tenants")
    membership_columns = _public_column_names(session, "tenant_memberships")
    return _HOSTED_TENANT_COLUMNS <= tenant_columns and _HOSTED_MEMBERSHIP_COLUMNS <= membership_columns


def workspace_create_backend() -> str:
    """Where a new workspace is stored: memory, organizations, or tenants."""
    from app.database.memory import postgres_persistence_enabled

    if not postgres_persistence_enabled():
        return "memory"
    with sync_session_scope() as session:
        if _public_relation_exists(session, "organizations"):
            return "organizations"
        if _hosted_workspace_ready(session):
            return "tenants"
    raise AppError(
        _ORGANIZATION_CREATE_UNSUPPORTED,
        code="ORGANIZATION_CREATE_UNSUPPORTED",
        status_code=422,
    )


def _raise_if_organizations_missing(session: Session) -> None:
    if _public_relation_exists(session, "organizations"):
        return
    raise AppError(
        _ORGANIZATION_CREATE_UNSUPPORTED,
        code="ORGANIZATION_CREATE_UNSUPPORTED",
        status_code=422,
    )


def organization_create_supported() -> bool:
    """Whether POST /organizations can persist a workspace."""
    from app.database.memory import postgres_persistence_enabled

    if not postgres_persistence_enabled():
        return True
    with sync_session_scope() as session:
        if _public_relation_exists(session, "organizations"):
            return True
        return _hosted_workspace_ready(session)


def assert_organization_create_supported() -> None:
    """Refuse creation when neither workspace schema can store one."""
    workspace_create_backend()


def organization_directory_available() -> bool:
    """True when the repository organization and membership tables both exist."""
    with sync_session_scope() as session:
        return _public_relation_exists(session, "organizations") and _public_relation_exists(
            session, "organization_memberships"
        )


def _load_present(loader: Callable[[Session], None]) -> None:
    """Run one catalog load. A missing table leaves that catalog empty."""
    try:
        with sync_session_scope() as session:
            loader(session)
    except Exception as exc:
        if _is_missing_relation(exc):
            return
        raise


def _load_required(loader: Callable[[Session], None]) -> None:
    with sync_session_scope() as session:
        loader(session)


def organization_record_for_tenant(tenant: TenantModel | UUID) -> OrganizationRecord:
    """Application identity for a hosted tenant.

    Name and active state come from the verified tenant columns when present.
    Plan stays blank because public.tenants has no plan column.
    """
    now = utcnow()
    if isinstance(tenant, UUID):
        tenant_id = tenant
        name = str(tenant)
        code = ""
        is_active = None
        created_at = now
        updated_at = now
    else:
        tenant_id = tenant.id
        name = getattr(tenant, "name", None) or str(tenant.id)
        code = getattr(tenant, "code", None) or ""
        is_active = getattr(tenant, "is_active", None)
        created_at = getattr(tenant, "created_at", None) or now
        updated_at = getattr(tenant, "updated_at", None) or created_at
    if is_active is True:
        status = "active"
    elif is_active is False:
        status = "inactive"
    else:
        status = ""
    return OrganizationRecord(
        id=tenant_id,
        name=str(name),
        slug=str(code),
        plan_code="",
        status=status,
        row_version=1,
        created_at=created_at,
        updated_at=updated_at,
    )


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
        if not _public_relation_exists(session, "organizations"):
            return
        if not _public_relation_exists(session, "organization_memberships"):
            return
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


def ensure_policy_detail_columns() -> None:
    """Keep policy text available on databases created before description was stored."""
    with sync_session_scope() as session:
        session.execute(text("alter table public.policies add column if not exists description text"))
        session.execute(
            text("alter table public.policies add column if not exists owner_employee_id uuid")
        )
        session.execute(
            text(
                "alter table public.policies add column if not exists metadata jsonb "
                "not null default '{}'::jsonb"
            )
        )


def hydrate_store(store: MemoryStore) -> None:
    def load_organizations(session: Session) -> None:
<<<<<<< HEAD
=======
    ensure_policy_detail_columns()
    with sync_session_scope() as session:
>>>>>>> main
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

    def load_memberships(session: Session) -> None:
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

    def load_tenants(session: Session) -> None:
        for row in session.scalars(select(TenantModel)).all():
            if row.id in store.organizations:
                continue
            store.organizations[row.id] = organization_record_for_tenant(row)

    def load_tenant_memberships(session: Session) -> None:
        for row in session.scalars(select(TenantMembershipModel)).all():
            store.memberships[row.id] = MembershipRecord(
                id=row.id,
                organization_id=row.tenant_id,
                user_id=row.user_id,
                role=OrgRole(row.role),
                status=MembershipStatus(row.status),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    def load_employees(session: Session) -> None:
        employee_rows = session.execute(
            select(EmployeeModel, RoleModel.code, RoleModel.tenant_id).outerjoin(
                RoleModel,
                and_(
                    RoleModel.id == EmployeeModel.role_id,
                    RoleModel.tenant_id == EmployeeModel.organization_id,
                ),
<<<<<<< HEAD
=======
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
                description=row.description,
                owner_employee_id=row.owner_employee_id,
                metadata=dict(row.metadata_json or {}),
>>>>>>> main
            )
        ).all()
        for row, role_code, role_tenant_id in employee_rows:
            store.employees[row.id] = _employee_from_row(
                row,
                role_code=role_code_for_tenant(row.organization_id, role_tenant_id, role_code),
            )

    _load_present(load_organizations)
    _load_present(load_memberships)
    _load_present(load_tenants)
    _load_present(load_tenant_memberships)
    _load_required(load_employees)
    _load_present(lambda session: _hydrate_optional_catalogs(session, store))


def _department_select_sql(columns: set[str]) -> str:
    scope_column = department_scope_column(columns)
    selected = ["id", f"{scope_column} as organization_id", "name"]
    for column in _DEPARTMENT_OPTIONAL_COLUMNS:
        if column in columns:
            selected.append(column)
    return "select " + ", ".join(selected) + " from public.departments"


def _load_departments(session: Session, store: MemoryStore) -> None:
    columns = _department_columns(session)
    rows = session.execute(text(_department_select_sql(columns))).mappings().all()
    for row in rows:
        if "status" not in row or "created_at" not in row or "updated_at" not in row:
            raise ValueError("public.departments is missing status or timestamp columns")
        store.departments[row["id"]] = DepartmentRecord(
            id=row["id"],
            organization_id=row["organization_id"],
            name=row["name"],
            code=row["code"] if "code" in row else None,
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            parent_department_id=row["parent_department_id"] if "parent_department_id" in row else None,
            manager_employee_id=row["manager_employee_id"] if "manager_employee_id" in row else None,
        )


def _hydrate_optional_catalogs(session: Session, store: MemoryStore) -> None:
    _load_processes(session, store)
    _load_discovery(session, store)
    _load_departments(session, store)
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
        store.suppliers[row.id] = _supplier_from_row(row)
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
<<<<<<< HEAD
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
=======
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
                approval_id=row.approval_id,
                dry_run=row.dry_run,
                current_step_index=row.current_step_index,
                pause_reason=row.pause_reason,
                allowed_tools=list(row.allowed_tools or []),
                metadata=dict(row.metadata_json or {}),
            )
>>>>>>> main
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
    if not _public_relation_exists(session, "app_execution_artifacts"):
        return
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


def persist_hosted_workspace(record: OrganizationRecord, membership: MembershipRecord) -> None:
    """Insert a hosted tenant and its owner membership in one transaction."""
    with sync_session_scope() as session:
        if not _hosted_workspace_ready(session):
            raise AppError(
                _ORGANIZATION_CREATE_UNSUPPORTED,
                code="ORGANIZATION_CREATE_UNSUPPORTED",
                status_code=422,
            )
        base = record.slug or "workspace"
        code = base
        inserted = False
        for attempt in range(1, 21):
            try:
                with session.begin_nested():
                    session.execute(
                        text(
                            "insert into public.tenants "
                            "(id, code, name, is_active, created_at, updated_at) "
                            "values (:id, :code, :name, :is_active, :created_at, :updated_at)"
                        ),
                        {
                            "id": record.id,
                            "code": code,
                            "name": record.name,
                            "is_active": True,
                            "created_at": record.created_at,
                            "updated_at": record.updated_at,
                        },
                    )
                inserted = True
                break
            except IntegrityError:
                code = f"{base}-{attempt}"
        if not inserted:
            raise AppError(
                "A workspace with this name already exists",
                code="CONFLICT",
                status_code=409,
            )
        record.slug = code
        session.execute(
            text(
                "insert into public.tenant_memberships "
                "(id, tenant_id, user_id, role, status, created_at, updated_at) "
                "values (:id, :tenant_id, :user_id, :role, :status, :created_at, :updated_at)"
            ),
            {
                "id": membership.id,
                "tenant_id": record.id,
                "user_id": membership.user_id,
                "role": membership.role.value,
                "status": membership.status.value,
                "created_at": membership.created_at,
                "updated_at": membership.updated_at,
            },
        )


def persist_organization(store: MemoryStore, record: OrganizationRecord) -> None:
    with sync_session_scope() as session:
        _raise_if_organizations_missing(session)
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
        if _public_relation_exists(session, "tenant_memberships") and not _public_relation_exists(
            session, "organization_memberships"
        ):
            session.merge(
                TenantMembershipModel(
                    id=record.id,
                    tenant_id=record.organization_id,
                    user_id=record.user_id,
                    role=record.role.value,
                    status=record.status.value,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
            return
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


def _department_upsert_sql(columns: set[str]) -> str:
    scope_column = department_scope_column(columns)
    insert_columns = ["id", scope_column, "name"]
    for column in _DEPARTMENT_OPTIONAL_COLUMNS:
        if column in columns:
            insert_columns.append(column)
    binds = [":organization_id" if column == scope_column else f":{column}" for column in insert_columns]
    updates = [
        f"{column} = excluded.{column}"
        for column in insert_columns
        if column not in {"id", "created_at"}
    ]
    return (
        f"insert into public.departments ({', '.join(insert_columns)}) "
        f"values ({', '.join(binds)}) "
        f"on conflict (id) do update set {', '.join(updates)}"
    )


def persist_department(store: MemoryStore, record: DepartmentRecord) -> None:
    with sync_session_scope() as session:
        columns = _department_columns(session)
        values: dict[str, Any] = {
            "id": record.id,
            "organization_id": record.organization_id,
            "name": record.name,
        }
        optional_values = {
            "code": record.code,
            "parent_department_id": record.parent_department_id,
            "manager_employee_id": record.manager_employee_id,
            "status": record.status,
            "row_version": 1,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        for column, value in optional_values.items():
            if column in columns:
                values[column] = value
        session.execute(text(_department_upsert_sql(columns)), values)


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


def _text_list(value: Any) -> list[str]:
    if not value:
        return []
    return [str(item) for item in value]


def _employee_from_row(row: EmployeeModel, *, role_code: str | None = None) -> EmployeeRecord:
    return EmployeeRecord(
        id=row.id,
        organization_id=row.organization_id,
        full_name=row.full_name,
        email=row.email,
        title=None,
        department_id=row.department_id,
        is_manager=bool(row.is_manager),
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        employee_code=row.employee_code,
        role_code=role_code,
        approval_authority_limit=_as_float(row.approval_authority_limit),
        phone=row.phone,
        employment_type=row.employment_type or "full_time",
        manager_employee_id=row.manager_employee_id,
        reporting_level=int(row.reporting_level or 1),
        primary_skills=_text_list(row.primary_skills),
        secondary_skills=_text_list(row.secondary_skills),
        skill_level=row.skill_level or "intermediate",
        availability_percent=float(
            100 if row.availability_percent is None else row.availability_percent
        ),
        weekly_capacity_hours=float(
            40 if row.weekly_capacity_hours is None else row.weekly_capacity_hours
        ),
        baseline_workload_percent=float(
            row.current_workload_percent
            if getattr(row, "baseline_workload_percent", None) is None
            else row.baseline_workload_percent
        ),
        current_workload_percent=float(
            row.current_workload_percent if row.current_workload_percent is not None else 0
        ),
        cost_per_hour=_as_float(row.cost_per_hour),
        max_allocation_percent=float(
            row.max_allocation_percent if row.max_allocation_percent is not None else 100
        ),
        approval_tier=row.approval_tier or "none",
    )


def persist_employee(store: MemoryStore, record: EmployeeRecord) -> None:
    with sync_session_scope() as session:
        existing = session.get(EmployeeModel, record.id)
        role_id = existing.role_id if existing is not None else None
        if record.role_code and record.role_code.strip():
            rows = session.execute(
                select(RoleModel.id, RoleModel.tenant_id, RoleModel.code).where(
                    RoleModel.code == record.role_code
                )
            ).all()
            resolved = resolve_role_id(
                [HostedRole(id=row.id, tenant_id=row.tenant_id, code=row.code) for row in rows],
                record.organization_id,
                record.role_code,
            )
            if resolved is not None:
                role_id = resolved
        session.merge(EmployeeModel(**employee_model_values(record, role_id=role_id)))


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


def _supplier_from_row(row: SupplierModel) -> SupplierRecord:
    return SupplierRecord(
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
        supplier_number=row.supplier_number,
        city=row.city,
        address=row.address,
        business_registration_number=row.business_registration_number,
        tax_number=row.tax_number,
        primary_contact_name=row.primary_contact_name,
        primary_contact_email=row.primary_contact_email,
        primary_contact_phone=row.primary_contact_phone,
        secondary_contact_name=row.secondary_contact_name,
        secondary_contact_email=row.secondary_contact_email,
        secondary_contact_phone=row.secondary_contact_phone,
        supplier_category=row.supplier_category or "other",
        products_services=row.products_services,
        lead_time_days=row.lead_time_days,
        minimum_order_quantity=_as_float(row.minimum_order_quantity),
        payment_terms=row.payment_terms,
        preferred_currency=row.preferred_currency or "USD",
        risk_level=row.risk_level or "low",
        compliance_status=row.compliance_status or "pending",
        insurance_valid=bool(row.insurance_valid),
        contract_start_date=row.contract_start_date,
        contract_expiry_date=row.contract_expiry_date,
        certification_details=row.certification_details,
        supplier_rating=_as_float(row.supplier_rating),
        on_time_delivery_percent=_as_float(row.on_time_delivery_percent),
        quality_score_percent=_as_float(row.quality_score_percent),
        average_response_hours=_as_float(row.average_response_hours),
        rejected_orders_count=int(row.rejected_orders_count or 0),
        total_orders_completed=int(row.total_orders_completed or 0),
        approval_tier=row.approval_tier or "none",
        preferred_supplier=bool(row.preferred_supplier),
        blacklisted=bool(row.blacklisted),
        suspension_reason=row.suspension_reason,
        notes=row.notes,
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
                supplier_number=record.supplier_number,
                city=record.city,
                address=record.address,
                business_registration_number=record.business_registration_number,
                tax_number=record.tax_number,
                primary_contact_name=record.primary_contact_name,
                primary_contact_email=record.primary_contact_email,
                primary_contact_phone=record.primary_contact_phone,
                secondary_contact_name=record.secondary_contact_name,
                secondary_contact_email=record.secondary_contact_email,
                secondary_contact_phone=record.secondary_contact_phone,
                supplier_category=record.supplier_category,
                products_services=record.products_services,
                lead_time_days=record.lead_time_days,
                minimum_order_quantity=record.minimum_order_quantity,
                payment_terms=record.payment_terms,
                preferred_currency=record.preferred_currency,
                risk_level=record.risk_level,
                compliance_status=record.compliance_status,
                insurance_valid=record.insurance_valid,
                contract_start_date=record.contract_start_date,
                contract_expiry_date=record.contract_expiry_date,
                certification_details=record.certification_details,
                supplier_rating=record.supplier_rating,
                on_time_delivery_percent=record.on_time_delivery_percent,
                quality_score_percent=record.quality_score_percent,
                average_response_hours=record.average_response_hours,
                rejected_orders_count=record.rejected_orders_count,
                total_orders_completed=record.total_orders_completed,
                approval_tier=record.approval_tier,
                preferred_supplier=record.preferred_supplier,
                blacklisted=record.blacklisted,
                suspension_reason=record.suspension_reason,
                notes=record.notes,
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
                description=record.description,
                owner_employee_id=record.owner_employee_id,
                metadata_json=record.metadata or {},
                status=record.status,
                row_version=1,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )


def _persist_hosted_process(
    session: Session,
    columns: set[str],
    record: ProcessDefinitionRecord,
) -> None:
    values: dict[str, Any] = {
        "id": record.id,
        "tenant_id": record.organization_id,
        "name": record.name,
        "process_type": _HOSTED_PROCESS_TYPE,
    }
    if "description" in columns:
        values["description"] = record.description
    if "status" in columns:
        values["status"] = record.status
    if "created_at" in columns:
        values["created_at"] = record.created_at
    if "updated_at" in columns:
        values["updated_at"] = record.updated_at
    update_columns = [
        column
        for column in ("name", "description", "status", "updated_at")
        if column in values and column != "tenant_id"
    ]
    session.execute(text(_upsert_sql("processes", list(values), update_columns)), values)


def persist_process(store: MemoryStore, record: ProcessDefinitionRecord) -> None:
    with sync_session_scope() as session:
        definition_columns = _public_column_names(session, "process_definitions")
        if "organization_id" in definition_columns:
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
            return
        columns = _public_column_names(session, "processes")
        required = {"id", "tenant_id", "name", "process_type"}
        if required <= columns:
            _persist_hosted_process(session, columns, record)
            return
        raise AppError(
            "Process storage is not available for this database. No process was written.",
            code="PROCESS_STORAGE_UNAVAILABLE",
            status_code=503,
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


def _discovery_values(
    columns: set[str],
    identity: tuple[str, str],
    record: DiscoverySessionRecord | DiscoveryMessageRecord,
) -> dict[str, Any]:
    scope, process_column = identity
    values: dict[str, Any] = {
        "id": record.id,
        scope: record.organization_id,
        process_column: record.process_id,
    }
    optional: dict[str, Any] = {}
    if isinstance(record, DiscoveryMessageRecord):
        values["session_id"] = record.session_id
        values["role"] = record.role
        values["content"] = record.content
        optional = {
            "document_ids": [str(item) for item in record.document_ids],
            "clarifying_questions": _json_value(record.clarifying_questions),
            "intent": _json_value(record.intent),
            "plan_draft": _json_value(record.plan_draft),
            "source_refs": _json_value(record.source_refs),
            "suspicious_flags": _json_value(record.suspicious_flags),
            "created_by_user_id": record.created_by_user_id,
            "created_at": record.created_at,
        }
    else:
        optional = {
            "status": record.status,
            "created_by_user_id": record.created_by_user_id,
            "document_ids": [str(item) for item in record.document_ids],
            "row_version": 1,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
    for column, value in optional.items():
        if column in columns:
            values[column] = value
    return values


def persist_discovery_session(store: MemoryStore, record: DiscoverySessionRecord) -> None:
    with sync_session_scope() as session:
        columns = _public_column_names(session, "discovery_sessions")
        identity = _discovery_identity(columns)
        if identity is None:
            raise _discovery_storage_error()
        values = _discovery_values(columns, identity, record)
        update_columns = [
            column
            for column in ("status", "document_ids", "updated_at", "created_by_user_id")
            if column in values
        ]
        session.execute(
            text(_upsert_sql("discovery_sessions", list(values), update_columns)),
            values,
        )


def persist_discovery_message(store: MemoryStore, record: DiscoveryMessageRecord) -> None:
    with sync_session_scope() as session:
        columns = _public_column_names(session, "discovery_messages")
        identity = _discovery_identity(columns)
        required = {"session_id", "role", "content", "created_at"}
        if identity is None or not required <= columns:
            raise _discovery_storage_error()
        values = _discovery_values(columns, identity, record)
        update_columns = [
            column
            for column in (
                "role",
                "content",
                "document_ids",
                "clarifying_questions",
                "intent",
                "plan_draft",
                "source_refs",
                "suspicious_flags",
            )
            if column in values
        ]
        session.execute(
            text(_upsert_sql("discovery_messages", list(values), update_columns)),
            values,
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
                metadata_json=dict(getattr(record, "metadata", None) or {}),
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


def delete_policy_persistence(organization_id: UUID, policy_id: UUID) -> None:
    """Remove a policy after releasing its current version pointer."""
    params = {"organization_id": organization_id, "policy_id": policy_id}
    statements = (
        """
        UPDATE public.policies
        SET current_version_id = NULL
        WHERE id = :policy_id
          AND organization_id = :organization_id
        """,
        """
        DELETE FROM public.policies
        WHERE id = :policy_id
          AND organization_id = :organization_id
        """,
    )
    with sync_session_scope() as session:
        for statement in statements:
            session.execute(text(statement), params)


def delete_process_persistence(organization_id: UUID, process_id: UUID) -> None:
    """Remove a process and rows that block deleting the definition."""
    params = {"organization_id": organization_id, "process_id": process_id}
    statements = (
        """
        DELETE FROM public.app_execution_artifacts
        WHERE organization_id = :organization_id
          AND process_id = :process_id
        """,
        """
        DELETE FROM public.process_runs
        WHERE organization_id = :organization_id
          AND process_definition_id = :process_id
        """,
        """
        UPDATE public.process_definitions
        SET current_version_id = NULL
        WHERE id = :process_id
          AND organization_id = :organization_id
        """,
        """
        DELETE FROM public.process_definitions
        WHERE id = :process_id
          AND organization_id = :organization_id
        """,
    )
    with sync_session_scope() as session:
        for statement in statements:
            session.execute(text(statement), params)


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
