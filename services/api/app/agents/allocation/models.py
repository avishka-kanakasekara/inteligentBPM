"""Typed models for Agent 2 — Resource and Company Context Allocation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ResourceType(StrEnum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    DEPARTMENT = "department"
    SUPPLIER = "supplier"
    SUPPLIER_CONTACT = "supplier_contact"
    PRODUCT = "product"
    BUDGET = "budget"
    COST_CENTER = "cost_center"
    APPROVAL_AUTHORITY = "approval_authority"
    INTEGRATION = "integration"
    ORGANIZATION = "organization"
    UNKNOWN = "unknown"


class AuthorizationStatus(StrEnum):
    AUTHORIZED = "authorized"
    UNAUTHORIZED = "unauthorized"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ConflictStatus(StrEnum):
    NONE = "none"
    AMBIGUOUS = "ambiguous"
    INACTIVE = "inactive"
    UNAPPROVED = "unapproved"
    MISSING_CONTACT = "missing_contact"
    BUDGET_MISMATCH = "budget_mismatch"
    CROSS_TENANT = "cross_tenant"
    RULE_VIOLATION = "rule_violation"


class DataSource(StrEnum):
    DIRECTORY_QUERY = "directory_query"
    SUPPLIER_QUERY = "supplier_query"
    BUDGET_QUERY = "budget_query"
    MANAGER_LINK = "manager_link"
    DEPARTMENT_RULE = "department_rule"
    ROLE_RULE = "role_rule"
    USER_CLARIFICATION = "user_clarification"
    INTEGRATION_CATALOG = "integration_catalog"
    ORGANIZATION_PROFILE = "organization_profile"
    LLM_INTERPRETATION = "llm_interpretation"


class ResourceCandidate(BaseModel):
    resource_id: str
    resource_type: ResourceType
    display_name: str
    reason: str
    data_source: DataSource
    confidence: float = Field(ge=0.0, le=1.0)
    authorization_status: AuthorizationStatus = AuthorizationStatus.UNKNOWN
    active_status: bool = True
    conflict_status: ConflictStatus = ConflictStatus.NONE
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceAssignment(BaseModel):
    step_id: str
    requirement: str
    resource_id: str
    resource_type: ResourceType
    reason: str
    data_source: DataSource
    confidence: float = Field(ge=0.0, le=1.0)
    authorization_status: AuthorizationStatus
    active_status: bool
    conflict_status: ConflictStatus = ConflictStatus.NONE
    display_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceConflict(BaseModel):
    id: str
    step_id: str
    requirement: str
    conflict_status: ConflictStatus
    message: str
    candidates: list[ResourceCandidate] = Field(default_factory=list)
    data_source: DataSource = DataSource.DIRECTORY_QUERY


class UnresolvedResource(BaseModel):
    id: str
    step_id: str
    requirement: str
    resource_type: ResourceType = ResourceType.UNKNOWN
    question: str
    blocking: bool = True
    candidates: list[ResourceCandidate] = Field(default_factory=list)
    suggested_alternatives: list[str] = Field(default_factory=list)


class ClarificationChoice(BaseModel):
    step_id: str
    requirement: str
    resource_id: str
    resource_type: ResourceType


class ResourceAllocationRequest(BaseModel):
    process_id: UUID
    process_version_id: UUID | None = None
    clarification_choices: list[ClarificationChoice] = Field(default_factory=list)
    notes: str | None = None


class IntegrationAvailability(BaseModel):
    key: str
    available: bool
    mode: Literal["mock", "live", "disabled"] = "mock"
    reason: str


class OrganizationProfileSnapshot(BaseModel):
    organization_id: UUID
    name: str
    plan_code: str
    industry: str | None = None
    country_code: str | None = None
    default_currency: str = "USD"
    status: str


class ResourceAllocationResult(BaseModel):
    schema_version: str = "1"
    organization_id: UUID
    process_id: UUID
    process_version_id: UUID
    status: Literal["resolved", "needs_clarification", "blocked"] = "needs_clarification"
    organization_profile: OrganizationProfileSnapshot | None = None
    assignments: list[ResourceAssignment] = Field(default_factory=list)
    candidates: list[ResourceCandidate] = Field(default_factory=list)
    conflicts: list[ResourceConflict] = Field(default_factory=list)
    unresolved: list[UnresolvedResource] = Field(default_factory=list)
    integrations: list[IntegrationAvailability] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    llm_used: bool = False
    invented_resources: bool = False
    side_effects_executed: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AllocationAssistOutput(BaseModel):
    """Gemini assist payload — may propose catalog resource IDs only (never invent)."""

    role_interpretations: list[dict[str, str]] = Field(default_factory=list)
    requirement_mappings: list[dict[str, str]] = Field(default_factory=list)
    proposed_assignments: list[dict[str, str]] = Field(default_factory=list)
    candidate_explanations: list[str] = Field(default_factory=list)
    conflict_explanations: list[str] = Field(default_factory=list)
    alternative_suggestions: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
