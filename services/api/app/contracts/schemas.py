"""Request/response schemas for API v1."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.contracts.common import APIModel


class UserMeResponse(APIModel):
    id: UUID
    email: str | None
    role: str


class OrganizationSummary(APIModel):
    id: UUID
    name: str
    slug: str
    plan_code: str
    status: str
    membership_role: str
    created_at: datetime
    updated_at: datetime


class OrganizationCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    plan_code: str = Field(default="pro")
    organization_id: UUID | None = Field(
        default=None,
        description="Ignored unless it matches authenticated org context",
    )


class OrganizationUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    plan_code: str | None = None
    legal_name: str | None = None
    trading_name: str | None = None
    industry: str | None = None
    country_code: str | None = None
    tax_id: str | None = None
    tax_registration: str | None = None
    tax_country_code: str | None = None
    default_timezone: str | None = None
    default_currency: str | None = None
    tax_information: dict[str, Any] | None = None
    row_version: int | None = None
    organization_id: UUID | None = None


class OrganizationResponse(APIModel):
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
    tax_information: dict[str, Any] = Field(default_factory=dict)


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _skill_list(value: object) -> object:
    if value is None or value == "":
        return value if value is None else []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return value


class EmployeeCreate(APIModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    status: Literal["active", "inactive"] = "active"
    title: str | None = Field(default=None, max_length=160)
    department_id: UUID | None = None
    is_manager: bool = False
    employee_code: str | None = Field(default=None, max_length=40)
    role_code: str | None = Field(default=None, max_length=80)
    approval_authority_limit: float | None = Field(default=None, ge=0)
    approval_authority_currency: str = Field(default="USD", min_length=3, max_length=3)
    phone: str | None = Field(default=None, max_length=40)
    employment_type: Literal["full_time", "part_time", "contract"] = "full_time"
    join_date: date | None = None
    manager_employee_id: UUID | None = None
    team: str | None = Field(default=None, max_length=120)
    business_unit: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    reporting_level: int = Field(default=1, ge=1, le=20)
    primary_skills: list[str] = Field(default_factory=list, max_length=30)
    secondary_skills: list[str] = Field(default_factory=list, max_length=30)
    certifications: list[str] = Field(default_factory=list, max_length=30)
    years_of_experience: float | None = Field(default=None, ge=0, le=80)
    skill_level: Literal["beginner", "intermediate", "expert"] = "intermediate"
    availability_percent: float = Field(default=100, ge=0, le=100)
    weekly_capacity_hours: float = Field(default=40, ge=0, le=168)
    current_workload_percent: float = Field(default=0, ge=0, le=100)
    cost_per_hour: float | None = Field(default=None, ge=0)
    monthly_cost: float | None = Field(default=None, ge=0)
    max_allocation_percent: float = Field(default=100, ge=0, le=100)
    approval_tier: Literal["none", "team", "department", "business_unit", "executive"] = "none"
    can_approve_procurement: bool = False
    can_approve_budget: bool = False
    delegation_authority: bool = False
    tasks_completed: int | None = Field(default=None, ge=0)
    avg_task_completion_hours: float | None = Field(default=None, ge=0)
    sla_compliance_percent: float | None = Field(default=None, ge=0, le=100)
    performance_score: float | None = Field(default=None, ge=0, le=100)
    organization_id: UUID | None = None

    @field_validator(
        "title",
        "phone",
        "team",
        "business_unit",
        "location",
        "role_code",
        "employee_code",
        "department_id",
        "manager_employee_id",
        mode="before",
    )
    @classmethod
    def _empty_optional(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Full name is required")
        return cleaned

    @field_validator("primary_skills", "secondary_skills", "certifications", mode="before")
    @classmethod
    def _lists(cls, value: object) -> object:
        parsed = _skill_list(value)
        return [] if parsed is None else parsed


class EmployeeUpdate(APIModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    title: str | None = Field(default=None, max_length=160)
    department_id: UUID | None = None
    is_manager: bool | None = None
    employee_code: str | None = Field(default=None, max_length=40)
    role_code: str | None = Field(default=None, max_length=80)
    approval_authority_limit: float | None = Field(default=None, ge=0)
    approval_authority_currency: str | None = Field(default=None, min_length=3, max_length=3)
    phone: str | None = Field(default=None, max_length=40)
    employment_type: Literal["full_time", "part_time", "contract"] | None = None
    join_date: date | None = None
    manager_employee_id: UUID | None = None
    team: str | None = Field(default=None, max_length=120)
    business_unit: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    reporting_level: int | None = Field(default=None, ge=1, le=20)
    primary_skills: list[str] | None = Field(default=None, max_length=30)
    secondary_skills: list[str] | None = Field(default=None, max_length=30)
    certifications: list[str] | None = Field(default=None, max_length=30)
    years_of_experience: float | None = Field(default=None, ge=0, le=80)
    skill_level: Literal["beginner", "intermediate", "expert"] | None = None
    availability_percent: float | None = Field(default=None, ge=0, le=100)
    weekly_capacity_hours: float | None = Field(default=None, ge=0, le=168)
    current_workload_percent: float | None = Field(default=None, ge=0, le=100)
    cost_per_hour: float | None = Field(default=None, ge=0)
    monthly_cost: float | None = Field(default=None, ge=0)
    max_allocation_percent: float | None = Field(default=None, ge=0, le=100)
    approval_tier: Literal["none", "team", "department", "business_unit", "executive"] | None = None
    can_approve_procurement: bool | None = None
    can_approve_budget: bool | None = None
    delegation_authority: bool | None = None
    status: Literal["active", "inactive"] | None = None
    tasks_completed: int | None = Field(default=None, ge=0)
    avg_task_completion_hours: float | None = Field(default=None, ge=0)
    sla_compliance_percent: float | None = Field(default=None, ge=0, le=100)
    performance_score: float | None = Field(default=None, ge=0, le=100)
    organization_id: UUID | None = None

    @field_validator(
        "title",
        "phone",
        "team",
        "business_unit",
        "location",
        "role_code",
        "employee_code",
        "department_id",
        "manager_employee_id",
        mode="before",
    )
    @classmethod
    def _empty_optional(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Full name is required")
        return cleaned

    @field_validator("primary_skills", "secondary_skills", "certifications", mode="before")
    @classmethod
    def _lists(cls, value: object) -> object:
        if value is None:
            return None
        return _skill_list(value)


class EmployeeResponse(APIModel):
    id: UUID
    organization_id: UUID
    full_name: str
    email: str
    title: str | None = None
    department_id: UUID | None = None
    is_manager: bool
    status: str
    employee_code: str | None = None
    role_code: str | None = None
    approval_authority_limit: float | None = None
    approval_authority_currency: str = "USD"
    phone: str | None = None
    employment_type: str = "full_time"
    join_date: date | None = None
    manager_employee_id: UUID | None = None
    team: str | None = None
    business_unit: str | None = None
    location: str | None = None
    reporting_level: int = 1
    primary_skills: list[str] = Field(default_factory=list)
    secondary_skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    years_of_experience: float | None = None
    skill_level: str = "intermediate"
    availability_percent: float = 100
    weekly_capacity_hours: float = 40
    current_workload_percent: float = 0
    cost_per_hour: float | None = None
    monthly_cost: float | None = None
    max_allocation_percent: float = 100
    approval_tier: str = "none"
    can_approve_procurement: bool = False
    can_approve_budget: bool = False
    delegation_authority: bool = False
    tasks_completed: int | None = None
    avg_task_completion_hours: float | None = None
    sla_compliance_percent: float | None = None
    performance_score: float | None = None
    created_at: datetime
    updated_at: datetime


class ManagerLinkCreate(APIModel):
    employee_id: UUID
    manager_employee_id: UUID
    link_type: str = "direct"
    organization_id: UUID | None = None


class ManagerLinkResponse(APIModel):
    id: UUID
    organization_id: UUID
    employee_id: UUID
    manager_employee_id: UUID
    link_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class DepartmentCreate(APIModel):
    name: str
    code: str | None = None
    parent_department_id: UUID | None = None
    manager_employee_id: UUID | None = None
    organization_id: UUID | None = None


class DepartmentUpdate(APIModel):
    name: str | None = None
    code: str | None = None
    parent_department_id: UUID | None = None
    manager_employee_id: UUID | None = None
    organization_id: UUID | None = None


class DepartmentResponse(APIModel):
    id: UUID
    organization_id: UUID
    name: str
    code: str | None
    status: str
    parent_department_id: UUID | None = None
    manager_employee_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class CostCenterCreate(APIModel):
    code: str
    name: str
    department_id: UUID | None = None
    organization_id: UUID | None = None


class CostCenterUpdate(APIModel):
    code: str | None = None
    name: str | None = None
    department_id: UUID | None = None
    organization_id: UUID | None = None


class CostCenterResponse(APIModel):
    id: UUID
    organization_id: UUID
    code: str
    name: str
    department_id: UUID | None
    status: str
    created_at: datetime
    updated_at: datetime


def _optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("Enter a valid email address")
    return normalized


class SupplierCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=40)
    status: Literal["active", "inactive"] = "active"
    website: str | None = Field(default=None, max_length=300)
    country_code: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=300)
    business_registration_number: str | None = Field(default=None, max_length=80)
    tax_number: str | None = Field(default=None, max_length=80)
    primary_contact_name: str | None = Field(default=None, max_length=160)
    primary_contact_email: str | None = None
    primary_contact_phone: str | None = Field(default=None, max_length=40)
    secondary_contact_name: str | None = Field(default=None, max_length=160)
    secondary_contact_email: str | None = None
    secondary_contact_phone: str | None = Field(default=None, max_length=40)
    supplier_category: Literal[
        "raw_materials",
        "manufacturing",
        "logistics",
        "it_services",
        "consulting",
        "finance",
        "other",
    ] = "other"
    products_services: str | None = Field(default=None, max_length=1000)
    lead_time_days: int | None = Field(default=None, ge=0)
    minimum_order_quantity: float | None = Field(default=None, ge=0)
    payment_terms: str | None = Field(default=None, max_length=160)
    preferred_currency: str = Field(default="USD", min_length=3, max_length=3)
    risk_level: Literal["low", "medium", "high"] = "low"
    compliance_status: Literal["pending", "compliant", "non_compliant", "expired"] = "pending"
    insurance_valid: bool = False
    contract_start_date: date | None = None
    contract_expiry_date: date | None = None
    certification_details: str | None = Field(default=None, max_length=1000)
    supplier_rating: float | None = Field(default=None, ge=1, le=5)
    on_time_delivery_percent: float | None = Field(default=None, ge=0, le=100)
    quality_score_percent: float | None = Field(default=None, ge=0, le=100)
    average_response_hours: float | None = Field(default=None, ge=0)
    rejected_orders_count: int = Field(default=0, ge=0)
    total_orders_completed: int = Field(default=0, ge=0)
    approval_status: Literal["pending", "approved", "rejected", "suspended"] = "pending"
    approval_tier: Literal["none", "team", "department", "business_unit", "executive"] = "none"
    preferred_supplier: bool = False
    blacklisted: bool = False
    suspension_reason: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    organization_id: UUID | None = None

    @field_validator(
        "code",
        "website",
        "country_code",
        "city",
        "address",
        "business_registration_number",
        "tax_number",
        "primary_contact_name",
        "primary_contact_phone",
        "secondary_contact_name",
        "secondary_contact_phone",
        "products_services",
        "payment_terms",
        "certification_details",
        "suspension_reason",
        "notes",
        mode="before",
    )
    @classmethod
    def _empty_optional(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Company name is required")
        return cleaned

    @field_validator("primary_contact_email", "secondary_contact_email")
    @classmethod
    def _contact_email(cls, value: str | None) -> str | None:
        return _optional_email(value)


class SupplierUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=40)
    status: Literal["active", "inactive"] | None = None
    website: str | None = Field(default=None, max_length=300)
    country_code: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=300)
    business_registration_number: str | None = Field(default=None, max_length=80)
    tax_number: str | None = Field(default=None, max_length=80)
    primary_contact_name: str | None = Field(default=None, max_length=160)
    primary_contact_email: str | None = None
    primary_contact_phone: str | None = Field(default=None, max_length=40)
    secondary_contact_name: str | None = Field(default=None, max_length=160)
    secondary_contact_email: str | None = None
    secondary_contact_phone: str | None = Field(default=None, max_length=40)
    supplier_category: Literal[
        "raw_materials",
        "manufacturing",
        "logistics",
        "it_services",
        "consulting",
        "finance",
        "other",
    ] | None = None
    products_services: str | None = Field(default=None, max_length=1000)
    lead_time_days: int | None = Field(default=None, ge=0)
    minimum_order_quantity: float | None = Field(default=None, ge=0)
    payment_terms: str | None = Field(default=None, max_length=160)
    preferred_currency: str | None = Field(default=None, min_length=3, max_length=3)
    risk_level: Literal["low", "medium", "high"] | None = None
    compliance_status: Literal["pending", "compliant", "non_compliant", "expired"] | None = None
    insurance_valid: bool | None = None
    contract_start_date: date | None = None
    contract_expiry_date: date | None = None
    certification_details: str | None = Field(default=None, max_length=1000)
    supplier_rating: float | None = Field(default=None, ge=1, le=5)
    on_time_delivery_percent: float | None = Field(default=None, ge=0, le=100)
    quality_score_percent: float | None = Field(default=None, ge=0, le=100)
    average_response_hours: float | None = Field(default=None, ge=0)
    rejected_orders_count: int | None = Field(default=None, ge=0)
    total_orders_completed: int | None = Field(default=None, ge=0)
    approval_status: Literal["pending", "approved", "rejected", "suspended"] | None = None
    approval_tier: Literal["none", "team", "department", "business_unit", "executive"] | None = None
    preferred_supplier: bool | None = None
    blacklisted: bool | None = None
    suspension_reason: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    organization_id: UUID | None = None

    @field_validator(
        "code",
        "website",
        "country_code",
        "city",
        "address",
        "business_registration_number",
        "tax_number",
        "primary_contact_name",
        "primary_contact_phone",
        "secondary_contact_name",
        "secondary_contact_phone",
        "products_services",
        "payment_terms",
        "certification_details",
        "suspension_reason",
        "notes",
        mode="before",
    )
    @classmethod
    def _empty_optional(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Company name is required")
        return cleaned

    @field_validator("primary_contact_email", "secondary_contact_email")
    @classmethod
    def _contact_email(cls, value: str | None) -> str | None:
        return _optional_email(value)


class SupplierResponse(APIModel):
    id: UUID
    organization_id: UUID
    name: str
    code: str | None = None
    status: str
    approval_status: str = "pending"
    website: str | None = None
    country_code: str | None = None
    supplier_number: str | None = None
    city: str | None = None
    address: str | None = None
    business_registration_number: str | None = None
    tax_number: str | None = None
    primary_contact_name: str | None = None
    primary_contact_email: str | None = None
    primary_contact_phone: str | None = None
    secondary_contact_name: str | None = None
    secondary_contact_email: str | None = None
    secondary_contact_phone: str | None = None
    supplier_category: str = "other"
    products_services: str | None = None
    lead_time_days: int | None = None
    minimum_order_quantity: float | None = None
    payment_terms: str | None = None
    preferred_currency: str = "USD"
    risk_level: str = "low"
    compliance_status: str = "pending"
    insurance_valid: bool = False
    contract_start_date: date | None = None
    contract_expiry_date: date | None = None
    certification_details: str | None = None
    supplier_rating: float | None = None
    on_time_delivery_percent: float | None = None
    quality_score_percent: float | None = None
    average_response_hours: float | None = None
    rejected_orders_count: int = 0
    total_orders_completed: int = 0
    approval_tier: str = "none"
    preferred_supplier: bool = False
    blacklisted: bool = False
    suspension_reason: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class SupplierContactCreate(APIModel):
    supplier_id: UUID
    full_name: str
    email: str | None = None
    is_primary: bool = False
    phone: str | None = None
    role_title: str | None = None
    allow_duplicate_email: bool = False
    organization_id: UUID | None = None


class SupplierContactResponse(APIModel):
    id: UUID
    organization_id: UUID
    supplier_id: UUID
    full_name: str
    email: str | None
    is_primary: bool
    status: str
    phone: str | None = None
    role_title: str | None = None
    allow_duplicate_email: bool = False
    created_at: datetime
    updated_at: datetime


class SupplierProductCreate(APIModel):
    supplier_id: UUID
    name: str
    sku: str | None = None
    unit_price: float | None = None
    currency_code: str = "USD"
    description: str | None = None
    unit_of_measure: str | None = None
    organization_id: UUID | None = None


class SupplierProductResponse(APIModel):
    id: UUID
    organization_id: UUID
    supplier_id: UUID
    name: str
    sku: str | None
    unit_price: float | None
    currency_code: str
    status: str
    description: str | None = None
    unit_of_measure: str | None = None
    created_at: datetime
    updated_at: datetime


class BudgetCreate(APIModel):
    name: str
    fiscal_year: int
    amount_total: float
    currency_code: str = "USD"
    department_id: UUID | None = None
    cost_center_id: UUID | None = None
    organization_id: UUID | None = None


class BudgetUpdate(APIModel):
    name: str | None = None
    fiscal_year: int | None = None
    amount_total: float | None = None
    currency_code: str | None = None
    department_id: UUID | None = None
    cost_center_id: UUID | None = None
    organization_id: UUID | None = None


class BudgetResponse(APIModel):
    id: UUID
    organization_id: UUID
    name: str
    fiscal_year: int
    amount_total: float
    currency_code: str
    status: str
    department_id: UUID | None = None
    cost_center_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class PolicyCreate(APIModel):
    code: str
    title: str
    category: str | None = None
    description: str | None = None
    owner_employee_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    organization_id: UUID | None = None


class PolicyUpdate(APIModel):
    code: str | None = None
    title: str | None = None
    category: str | None = None
    description: str | None = None
    owner_employee_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    status: str | None = None
    organization_id: UUID | None = None


class PolicyResponse(APIModel):
    id: UUID
    organization_id: UUID
    code: str
    title: str
    status: str
    category: str | None = None
    description: str | None = None
    owner_employee_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class RoleCatalogItem(APIModel):
    code: str
    label: str
    description: str


class ImportPreviewRequest(APIModel):
    csv_content: str = Field(min_length=1)
    organization_id: UUID | None = None


class ImportRowErrorResponse(APIModel):
    row_number: int
    field: str | None
    code: str
    message: str


class ImportPreviewResponse(APIModel):
    total_rows: int
    valid_count: int
    error_count: int
    duplicate_count: int
    valid_rows: list[dict[str, Any]]
    errors: list[ImportRowErrorResponse]
    duplicates: list[ImportRowErrorResponse]


class ImportCommitResponse(APIModel):
    created_ids: list[str]
    created_count: int


class DocumentUploadUrlRequest(APIModel):
    filename: str
    content_type: str = "application/pdf"
    organization_id: UUID | None = None


class DocumentUploadUrlResponse(APIModel):
    bucket: str
    path: str
    upload_url: str
    content_type: str


class DocumentCreate(APIModel):
    title: str
    storage_path: str
    file_name: str | None = None
    mime_type: str | None = None
    byte_size: int | None = None
    content_hash: str | None = None
    source_type: str = "upload"
    classification: str = "internal"
    access_scope: str = "organization"
    document_type: str = "general"
    organization_id: UUID | None = None


class DocumentIngestRequest(APIModel):
    title: str
    file_name: str
    content_base64: str
    mime_type: str | None = None
    source_type: str = "upload"
    classification: str = "internal"
    access_scope: str = "organization"
    document_type: str = "general"
    apply_redaction: bool = True
    organization_id: UUID | None = None


class DocumentResponse(APIModel):
    id: UUID
    organization_id: UUID
    title: str
    storage_path: str
    status: str
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
    suspicious_flags: list[str] = Field(default_factory=list)
    redacted: bool = False


class DocumentChunkResponse(APIModel):
    id: UUID
    organization_id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    page_number: int | None = None
    section_heading: str | None = None
    token_count: int | None = None
    is_redacted: bool = False
    suspicious: bool = False
    embedding_model: str | None = None


class DocumentSearchRequest(APIModel):
    query: str = Field(min_length=1)
    mode: str = Field(default="hybrid", pattern="^(keyword|vector|hybrid)$")
    limit: int = Field(default=8, ge=1, le=50)
    similarity_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    document_id: UUID | None = None
    include_agent_context: bool = False
    organization_id: UUID | None = None


class DocumentCitationResponse(APIModel):
    document_id: str
    chunk_id: str
    file_name: str | None
    page_number: int | None
    section_heading: str | None
    excerpt: str


class DocumentSearchHitResponse(APIModel):
    chunk_id: UUID
    document_id: UUID
    organization_id: UUID
    chunk_index: int
    content: str
    score: float
    page_number: int | None
    section_heading: str | None
    file_name: str | None
    title: str
    suspicious: bool
    citation: DocumentCitationResponse


class DocumentSearchResponse(APIModel):
    hits: list[DocumentSearchHitResponse]
    agent_context: str | None = None


class ProcessCreate(APIModel):
    name: str
    description: str | None = None
    organization_id: UUID | None = None


class ProcessResponse(APIModel):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    status: str
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class SourceRef(APIModel):
    type: str = "document"
    id: str = ""
    label: str = ""


class ProcessSummaryResponse(APIModel):
    """Summary view matching the frontend ProcessSummary schema."""

    id: UUID
    name: str
    status: str
    risk_level: str | None = None
    approval_status: str | None = None
    execution_status: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    unresolved_assignments: list[str] = Field(default_factory=list)
    policy_evidence: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    human_decision: str | None = None
    has_allocation: bool = False
    has_risk: bool = False
    has_execution: bool = False
    updated_at: datetime


class RiskItem(APIModel):
    id: str
    category: str
    severity: str
    description: str
    blocking: bool
    required_remediation: str
    required_approver: str | None = None
    policy_code: str | None = None


class ApprovalSummaryResponse(APIModel):
    """Summary view matching the frontend ApprovalSummary schema."""

    id: UUID
    process_id: UUID | None = None
    process_name: str = ""
    status: str
    risk_level: str = "low"
    risk_decision: str | None = None
    required_roles: list[str] = Field(default_factory=list)
    snapshot_hash: str
    plan_snapshot_hash: str | None = None
    risk_snapshot_hash: str | None = None
    policy_evidence: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    decision_note: str | None = None
    risk_summary: str | None = None
    risk_items: list[RiskItem] | None = None
    blocking_explanation: str | None = None
    updated_at: datetime


class ProcessVersionCreate(APIModel):
    plan_snapshot: dict[str, Any]
    organization_id: UUID | None = None


class ProcessVersionResponse(APIModel):
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


class DiscoveryChatRequest(APIModel):
    message: str
    document_ids: list[UUID] = Field(default_factory=list)
    organization_id: UUID | None = None


class DiscoveryChatMessageResponse(APIModel):
    id: UUID
    organization_id: UUID
    process_id: UUID
    session_id: UUID
    role: str
    content: str
    document_ids: list[UUID] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    intent: dict[str, Any] | None = None
    plan_draft: dict[str, Any] | None = None
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    suspicious_flags: list[str] = Field(default_factory=list)
    created_by_user_id: UUID | None = None
    created_at: datetime


class DiscoveryChatHistoryResponse(APIModel):
    session_id: UUID | None = None
    messages: list[DiscoveryChatMessageResponse]


class DraftPlanRequest(APIModel):
    revision_of_version_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list)
    instructions: str | None = None
    organization_id: UUID | None = None


class DraftPlanResponse(APIModel):
    version_id: UUID
    version_number: int
    status: str
    plan: dict[str, Any]
    plan_snapshot_hash: str


class ConfirmPlanResponse(APIModel):
    version_id: UUID
    version_number: int
    status: str
    confirmed_at: datetime | None
    plan: dict[str, Any]


class AllocateResourcesRequest(APIModel):
    process_version_id: UUID | None = None
    clarification_choices: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None
    organization_id: UUID | None = None


class AllocateResourcesResponse(APIModel):
    organization_id: UUID
    process_id: UUID
    process_version_id: UUID
    status: str
    assignments: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: list[dict[str, Any]] = Field(default_factory=list)
    integrations: list[dict[str, Any]] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    llm_used: bool = False
    invented_resources: bool = False
    side_effects_executed: bool = False
    organization_profile: dict[str, Any] | None = None


class RiskAnalyzeRequest(APIModel):
    process_version_id: UUID | None = None
    allocation_id: UUID | None = None
    spending_amount: float | None = None
    quotation_count: int | None = None
    geographic_region: str | None = None
    handles_restricted_data: bool | None = None
    notes: str | None = None
    organization_id: UUID | None = None


class RiskResultResponse(APIModel):
    organization_id: UUID
    process_id: UUID
    process_version_id: UUID
    allocation_id: UUID | None = None
    decision: str
    overall_status: str
    risk_items: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    required_approvals: list[dict[str, Any]] = Field(default_factory=list)
    required_approver_roles: list[str] = Field(default_factory=list)
    policy_evidence: list[dict[str, Any]] = Field(default_factory=list)
    ambiguous_findings: list[dict[str, Any]] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    plan_snapshot_hash: str
    allocation_snapshot_hash: str | None = None
    risk_snapshot_hash: str
    reasoning_summary: str = ""
    llm_used: bool = False
    gemini_approved: bool = False
    valid: bool = True
    invalidated_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ApprovalResponse(APIModel):
    id: UUID
    organization_id: UUID
    process_run_id: UUID | None
    status: str
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
    required_roles: list[str] = Field(default_factory=list)
    prohibited_action: bool = False
    override_required: bool = False


class ApprovalDecisionRequest(APIModel):
    decision: str
    note: str | None = None
    row_version: int
    organization_id: UUID | None = None


class ProcessRunCreate(APIModel):
    process_id: UUID
    process_version_id: UUID | None = None
    organization_id: UUID | None = None


class ProcessRunResponse(APIModel):
    id: UUID
    organization_id: UUID
    process_id: UUID
    process_version_id: UUID | None
    status: str
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


class ExecutionStartRequest(APIModel):
    dry_run: bool = False
    auto_run: bool = False
    max_steps: int = 20
    process_version_id: UUID | None = None
    approval_id: UUID | None = None
    organization_id: UUID | None = None


class ExecutionInvokeRequest(APIModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    process_run_id: UUID | None = None
    dry_run: bool | None = None
    organization_id: UUID | None = None


class ExecutionStateResponse(APIModel):
    process_id: UUID
    process_run_id: UUID
    status: str
    dry_run: bool = False
    current_step_index: int = 0
    pause_reason: str | None = None
    plan_snapshot_hash: str | None = None
    risk_snapshot_hash: str | None = None
    approval_id: UUID | None = None
    tool_invocations: list[dict[str, Any]] = Field(default_factory=list)
    human_checkpoints: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    email_outbox: list[dict[str, Any]] = Field(default_factory=list)


class ToolDefinitionResponse(APIModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permission: str
    risk_level: str
    side_effect_status: str
    required_approval_type: str
    idempotency_behavior: str
    organization_scope: bool = True
    provider_support: str = "both"
    retry_behavior: str = "safe_retry"
    timeout_seconds: float = 30.0


class ToolInvocationResponse(APIModel):
    id: UUID
    organization_id: UUID
    process_id: UUID
    process_run_id: UUID
    tool_name: str
    arguments: dict[str, Any]
    idempotency_key: str | None = None
    status: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    plan_snapshot_hash: str | None = None
    risk_snapshot_hash: str | None = None
    approval_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class QuotationCompareRequest(APIModel):
    quotation_ids: list[str]
    explain: bool = True


class PurchaseOrderSubmitRequest(APIModel):
    process_id: UUID | None = None
    process_run_id: UUID | None = None
    idempotency_key: str
    dry_run: bool | None = None
    organization_id: UUID | None = None
