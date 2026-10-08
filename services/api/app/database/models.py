"""SQLAlchemy ORM models for Postgres persistence mode."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OrganizationModel(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    plan_code: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[str | None] = mapped_column(Text)
    trading_name: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(Text)
    tax_id: Mapped[str | None] = mapped_column(Text)
    tax_registration: Mapped[str | None] = mapped_column(Text)
    tax_country_code: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DepartmentModel(Base):
    __tablename__ = "departments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text)
    parent_department_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    manager_employee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CostCenterModel(Base):
    __tablename__ = "cost_centers"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    department_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmployeeModel(Base):
    __tablename__ = "employees"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    employee_code: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    department_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    is_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    role_code: Mapped[str | None] = mapped_column(Text)
    approval_authority_limit: Mapped[float | None] = mapped_column(Numeric(18, 2))
    approval_authority_currency: Mapped[str] = mapped_column(Text, nullable=False, default="USD")
    phone: Mapped[str | None] = mapped_column(Text)
    employment_type: Mapped[str] = mapped_column(Text, nullable=False, default="full_time")
    join_date: Mapped[date | None] = mapped_column(Date)
    manager_employee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    team: Mapped[str | None] = mapped_column(Text)
    business_unit: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    reporting_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    primary_skills: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    secondary_skills: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    certifications: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    years_of_experience: Mapped[float | None] = mapped_column(Numeric(5, 1))
    skill_level: Mapped[str] = mapped_column(Text, nullable=False, default="intermediate")
    availability_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=100)
    weekly_capacity_hours: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=40)
    baseline_workload_percent: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    current_workload_percent: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    cost_per_hour: Mapped[float | None] = mapped_column(Numeric(18, 2))
    monthly_cost: Mapped[float | None] = mapped_column(Numeric(18, 2))
    max_allocation_percent: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=100
    )
    approval_tier: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    can_approve_procurement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_approve_budget: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delegation_authority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tasks_completed: Mapped[int | None] = mapped_column(Integer)
    avg_task_completion_hours: Mapped[float | None] = mapped_column(Numeric(8, 2))
    sla_compliance_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))
    performance_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmployeeManagerLinkModel(Base):
    __tablename__ = "employee_manager_links"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    manager_employee_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    link_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupplierModel(Base):
    __tablename__ = "suppliers"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    website: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    supplier_number: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    business_registration_number: Mapped[str | None] = mapped_column(Text)
    tax_number: Mapped[str | None] = mapped_column(Text)
    primary_contact_name: Mapped[str | None] = mapped_column(Text)
    primary_contact_email: Mapped[str | None] = mapped_column(Text)
    primary_contact_phone: Mapped[str | None] = mapped_column(Text)
    secondary_contact_name: Mapped[str | None] = mapped_column(Text)
    secondary_contact_email: Mapped[str | None] = mapped_column(Text)
    secondary_contact_phone: Mapped[str | None] = mapped_column(Text)
    supplier_category: Mapped[str] = mapped_column(Text, nullable=False, default="other")
    products_services: Mapped[str | None] = mapped_column(Text)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    minimum_order_quantity: Mapped[float | None] = mapped_column(Numeric(18, 2))
    payment_terms: Mapped[str | None] = mapped_column(Text)
    preferred_currency: Mapped[str] = mapped_column(Text, nullable=False, default="USD")
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, default="low")
    compliance_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    insurance_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contract_start_date: Mapped[date | None] = mapped_column(Date)
    contract_expiry_date: Mapped[date | None] = mapped_column(Date)
    certification_details: Mapped[str | None] = mapped_column(Text)
    supplier_rating: Mapped[float | None] = mapped_column(Numeric(3, 2))
    on_time_delivery_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))
    quality_score_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))
    average_response_hours: Mapped[float | None] = mapped_column(Numeric(8, 2))
    rejected_orders_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_orders_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approval_tier: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    preferred_supplier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blacklisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suspension_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupplierContactModel(Base):
    __tablename__ = "supplier_contacts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    role_title: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    allow_duplicate_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupplierProductModel(Base):
    __tablename__ = "supplier_products"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    sku: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    unit_of_measure: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    currency_code: Mapped[str] = mapped_column(Text, nullable=False, default="USD")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BudgetModel(Base):
    __tablename__ = "budgets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    department_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    cost_center_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(Text, nullable=False, default="USD")
    amount_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    amount_spent: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyModel(Base):
    __tablename__ = "policies"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrganizationMembershipModel(Base):
    __tablename__ = "organization_memberships"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessDefinitionModel(Base):
    __tablename__ = "process_definitions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessVersionModel(Base):
    __tablename__ = "process_versions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    process_definition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    plan_snapshot_hash: Mapped[str] = mapped_column(Text, nullable=False)
    allocation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    allocation_snapshot_hash: Mapped[str | None] = mapped_column(Text)
    risk_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    risk_snapshot_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DiscoverySessionModel(Base):
    __tablename__ = "discovery_sessions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    process_definition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    document_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DiscoveryMessageModel(Base):
    __tablename__ = "discovery_messages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    process_definition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    document_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False)
    clarifying_questions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    plan_draft: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    suspicious_flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessWorkflowArtifactModel(Base):
    __tablename__ = "process_workflow_artifacts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    process_definition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    process_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    plan_snapshot_hash: Mapped[str | None] = mapped_column(Text)
    allocation_snapshot_hash: Mapped[str | None] = mapped_column(Text)
    risk_snapshot_hash: Mapped[str | None] = mapped_column(Text)
    valid: Mapped[bool | None] = mapped_column(Boolean)
    invalidated_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppProcessRunModel(Base):
    __tablename__ = "app_process_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    process_definition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    process_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    initiated_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    correlation_id: Mapped[str | None] = mapped_column(Text)
    plan_snapshot_hash: Mapped[str | None] = mapped_column(Text)
    risk_snapshot_hash: Mapped[str | None] = mapped_column(Text)
    approval_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pause_reason: Mapped[str | None] = mapped_column(Text)
    allowed_tools: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutionArtifactModel(Base):
    __tablename__ = "app_execution_artifacts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    process_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    process_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    artifact_kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
