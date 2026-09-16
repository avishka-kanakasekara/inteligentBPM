"""Domain enums and value objects."""

from __future__ import annotations

from enum import StrEnum


class OrgRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"
    COMPLIANCE = "compliance"
    AUDITOR = "auditor"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"
    REMOVED = "removed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ProcessRunStatus(StrEnum):
    DRAFT = "draft"
    DISCOVERING = "discovering"
    PLAN_READY = "plan_ready"
    ALLOCATING = "allocating"
    ALLOCATED = "allocated"
    ANALYZING_RISK = "analyzing_risk"
    RISK_COMPLETE = "risk_complete"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    SCANNING = "scanning"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    ARCHIVED = "archived"
