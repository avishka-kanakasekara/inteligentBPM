"""Plan catalog definitions and entitlement seed rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanDefinition:
    plan_code: str
    display_name: str
    description: str
    sort_order: int
    highlights: tuple[str, ...]


PLAN_CATALOG: dict[str, PlanDefinition] = {
    "pro": PlanDefinition(
        plan_code="pro",
        display_name="Pro",
        description=(
            "One company instance with basic organization management, process discovery, "
            "standard documents/policies/approvals, standard email integration, limited "
            "workflow runs, and standard audit history."
        ),
        sort_order=1,
        highlights=(
            "One company instance",
            "Basic organization management",
            "Basic process discovery",
            "Standard document upload",
            "Standard policies & approvals",
            "Standard email integration",
            "Limited workflow runs",
            "Standard audit history",
        ),
    ),
    "enterprise": PlanDefinition(
        plan_code="enterprise",
        display_name="Enterprise",
        description=(
            "Multiple organizations or business units, higher limits, advanced RBAC, "
            "SSO/SAML, SCIM, custom retention, advanced audit exports, custom approval "
            "policies, advanced supplier workflows, priority support, and custom integrations."
        ),
        sort_order=2,
        highlights=(
            "Multiple orgs / business units",
            "Higher limits",
            "Advanced RBAC",
            "SSO and SAML",
            "SCIM",
            "Custom retention",
            "Advanced audit exports",
            "Custom approval policies",
            "Advanced supplier workflows",
            "Priority support",
            "Custom integrations",
        ),
    ),
    "pro_max": PlanDefinition(
        plan_code="pro_max",
        display_name="Pro Max",
        description=(
            "Highest configurable limits, dedicated worker capacity, advanced model routing, "
            "advanced analytics, custom policy packs, dedicated integrations, extended audit "
            "retention, private networking where supported, and premium support."
        ),
        sort_order=3,
        highlights=(
            "Highest configurable limits",
            "Dedicated worker capacity",
            "Advanced model routing",
            "Advanced analytics",
            "Custom policy packs",
            "Dedicated integrations",
            "Extended audit retention",
            "Private networking (where supported)",
            "Premium support",
        ),
    ),
}


# feature_code -> {plan_code: (numeric_limit, boolean_value, text_value)}
# None numeric means unlimited / N/A; boolean None means not a boolean entitlement.
def _row(
    numeric: float | int | None = None,
    boolean: bool | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    return {"numeric_limit": numeric, "boolean_value": boolean, "text_value": text}


ENTITLEMENT_SEED: dict[str, dict[str, dict[str, Any]]] = {
    # Limits
    "organization.max_users": {
        "pro": _row(25),
        "enterprise": _row(500),
        "pro_max": _row(5000),
    },
    "organization.max_suppliers": {
        "pro": _row(50),
        "enterprise": _row(2000),
        "pro_max": _row(10000),
    },
    "organization.max_orgs": {
        "pro": _row(1),
        "enterprise": _row(50),
        "pro_max": _row(500),
    },
    "process.max_active_definitions": {
        "pro": _row(20),
        "enterprise": _row(200),
        "pro_max": _row(1000),
    },
    "process.monthly_runs": {
        "pro": _row(100),
        "enterprise": _row(2000),
        "pro_max": _row(20000),
    },
    "documents.monthly_pages": {
        "pro": _row(2000),
        "enterprise": _row(50000),
        "pro_max": _row(500000),
    },
    "documents.max_file_size": {
        "pro": _row(10_485_760),  # 10 MiB
        "enterprise": _row(52_428_800),  # 50 MiB
        "pro_max": _row(209_715_200),  # 200 MiB
    },
    "agents.max_concurrent_runs": {
        "pro": _row(2),
        "enterprise": _row(10),
        "pro_max": _row(50),
    },
    "security.audit_retention_days": {
        "pro": _row(90),
        "enterprise": _row(365),
        "pro_max": _row(2555),
    },
    # Boolean features
    "integrations.email_enabled": {
        "pro": _row(boolean=True),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "integrations.supplier_quotes_enabled": {
        "pro": _row(boolean=True),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "integrations.advanced_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "integrations.custom_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "integrations.dedicated_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=False),
        "pro_max": _row(boolean=True),
    },
    "security.sso_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "security.scim_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "security.advanced_rbac_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "analytics.advanced_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "audit.export_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "approvals.custom_policies_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "approvals.multi_role": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "process.discovery": {
        "pro": _row(boolean=True),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "process.execution": {
        "pro": _row(boolean=True),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "documents.upload": {
        "pro": _row(boolean=True),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "workers.dedicated_capacity": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=False),
        "pro_max": _row(boolean=True),
    },
    "models.advanced_routing": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=False),
        "pro_max": _row(boolean=True),
    },
    "policies.custom_packs": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=False),
        "pro_max": _row(boolean=True),
    },
    "networking.private_enabled": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=False),
        "pro_max": _row(boolean=True),
    },
    "support.priority": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=True),
        "pro_max": _row(boolean=True),
    },
    "support.premium": {
        "pro": _row(boolean=False),
        "enterprise": _row(boolean=False),
        "pro_max": _row(boolean=True),
    },
}

# Map usage meters to entitlement limit feature codes
METER_TO_LIMIT: dict[str, str] = {
    "process.monthly_runs": "process.monthly_runs",
    "documents.monthly_pages": "documents.monthly_pages",
    "agents.concurrent_runs": "agents.max_concurrent_runs",
}

PLAN_RANK = {"pro": 1, "enterprise": 2, "pro_max": 3}
