"""Procurement profile fields shared by supplier create/update validation."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.security.errors import ValidationAppError

SUPPLIER_CATEGORIES = frozenset(
    {
        "raw_materials",
        "manufacturing",
        "logistics",
        "it_services",
        "consulting",
        "finance",
        "other",
    }
)
RISK_LEVELS = frozenset({"low", "medium", "high"})
COMPLIANCE_STATUSES = frozenset({"pending", "compliant", "non_compliant", "expired"})
APPROVAL_STATUSES = frozenset({"pending", "approved", "rejected", "suspended"})
APPROVAL_TIERS = frozenset({"none", "team", "department", "business_unit", "executive"})
PERCENT_FIELDS = ("on_time_delivery_percent", "quality_score_percent")
NON_NEGATIVE_FIELDS = (
    "lead_time_days",
    "minimum_order_quantity",
    "average_response_hours",
    "rejected_orders_count",
    "total_orders_completed",
)
CLEARABLE_FIELDS = frozenset(
    {
        "code",
        "website",
        "country_code",
        "city",
        "address",
        "business_registration_number",
        "tax_number",
        "primary_contact_name",
        "primary_contact_email",
        "primary_contact_phone",
        "secondary_contact_name",
        "secondary_contact_email",
        "secondary_contact_phone",
        "products_services",
        "lead_time_days",
        "minimum_order_quantity",
        "payment_terms",
        "certification_details",
        "contract_start_date",
        "contract_expiry_date",
        "supplier_rating",
        "on_time_delivery_percent",
        "quality_score_percent",
        "average_response_hours",
        "suspension_reason",
        "notes",
    }
)
MUTABLE_FIELDS = frozenset(
    {
        "name",
        "code",
        "status",
        "website",
        "country_code",
        "approval_status",
        "city",
        "address",
        "business_registration_number",
        "tax_number",
        "primary_contact_name",
        "primary_contact_email",
        "primary_contact_phone",
        "secondary_contact_name",
        "secondary_contact_email",
        "secondary_contact_phone",
        "supplier_category",
        "products_services",
        "lead_time_days",
        "minimum_order_quantity",
        "payment_terms",
        "preferred_currency",
        "risk_level",
        "compliance_status",
        "insurance_valid",
        "contract_start_date",
        "contract_expiry_date",
        "certification_details",
        "supplier_rating",
        "on_time_delivery_percent",
        "quality_score_percent",
        "average_response_hours",
        "rejected_orders_count",
        "total_orders_completed",
        "approval_tier",
        "preferred_supplier",
        "blacklisted",
        "suspension_reason",
        "notes",
    }
)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def validate_supplier_profile(fields: dict[str, Any]) -> None:
    """Reject values that would break procurement, risk, or approval routing."""
    category = fields.get("supplier_category")
    if category is not None and category not in SUPPLIER_CATEGORIES:
        raise ValidationAppError(
            "supplier_category is not recognized",
            details={"supplier_category": category},
        )

    risk = fields.get("risk_level")
    if risk is not None and risk not in RISK_LEVELS:
        raise ValidationAppError(
            "risk_level must be low, medium, or high",
            details={"risk_level": risk},
        )

    compliance = fields.get("compliance_status")
    if compliance is not None and compliance not in COMPLIANCE_STATUSES:
        raise ValidationAppError(
            "compliance_status is not recognized",
            details={"compliance_status": compliance},
        )

    approval = fields.get("approval_status")
    if approval is not None and approval not in APPROVAL_STATUSES:
        raise ValidationAppError(
            "approval_status must be pending, approved, rejected, or suspended",
            details={"approval_status": approval},
        )

    tier = fields.get("approval_tier")
    if tier is not None and tier not in APPROVAL_TIERS:
        raise ValidationAppError(
            "approval_tier is not recognized",
            details={"approval_tier": tier},
        )

    status = fields.get("status")
    if status is not None and status not in {"active", "inactive", "blocked"}:
        raise ValidationAppError("status must be active, inactive, or blocked")

    rating = fields.get("supplier_rating")
    if rating is not None:
        number = _as_float(rating)
        if number is None or number < 1 or number > 5:
            raise ValidationAppError(
                "supplier_rating must be between 1 and 5",
                details={"supplier_rating": rating},
            )

    for key in PERCENT_FIELDS:
        if key not in fields or fields[key] is None:
            continue
        number = _as_float(fields[key])
        if number is None or number < 0 or number > 100:
            raise ValidationAppError(
                f"{key} must be between 0 and 100",
                details={key: fields[key]},
            )

    for key in NON_NEGATIVE_FIELDS:
        if key not in fields or fields[key] is None:
            continue
        number = _as_float(fields[key])
        if number is None or number < 0:
            raise ValidationAppError(f"{key} cannot be negative", details={key: fields[key]})

    start = fields.get("contract_start_date")
    expiry = fields.get("contract_expiry_date")
    if start is not None and expiry is not None and _as_date(expiry) < _as_date(start):
        raise ValidationAppError("Contract expiry date cannot be before the contract start date")
