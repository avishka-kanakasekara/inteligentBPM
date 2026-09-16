"""Deterministic resource matching for Agent 2 (no LLM, no side effects)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.agents.allocation.models import (
    AuthorizationStatus,
    ConflictStatus,
    DataSource,
    ResourceCandidate,
    ResourceConflict,
    ResourceType,
    UnresolvedResource,
)
from app.database.memory import (
    BudgetRecord,
    CostCenterRecord,
    DepartmentRecord,
    EmployeeRecord,
    SupplierContactRecord,
    SupplierProductRecord,
    SupplierRecord,
)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def infer_resource_type(requirement: str) -> ResourceType:
    text = _norm(requirement)
    # Artifacts / deliverables first — not directory people or suppliers
    if any(
        k in text
        for k in (
            "invoice",
            "quote",
            "purchase order",
            "draft po",
            "approved po",
            "submitted po",
            "po details",
            "po draft",
            "manifest",
            "delivery note",
            "receipt",
            "packing list",
            "rfq pack",
            "memo document",
            "memo template",
            "rfq template",
            "template",
        )
    ) and not any(
        k in text
        for k in ("approver", "approval authority", "authority", "contact", "manager approval")
    ):
        return ResourceType.UNKNOWN
    # Catalogs / software — bind to integrations (before "supplier" keyword)
    if any(
        k in text
        for k in (
            "approved supplier list",
            "supplier list",
            "vendor list",
            "supplier directory",
            "vendor directory",
            "internal contact directory",
            "contact directory",
            "employee directory",
            "company directory",
            "word processing",
            "spreadsheet",
            "calendar",
            "software",
            "document store",
            "memo template",
            "rfq pack",
        )
    ):
        return ResourceType.INTEGRATION
    if any(
        k in text
        for k in (
            "approval authority",
            "approver",
            "spending authority",
            "designated authority",
            "final po",
            "po approval",
            "final approval",
        )
    ):
        return ResourceType.APPROVAL_AUTHORITY
    if any(k in text for k in ("'s attention", "'s approval", "explicit approval", "manager approval")):
        return ResourceType.APPROVAL_AUTHORITY
    if any(k in text for k in ("manager", "mgr")):
        return ResourceType.MANAGER
    if any(k in text for k in ("supplier contact", "vendor contact", "vendor contact information")):
        return ResourceType.SUPPLIER_CONTACT
    if text.startswith("contact ") or text.endswith(" contact") or text == "contact":
        return ResourceType.SUPPLIER_CONTACT
    if any(k in text for k in ("supplier", "vendor")) and "list" not in text and "directory" not in text:
        return ResourceType.SUPPLIER
    if any(k in text for k in ("product", "sku", "item")):
        return ResourceType.PRODUCT
    if "budget" in text and "system" not in text:
        return ResourceType.BUDGET
    if any(k in text for k in ("cost center", "cost_center", "costcenter")) or text.startswith(
        "cc-"
    ):
        return ResourceType.COST_CENTER
    if any(k in text for k in ("department", "dept", "team")):
        return ResourceType.DEPARTMENT
    if any(
        k in text
        for k in (
            "integration",
            "email system",
            "email",
            "purchasing",
            "erp",
            "system",
            "form",
            "template",
            "tool",
            "document management",
            "procurement system",
            "budget management",
            "directory",
            "list",
            "software",
        )
    ):
        return ResourceType.INTEGRATION
    if any(
        k in text
        for k in (
            "employee",
            "requester",
            "buyer",
            "owner",
            "analyst",
            "person",
            "user",
            "attention",
            "specialist",
        )
    ):
        return ResourceType.EMPLOYEE
    return ResourceType.UNKNOWN


@dataclass
class OrgCatalog:
    organization_id: UUID
    employees: list[EmployeeRecord] = field(default_factory=list)
    departments: list[DepartmentRecord] = field(default_factory=list)
    suppliers: list[SupplierRecord] = field(default_factory=list)
    contacts: list[SupplierContactRecord] = field(default_factory=list)
    products: list[SupplierProductRecord] = field(default_factory=list)
    budgets: list[BudgetRecord] = field(default_factory=list)
    cost_centers: list[CostCenterRecord] = field(default_factory=list)
    manager_links: list[Any] = field(default_factory=list)

    def assert_tenant(self, resource_org_id: UUID) -> None:
        if resource_org_id != self.organization_id:
            raise ValueError("cross-organization resource lookup denied")


@dataclass
class MatchOutcome:
    assigned: ResourceCandidate | None = None
    candidates: list[ResourceCandidate] = field(default_factory=list)
    conflict: ResourceConflict | None = None
    unresolved: UnresolvedResource | None = None
    used_org_rule: bool = False


class DeterministicResourceMatcher:
    """Backend queries only — never invents contacts/suppliers/employees."""

    def __init__(self, catalog: OrgCatalog) -> None:
        self.catalog = catalog

    def match(
        self,
        *,
        step_id: str,
        requirement: str,
        preferred_department_id: UUID | None = None,
        employee_context_id: UUID | None = None,
        min_approval_amount: float | None = None,
        context_text: str | None = None,
        exclude_resource_ids: set[str] | None = None,
    ) -> MatchOutcome:
        rtype = infer_resource_type(requirement)
        text = _norm(requirement)
        ctx = _norm(context_text or "")
        exclude = exclude_resource_ids or set()

        if rtype in {
            ResourceType.EMPLOYEE,
            ResourceType.MANAGER,
            ResourceType.APPROVAL_AUTHORITY,
        }:
            return self._match_people(
                step_id=step_id,
                requirement=requirement,
                text=text,
                rtype=rtype,
                preferred_department_id=preferred_department_id,
                employee_context_id=employee_context_id,
                min_approval_amount=min_approval_amount,
            )
        if rtype == ResourceType.DEPARTMENT:
            return self._match_departments(step_id, requirement, text)
        if rtype == ResourceType.SUPPLIER:
            return self._match_suppliers(step_id, requirement, text)
        if rtype == ResourceType.SUPPLIER_CONTACT:
            return self._match_contacts(
                step_id, requirement, text, context_text=ctx, exclude_resource_ids=exclude
            )
        if rtype == ResourceType.PRODUCT:
            return self._match_products(step_id, requirement, text)
        if rtype == ResourceType.BUDGET:
            return self._match_budgets(
                step_id, requirement, text, preferred_department_id=preferred_department_id
            )
        if rtype == ResourceType.COST_CENTER:
            return self._match_cost_centers(step_id, requirement, text)
        if rtype == ResourceType.INTEGRATION:
            return self._match_integration(step_id, requirement, text)
        # Unknown artifacts — try integration mapping for software-ish wording
        if any(k in text for k in ("template", "software", "system", "tool", "form")):
            return self._match_integration(step_id, requirement, text)
        if rtype == ResourceType.UNKNOWN:
            # Try exact lookups across catalogs before giving up
            for attempt in (
                self._match_people(
                    step_id=step_id,
                    requirement=requirement,
                    text=text,
                    rtype=ResourceType.EMPLOYEE,
                    preferred_department_id=preferred_department_id,
                    employee_context_id=employee_context_id,
                    min_approval_amount=min_approval_amount,
                ),
                self._match_departments(step_id, requirement, text),
                self._match_suppliers(step_id, requirement, text),
                self._match_products(step_id, requirement, text),
                self._match_cost_centers(step_id, requirement, text),
                self._match_budgets(
                    step_id,
                    requirement,
                    text,
                    preferred_department_id=preferred_department_id,
                ),
                self._match_contacts(
                    step_id, requirement, text, context_text=ctx, exclude_resource_ids=exclude
                ),
            ):
                if (
                    attempt.assigned is not None
                    or attempt.candidates
                    or attempt.conflict is not None
                ):
                    return attempt
            return MatchOutcome(
                unresolved=UnresolvedResource(
                    id=f"unres_{step_id}_{_slug(requirement)}",
                    step_id=step_id,
                    requirement=requirement,
                    resource_type=ResourceType.UNKNOWN,
                    question=f"Which resource should satisfy '{requirement}'?",
                    blocking=False,
                )
            )
        return MatchOutcome(
            unresolved=UnresolvedResource(
                id=f"unres_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                resource_type=rtype,
                question=f"Which resource should satisfy '{requirement}'?",
            )
        )

    # ------------------------------------------------------------------
    # People
    # ------------------------------------------------------------------

    def _match_people(
        self,
        *,
        step_id: str,
        requirement: str,
        text: str,
        rtype: ResourceType,
        preferred_department_id: UUID | None,
        employee_context_id: UUID | None,
        min_approval_amount: float | None,
    ) -> MatchOutcome:
        # Org rule: manager of a specific employee via hierarchy
        if rtype == ResourceType.MANAGER and employee_context_id is not None:
            managers = self._managers_for(employee_context_id)
            active = [m for m in managers if m.status == "active"]
            if len(active) == 1:
                cand = self._employee_candidate(
                    active[0],
                    reason="Deterministic manager hierarchy link",
                    data_source=DataSource.MANAGER_LINK,
                    confidence=0.98,
                    resource_type=ResourceType.MANAGER,
                )
                return MatchOutcome(assigned=cand, used_org_rule=True)
            if len(active) > 1:
                cands = [
                    self._employee_candidate(
                        m,
                        reason="Multiple active managers in hierarchy",
                        data_source=DataSource.MANAGER_LINK,
                        confidence=0.7,
                        resource_type=ResourceType.MANAGER,
                        conflict=ConflictStatus.AMBIGUOUS,
                    )
                    for m in active
                ]
                return self._ambiguous(step_id, requirement, cands)

        # Org rule: department's designated manager
        if rtype == ResourceType.MANAGER and preferred_department_id is not None:
            dept = next(
                (d for d in self.catalog.departments if d.id == preferred_department_id),
                None,
            )
            if dept and dept.manager_employee_id:
                mgr = next(
                    (e for e in self.catalog.employees if e.id == dept.manager_employee_id),
                    None,
                )
                if mgr and mgr.status == "active":
                    cand = self._employee_candidate(
                        mgr,
                        reason=f"Department rule: manager of {dept.name}",
                        data_source=DataSource.DEPARTMENT_RULE,
                        confidence=0.97,
                        resource_type=ResourceType.MANAGER,
                    )
                    return MatchOutcome(assigned=cand, used_org_rule=True)
                if mgr and mgr.status != "active":
                    return MatchOutcome(
                        conflict=ResourceConflict(
                            id=f"conf_{step_id}_{_slug(requirement)}",
                            step_id=step_id,
                            requirement=requirement,
                            conflict_status=ConflictStatus.INACTIVE,
                            message=f"Department manager {mgr.full_name} is inactive and cannot be assigned",
                            candidates=[
                                self._employee_candidate(
                                    mgr,
                                    reason="Inactive department manager",
                                    data_source=DataSource.DEPARTMENT_RULE,
                                    confidence=0.9,
                                    resource_type=ResourceType.MANAGER,
                                    conflict=ConflictStatus.INACTIVE,
                                    active=False,
                                )
                            ],
                        ),
                        unresolved=UnresolvedResource(
                            id=f"unres_{step_id}_{_slug(requirement)}",
                            step_id=step_id,
                            requirement=requirement,
                            resource_type=ResourceType.MANAGER,
                            question=f"Department manager for '{dept.name}' is inactive. Who should approve?",
                        ),
                    )

        # Exact email / code / name
        active_employees = [e for e in self.catalog.employees if e.status == "active"]
        inactive_hits = [
            e
            for e in self.catalog.employees
            if e.status != "active"
            and (
                _norm(e.email) == text
                or (e.employee_code and _norm(e.employee_code) == text)
                or _norm(e.full_name) == text
            )
        ]
        if inactive_hits:
            cands = [
                self._employee_candidate(
                    e,
                    reason="Matched inactive employee — assignment blocked",
                    data_source=DataSource.DIRECTORY_QUERY,
                    confidence=0.95,
                    resource_type=rtype if rtype != ResourceType.UNKNOWN else ResourceType.EMPLOYEE,
                    conflict=ConflictStatus.INACTIVE,
                    active=False,
                    auth=AuthorizationStatus.UNAUTHORIZED,
                )
                for e in inactive_hits
            ]
            return MatchOutcome(
                conflict=ResourceConflict(
                    id=f"conf_{step_id}_{_slug(requirement)}",
                    step_id=step_id,
                    requirement=requirement,
                    conflict_status=ConflictStatus.INACTIVE,
                    message="Matched employee is inactive and cannot be assigned",
                    candidates=cands,
                ),
                unresolved=UnresolvedResource(
                    id=f"unres_{step_id}_{_slug(requirement)}",
                    step_id=step_id,
                    requirement=requirement,
                    resource_type=ResourceType.EMPLOYEE,
                    question=f"'{requirement}' matches an inactive employee. Choose an active resource.",
                    candidates=cands,
                ),
            )

        exact: list[EmployeeRecord] = []
        for e in active_employees:
            if (
                _norm(e.email) == text
                or (e.employee_code and _norm(e.employee_code) == text)
                or _norm(e.full_name) == text
            ):
                exact.append(e)

        # Name contained in requirement ("Jordan Lee's attention" → Jordan Lee)
        if not exact:
            contained = [
                e
                for e in active_employees
                if len(_norm(e.full_name)) >= 3 and _norm(e.full_name) in text
            ]
            # Prefer longest name match to avoid first-name collisions
            if contained:
                contained.sort(key=lambda e: len(e.full_name), reverse=True)
                best_len = len(_norm(contained[0].full_name))
                contained = [e for e in contained if len(_norm(e.full_name)) == best_len]
                exact = contained

        # Role-code exact for role-like requirements
        if not exact and rtype in {
            ResourceType.EMPLOYEE,
            ResourceType.MANAGER,
            ResourceType.APPROVAL_AUTHORITY,
            ResourceType.UNKNOWN,
        }:
            role_key = text.replace(" ", "_")
            for e in active_employees:
                if e.role_code and _norm(e.role_code) in {text, role_key}:
                    exact.append(e)
            if rtype == ResourceType.MANAGER:
                managers = [e for e in active_employees if e.is_manager]
                if preferred_department_id:
                    managers = [
                        e for e in managers if e.department_id == preferred_department_id
                    ]
                if len(managers) == 1 and ("manager" in text or text in {"approver", "mgr"}):
                    cand = self._employee_candidate(
                        managers[0],
                        reason="Single active manager matches org rule",
                        data_source=DataSource.ROLE_RULE,
                        confidence=0.9,
                        resource_type=ResourceType.MANAGER,
                    )
                    return MatchOutcome(assigned=cand, used_org_rule=True)
                if len(managers) > 1 and text in {"manager", "approver", "mgr"}:
                    cands = [
                        self._employee_candidate(
                            m,
                            reason="Multiple managers — clarification required",
                            data_source=DataSource.DIRECTORY_QUERY,
                            confidence=0.55,
                            resource_type=ResourceType.MANAGER,
                            conflict=ConflictStatus.AMBIGUOUS,
                        )
                        for m in managers
                    ]
                    return self._ambiguous(step_id, requirement, cands)

        if rtype == ResourceType.APPROVAL_AUTHORITY and not exact:
            # Prefer managers for generic "approver" / Final PO — pick highest authority so work proceeds
            if any(
                k in text
                for k in ("approver", "approval", "authority", "final po", "po approval")
            ):
                role_pref = [
                    e
                    for e in active_employees
                    if e.is_manager
                    and (e.role_code or "").lower() in {"manager", "owner", "finance"}
                ]
                if preferred_department_id:
                    dept_pref = [e for e in role_pref if e.department_id == preferred_department_id]
                    if dept_pref:
                        role_pref = dept_pref
                if len(role_pref) == 1:
                    cand = self._employee_candidate(
                        role_pref[0],
                        reason="Deterministic approver match from manager role",
                        data_source=DataSource.ROLE_RULE,
                        confidence=0.9,
                        resource_type=ResourceType.APPROVAL_AUTHORITY,
                    )
                    return MatchOutcome(assigned=cand, used_org_rule=True)
                if len(role_pref) > 1:
                    ranked = sorted(
                        role_pref,
                        key=lambda e: (e.approval_authority_limit or 0, e.is_manager),
                        reverse=True,
                    )
                    primary = ranked[0]
                    cands = [
                        self._employee_candidate(
                            e,
                            reason="Approver candidate (manager)",
                            data_source=DataSource.ROLE_RULE,
                            confidence=0.9 if e.id == primary.id else 0.65,
                            resource_type=ResourceType.APPROVAL_AUTHORITY,
                            conflict=ConflictStatus.NONE
                            if e.id == primary.id
                            else ConflictStatus.AMBIGUOUS,
                        )
                        for e in ranked[:8]
                    ]
                    return MatchOutcome(assigned=cands[0], candidates=cands, used_org_rule=True)
            authorities = [
                e
                for e in active_employees
                if e.approval_authority_limit is not None
                and (
                    min_approval_amount is None
                    or e.approval_authority_limit >= min_approval_amount
                )
            ]
            if preferred_department_id:
                dept_auth = [e for e in authorities if e.department_id == preferred_department_id]
                if dept_auth:
                    authorities = dept_auth
            if len(authorities) == 1:
                cand = self._employee_candidate(
                    authorities[0],
                    reason="Deterministic approval authority match",
                    data_source=DataSource.ROLE_RULE,
                    confidence=0.92,
                    resource_type=ResourceType.APPROVAL_AUTHORITY,
                )
                return MatchOutcome(assigned=cand, used_org_rule=True)
            if len(authorities) > 1:
                ranked = sorted(
                    authorities,
                    key=lambda e: (e.approval_authority_limit or 0, e.is_manager),
                    reverse=True,
                )
                primary = ranked[0]
                cands = [
                    self._employee_candidate(
                        e,
                        reason="Highest approval authority among directory matches",
                        data_source=DataSource.DIRECTORY_QUERY,
                        confidence=0.88 if e.id == primary.id else 0.6,
                        resource_type=ResourceType.APPROVAL_AUTHORITY,
                        conflict=ConflictStatus.NONE
                        if e.id == primary.id
                        else ConflictStatus.AMBIGUOUS,
                    )
                    for e in ranked[:8]
                ]
                return MatchOutcome(assigned=cands[0], candidates=cands)

        if len(exact) == 1:
            e = exact[0]
            if rtype == ResourceType.MANAGER and not e.is_manager:
                return MatchOutcome(
                    conflict=ResourceConflict(
                        id=f"conf_{step_id}_{_slug(requirement)}",
                        step_id=step_id,
                        requirement=requirement,
                        conflict_status=ConflictStatus.RULE_VIOLATION,
                        message=f"{e.full_name} is not a manager; cannot override authorization rules",
                        candidates=[
                            self._employee_candidate(
                                e,
                                reason="Matched but not authorized as manager",
                                data_source=DataSource.DIRECTORY_QUERY,
                                confidence=0.85,
                                resource_type=ResourceType.EMPLOYEE,
                                conflict=ConflictStatus.RULE_VIOLATION,
                                auth=AuthorizationStatus.UNAUTHORIZED,
                            )
                        ],
                    )
                )
            cand = self._employee_candidate(
                e,
                reason="Exact directory match",
                data_source=DataSource.DIRECTORY_QUERY,
                confidence=0.99,
                resource_type=rtype if rtype != ResourceType.UNKNOWN else ResourceType.EMPLOYEE,
            )
            return MatchOutcome(assigned=cand)

        if len(exact) > 1:
            cands = [
                self._employee_candidate(
                    e,
                    reason="Ambiguous exact name match",
                    data_source=DataSource.DIRECTORY_QUERY,
                    confidence=0.7,
                    resource_type=ResourceType.EMPLOYEE,
                    conflict=ConflictStatus.AMBIGUOUS,
                )
                for e in exact
            ]
            return self._ambiguous(step_id, requirement, cands)

        # Partial name matches → candidates only (never invent)
        partial = [
            e
            for e in active_employees
            if text and text in _norm(e.full_name) and len(text) >= 3
        ]
        if partial:
            cands = [
                self._employee_candidate(
                    e,
                    reason="Partial name match — clarification required",
                    data_source=DataSource.DIRECTORY_QUERY,
                    confidence=0.45,
                    resource_type=ResourceType.EMPLOYEE,
                    conflict=ConflictStatus.AMBIGUOUS,
                )
                for e in partial[:8]
            ]
            return self._ambiguous(step_id, requirement, cands)

        return MatchOutcome(
            unresolved=UnresolvedResource(
                id=f"unres_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                resource_type=rtype if rtype != ResourceType.UNKNOWN else ResourceType.EMPLOYEE,
                question=f"No active directory match for '{requirement}'. Who should be assigned?",
            )
        )

    def _managers_for(self, employee_id: UUID) -> list[EmployeeRecord]:
        manager_ids = {
            link.manager_employee_id
            for link in self.catalog.manager_links
            if link.employee_id == employee_id and link.status == "active"
        }
        return [e for e in self.catalog.employees if e.id in manager_ids]

    def _employee_candidate(
        self,
        employee: EmployeeRecord,
        *,
        reason: str,
        data_source: DataSource,
        confidence: float,
        resource_type: ResourceType,
        conflict: ConflictStatus = ConflictStatus.NONE,
        active: bool | None = None,
        auth: AuthorizationStatus | None = None,
    ) -> ResourceCandidate:
        self.catalog.assert_tenant(employee.organization_id)
        is_active = employee.status == "active" if active is None else active
        return ResourceCandidate(
            resource_id=str(employee.id),
            resource_type=resource_type,
            display_name=employee.full_name,
            reason=reason,
            data_source=data_source,
            confidence=confidence,
            authorization_status=auth
            or (
                AuthorizationStatus.AUTHORIZED
                if is_active
                else AuthorizationStatus.UNAUTHORIZED
            ),
            active_status=is_active,
            conflict_status=conflict,
            metadata={
                "email": employee.email,
                "role_code": employee.role_code,
                "is_manager": employee.is_manager,
                "department_id": str(employee.department_id) if employee.department_id else None,
                "approval_authority_limit": employee.approval_authority_limit,
            },
        )

    # ------------------------------------------------------------------
    # Departments / suppliers / etc.
    # ------------------------------------------------------------------

    def _match_departments(self, step_id: str, requirement: str, text: str) -> MatchOutcome:
        active = [d for d in self.catalog.departments if d.status == "active"]
        exact = [
            d
            for d in active
            if _norm(d.name) == text or (d.code and _norm(d.code) == text)
        ]
        if len(exact) == 1:
            d = exact[0]
            return MatchOutcome(
                assigned=ResourceCandidate(
                    resource_id=str(d.id),
                    resource_type=ResourceType.DEPARTMENT,
                    display_name=d.name,
                    reason="Exact department match",
                    data_source=DataSource.DIRECTORY_QUERY,
                    confidence=0.99,
                    authorization_status=AuthorizationStatus.AUTHORIZED,
                    active_status=True,
                )
            )
        if len(exact) > 1:
            cands = [
                ResourceCandidate(
                    resource_id=str(d.id),
                    resource_type=ResourceType.DEPARTMENT,
                    display_name=d.name,
                    reason="Ambiguous department name",
                    data_source=DataSource.DIRECTORY_QUERY,
                    confidence=0.7,
                    conflict_status=ConflictStatus.AMBIGUOUS,
                )
                for d in exact
            ]
            return self._ambiguous(step_id, requirement, cands)
        return MatchOutcome(
            unresolved=UnresolvedResource(
                id=f"unres_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                resource_type=ResourceType.DEPARTMENT,
                question=f"Which department satisfies '{requirement}'?",
            )
        )

    def _match_suppliers(self, step_id: str, requirement: str, text: str) -> MatchOutcome:
        exact = [
            s
            for s in self.catalog.suppliers
            if _norm(s.name) == text or (s.code and _norm(s.code) == text)
        ]
        if not exact:
            # Name contained in requirement ("Northwind Supplies quote")
            contained = [
                s
                for s in self.catalog.suppliers
                if len(_norm(s.name)) >= 3 and _norm(s.name) in text
            ]
            if contained:
                contained.sort(key=lambda s: len(s.name), reverse=True)
                best_len = len(_norm(contained[0].name))
                exact = [s for s in contained if len(_norm(s.name)) == best_len]
            else:
                partial = [
                    s
                    for s in self.catalog.suppliers
                    if text and text in _norm(s.name) and len(text) >= 3
                ]
                if partial:
                    cands = [self._supplier_candidate(s, ambiguous=True) for s in partial[:8]]
                    return self._ambiguous(step_id, requirement, cands)
                return MatchOutcome(
                    unresolved=UnresolvedResource(
                        id=f"unres_{step_id}_{_slug(requirement)}",
                        step_id=step_id,
                        requirement=requirement,
                        resource_type=ResourceType.SUPPLIER,
                        question=f"No supplier match for '{requirement}'. Do not invent suppliers.",
                    )
                )

        approved_active = [
            s for s in exact if s.status == "active" and s.approval_status == "approved"
        ]
        if len(approved_active) == 1:
            s = approved_active[0]
            contacts = [
                c
                for c in self.catalog.contacts
                if c.supplier_id == s.id and c.status == "active"
            ]
            cand = self._supplier_candidate(s)
            if not contacts:
                return MatchOutcome(
                    assigned=None,
                    candidates=[cand],
                    conflict=ResourceConflict(
                        id=f"conf_{step_id}_{_slug(requirement)}",
                        step_id=step_id,
                        requirement=requirement,
                        conflict_status=ConflictStatus.MISSING_CONTACT,
                        message=f"Supplier {s.name} is approved but has no active contacts",
                        candidates=[cand],
                    ),
                    unresolved=UnresolvedResource(
                        id=f"unres_{step_id}_{_slug(requirement)}_contact",
                        step_id=step_id,
                        requirement=f"contact for {s.name}",
                        resource_type=ResourceType.SUPPLIER_CONTACT,
                        question=f"Supplier '{s.name}' has no active contacts. Add a contact before allocation.",
                        candidates=[cand],
                    ),
                )
            return MatchOutcome(assigned=cand)

        unapproved = [
            s for s in exact if s.approval_status != "approved" or s.status != "active"
        ]
        if unapproved and not approved_active:
            cands = [
                self._supplier_candidate(
                    s,
                    conflict=ConflictStatus.UNAPPROVED
                    if s.approval_status != "approved"
                    else ConflictStatus.INACTIVE,
                    auth=AuthorizationStatus.UNAUTHORIZED,
                )
                for s in unapproved
            ]
            return MatchOutcome(
                conflict=ResourceConflict(
                    id=f"conf_{step_id}_{_slug(requirement)}",
                    step_id=step_id,
                    requirement=requirement,
                    conflict_status=ConflictStatus.UNAPPROVED,
                    message="Supplier is not approved/active — cannot assign",
                    candidates=cands,
                ),
                unresolved=UnresolvedResource(
                    id=f"unres_{step_id}_{_slug(requirement)}",
                    step_id=step_id,
                    requirement=requirement,
                    resource_type=ResourceType.SUPPLIER,
                    question=f"Supplier '{requirement}' is not approved. Choose an approved supplier.",
                    candidates=cands,
                ),
            )

        if len(approved_active) > 1:
            return self._ambiguous(
                step_id, requirement, [self._supplier_candidate(s, ambiguous=True) for s in approved_active]
            )
        return MatchOutcome(
            unresolved=UnresolvedResource(
                id=f"unres_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                resource_type=ResourceType.SUPPLIER,
                question=f"Unable to allocate supplier for '{requirement}'.",
            )
        )

    def _supplier_candidate(
        self,
        supplier: SupplierRecord,
        *,
        ambiguous: bool = False,
        conflict: ConflictStatus | None = None,
        auth: AuthorizationStatus | None = None,
    ) -> ResourceCandidate:
        self.catalog.assert_tenant(supplier.organization_id)
        approved = supplier.approval_status == "approved" and supplier.status == "active"
        status = conflict or (
            ConflictStatus.AMBIGUOUS
            if ambiguous
            else ConflictStatus.NONE
            if approved
            else ConflictStatus.UNAPPROVED
        )
        return ResourceCandidate(
            resource_id=str(supplier.id),
            resource_type=ResourceType.SUPPLIER,
            display_name=supplier.name,
            reason="Supplier directory query",
            data_source=DataSource.SUPPLIER_QUERY,
            confidence=0.5 if ambiguous else 0.95,
            authorization_status=auth
            or (
                AuthorizationStatus.AUTHORIZED
                if approved
                else AuthorizationStatus.UNAUTHORIZED
            ),
            active_status=supplier.status == "active",
            conflict_status=status,
            metadata={
                "approval_status": supplier.approval_status,
                "code": supplier.code,
            },
        )

    def _match_contacts(
        self,
        step_id: str,
        requirement: str,
        text: str,
        *,
        context_text: str = "",
        exclude_resource_ids: set[str] | None = None,
    ) -> MatchOutcome:
        active = [c for c in self.catalog.contacts if c.status == "active"]
        exclude = exclude_resource_ids or set()
        search = f"{text} {context_text}".strip()
        exact = [
            c
            for c in active
            if _norm(c.full_name) == text or (c.email and _norm(c.email) == text)
        ]
        if len(exact) == 1:
            c = exact[0]
            return MatchOutcome(
                assigned=ResourceCandidate(
                    resource_id=str(c.id),
                    resource_type=ResourceType.SUPPLIER_CONTACT,
                    display_name=c.full_name,
                    reason="Exact supplier contact match",
                    data_source=DataSource.SUPPLIER_QUERY,
                    confidence=0.98,
                    authorization_status=AuthorizationStatus.AUTHORIZED,
                    active_status=True,
                    metadata={"supplier_id": str(c.supplier_id), "email": c.email},
                )
            )
        if len(exact) > 1:
            cands = [
                ResourceCandidate(
                    resource_id=str(c.id),
                    resource_type=ResourceType.SUPPLIER_CONTACT,
                    display_name=c.full_name,
                    reason="Ambiguous contact match",
                    data_source=DataSource.SUPPLIER_QUERY,
                    confidence=0.65,
                    conflict_status=ConflictStatus.AMBIGUOUS,
                )
                for c in exact
            ]
            return self._ambiguous(step_id, requirement, cands)

        # Prefer contacts whose supplier name / email appears in requirement or plan context
        named = []
        for c in active:
            supplier = next((s for s in self.catalog.suppliers if s.id == c.supplier_id), None)
            sname = _norm(supplier.name) if supplier else ""
            if sname and len(sname) >= 3 and sname in search:
                named.append(c)
            elif c.email and _norm(c.email) in search:
                named.append(c)
            elif c.email and "gmail.com" in search and "gmail.com" in (c.email or "").lower():
                named.append(c)
        named = [c for c in named if str(c.id) not in exclude] or named
        if len(named) >= 1 and any(
            k in search for k in ("kanaka", "gmail.com", "kadavishka")
        ):
            # Prefer Kanaka / gmail when the process explicitly mentions them
            preferred = sorted(
                named,
                key=lambda c: (
                    "kanaka" in _norm(
                        next((s.name for s in self.catalog.suppliers if s.id == c.supplier_id), "")
                    ),
                    "gmail.com" in (c.email or "").lower(),
                ),
                reverse=True,
            )
            c = preferred[0]
            return MatchOutcome(
                assigned=ResourceCandidate(
                    resource_id=str(c.id),
                    resource_type=ResourceType.SUPPLIER_CONTACT,
                    display_name=c.full_name,
                    reason="Contact matched via Kanaka/email in plan context",
                    data_source=DataSource.SUPPLIER_QUERY,
                    confidence=0.95,
                    authorization_status=AuthorizationStatus.AUTHORIZED,
                    active_status=True,
                    metadata={"supplier_id": str(c.supplier_id), "email": c.email},
                )
            )
        if len(named) == 1:
            c = named[0]
            return MatchOutcome(
                assigned=ResourceCandidate(
                    resource_id=str(c.id),
                    resource_type=ResourceType.SUPPLIER_CONTACT,
                    display_name=c.full_name,
                    reason="Contact matched via supplier name/email in requirement",
                    data_source=DataSource.SUPPLIER_QUERY,
                    confidence=0.95,
                    authorization_status=AuthorizationStatus.AUTHORIZED,
                    active_status=True,
                    metadata={"supplier_id": str(c.supplier_id), "email": c.email},
                )
            )
        if len(named) > 1:
            approved_ids = {
                s.id
                for s in self.catalog.suppliers
                if s.status == "active" and s.approval_status == "approved"
            }
            approved_named = [c for c in named if c.supplier_id in approved_ids] or named
            c = approved_named[0]
            return MatchOutcome(
                assigned=ResourceCandidate(
                    resource_id=str(c.id),
                    resource_type=ResourceType.SUPPLIER_CONTACT,
                    display_name=c.full_name,
                    reason="Preferred named supplier contact from requirement",
                    data_source=DataSource.SUPPLIER_QUERY,
                    confidence=0.92,
                    authorization_status=AuthorizationStatus.AUTHORIZED,
                    active_status=True,
                    metadata={"supplier_id": str(c.supplier_id), "email": c.email},
                )
            )

        # Generic vendor/supplier contact request → use contacts of approved suppliers
        if any(k in text for k in ("vendor contact", "supplier contact", "contact information")):
            approved_ids = {
                s.id
                for s in self.catalog.suppliers
                if s.status == "active" and s.approval_status == "approved"
            }
            pool = [c for c in active if c.supplier_id in approved_ids]
            # Prefer Kanaka when plan context mentions it; otherwise diversify away from
            # already-assigned contacts for dual-quote flows.
            if "kanaka" in search or "kadavishka" in search:
                kanaka_pool = [
                    c
                    for c in pool
                    if "kanaka"
                    in _norm(
                        next((s.name for s in self.catalog.suppliers if s.id == c.supplier_id), "")
                    )
                ]
                if kanaka_pool:
                    pool = kanaka_pool + [c for c in pool if c not in kanaka_pool]
            unused = [c for c in pool if str(c.id) not in exclude]
            if unused:
                pool = unused
            if len(pool) == 1:
                c = pool[0]
                return MatchOutcome(
                    assigned=ResourceCandidate(
                        resource_id=str(c.id),
                        resource_type=ResourceType.SUPPLIER_CONTACT,
                        display_name=c.full_name,
                        reason="Only active contact on approved suppliers",
                        data_source=DataSource.SUPPLIER_QUERY,
                        confidence=0.9,
                        authorization_status=AuthorizationStatus.AUTHORIZED,
                        active_status=True,
                        metadata={"supplier_id": str(c.supplier_id), "email": c.email},
                    )
                )
            if len(pool) > 1:
                primary = pool[0]
                cands = [
                    ResourceCandidate(
                        resource_id=str(c.id),
                        resource_type=ResourceType.SUPPLIER_CONTACT,
                        display_name=c.full_name,
                        reason="Approved-supplier contact candidate",
                        data_source=DataSource.SUPPLIER_QUERY,
                        confidence=0.88 if c.id == primary.id else 0.7,
                        authorization_status=AuthorizationStatus.AUTHORIZED,
                        active_status=True,
                        conflict_status=ConflictStatus.NONE
                        if c.id == primary.id
                        else ConflictStatus.AMBIGUOUS,
                        metadata={"supplier_id": str(c.supplier_id), "email": c.email},
                    )
                    for c in pool[:12]
                ]
                return MatchOutcome(assigned=cands[0], candidates=cands)

        return MatchOutcome(
            unresolved=UnresolvedResource(
                id=f"unres_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                resource_type=ResourceType.SUPPLIER_CONTACT,
                question=f"No supplier contact found for '{requirement}'. Do not invent contacts.",
            )
        )

    def _match_products(self, step_id: str, requirement: str, text: str) -> MatchOutcome:
        active = [p for p in self.catalog.products if p.status == "active"]
        exact = [
            p
            for p in active
            if _norm(p.name) == text or (p.sku and _norm(p.sku) == text)
        ]
        if len(exact) == 1:
            p = exact[0]
            return MatchOutcome(
                assigned=ResourceCandidate(
                    resource_id=str(p.id),
                    resource_type=ResourceType.PRODUCT,
                    display_name=p.name,
                    reason="Exact product match",
                    data_source=DataSource.SUPPLIER_QUERY,
                    confidence=0.97,
                    authorization_status=AuthorizationStatus.AUTHORIZED,
                    active_status=True,
                    metadata={"supplier_id": str(p.supplier_id), "sku": p.sku},
                )
            )
        if len(exact) > 1:
            return self._ambiguous(
                step_id,
                requirement,
                [
                    ResourceCandidate(
                        resource_id=str(p.id),
                        resource_type=ResourceType.PRODUCT,
                        display_name=p.name,
                        reason="Ambiguous product match",
                        data_source=DataSource.SUPPLIER_QUERY,
                        confidence=0.6,
                        conflict_status=ConflictStatus.AMBIGUOUS,
                    )
                    for p in exact
                ],
            )
        return MatchOutcome(
            unresolved=UnresolvedResource(
                id=f"unres_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                resource_type=ResourceType.PRODUCT,
                question=f"No product match for '{requirement}'.",
            )
        )

    def _match_budgets(
        self,
        step_id: str,
        requirement: str,
        text: str,
        *,
        preferred_department_id: UUID | None,
    ) -> MatchOutcome:
        active = [b for b in self.catalog.budgets if b.status == "active"]
        exact = [b for b in active if _norm(b.name) == text]
        if not exact and preferred_department_id is not None:
            owned = [b for b in active if b.department_id == preferred_department_id]
            if len(owned) == 1:
                b = owned[0]
                return MatchOutcome(
                    assigned=ResourceCandidate(
                        resource_id=str(b.id),
                        resource_type=ResourceType.BUDGET,
                        display_name=b.name,
                        reason="Budget ownership by department",
                        data_source=DataSource.BUDGET_QUERY,
                        confidence=0.94,
                        authorization_status=AuthorizationStatus.AUTHORIZED,
                        active_status=True,
                        metadata={
                            "department_id": str(b.department_id) if b.department_id else None,
                            "cost_center_id": str(b.cost_center_id) if b.cost_center_id else None,
                            "amount_total": b.amount_total,
                        },
                    ),
                    used_org_rule=True,
                )
            if len(owned) > 1:
                return self._ambiguous(
                    step_id,
                    requirement,
                    [
                        ResourceCandidate(
                            resource_id=str(b.id),
                            resource_type=ResourceType.BUDGET,
                            display_name=b.name,
                            reason="Multiple budgets for department",
                            data_source=DataSource.BUDGET_QUERY,
                            confidence=0.6,
                            conflict_status=ConflictStatus.AMBIGUOUS,
                        )
                        for b in owned
                    ],
                )
        if len(exact) == 1:
            b = exact[0]
            if (
                preferred_department_id is not None
                and b.department_id is not None
                and b.department_id != preferred_department_id
            ):
                return MatchOutcome(
                    conflict=ResourceConflict(
                        id=f"conf_{step_id}_{_slug(requirement)}",
                        step_id=step_id,
                        requirement=requirement,
                        conflict_status=ConflictStatus.BUDGET_MISMATCH,
                        message="Budget is owned by a different department",
                        candidates=[
                            ResourceCandidate(
                                resource_id=str(b.id),
                                resource_type=ResourceType.BUDGET,
                                display_name=b.name,
                                reason="Budget ownership mismatch",
                                data_source=DataSource.BUDGET_QUERY,
                                confidence=0.9,
                                authorization_status=AuthorizationStatus.UNAUTHORIZED,
                                active_status=True,
                                conflict_status=ConflictStatus.BUDGET_MISMATCH,
                            )
                        ],
                    )
                )
            return MatchOutcome(
                assigned=ResourceCandidate(
                    resource_id=str(b.id),
                    resource_type=ResourceType.BUDGET,
                    display_name=b.name,
                    reason="Exact budget name match",
                    data_source=DataSource.BUDGET_QUERY,
                    confidence=0.96,
                    authorization_status=AuthorizationStatus.AUTHORIZED,
                    active_status=True,
                )
            )
        if len(exact) > 1:
            return self._ambiguous(
                step_id,
                requirement,
                [
                    ResourceCandidate(
                        resource_id=str(b.id),
                        resource_type=ResourceType.BUDGET,
                        display_name=b.name,
                        reason="Ambiguous budget name",
                        data_source=DataSource.BUDGET_QUERY,
                        confidence=0.65,
                        conflict_status=ConflictStatus.AMBIGUOUS,
                    )
                    for b in exact
                ],
            )
        return MatchOutcome(
            unresolved=UnresolvedResource(
                id=f"unres_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                resource_type=ResourceType.BUDGET,
                question=f"Which budget covers '{requirement}'?",
            )
        )

    def _match_cost_centers(self, step_id: str, requirement: str, text: str) -> MatchOutcome:
        active = [c for c in self.catalog.cost_centers if c.status == "active"]
        exact = [
            c
            for c in active
            if _norm(c.name) == text or _norm(c.code) == text
        ]
        if len(exact) == 1:
            c = exact[0]
            return MatchOutcome(
                assigned=ResourceCandidate(
                    resource_id=str(c.id),
                    resource_type=ResourceType.COST_CENTER,
                    display_name=c.name,
                    reason="Exact cost center match",
                    data_source=DataSource.BUDGET_QUERY,
                    confidence=0.97,
                    authorization_status=AuthorizationStatus.AUTHORIZED,
                    active_status=True,
                    metadata={"code": c.code},
                )
            )
        if len(exact) > 1:
            return self._ambiguous(
                step_id,
                requirement,
                [
                    ResourceCandidate(
                        resource_id=str(c.id),
                        resource_type=ResourceType.COST_CENTER,
                        display_name=c.name,
                        reason="Ambiguous cost center",
                        data_source=DataSource.BUDGET_QUERY,
                        confidence=0.6,
                        conflict_status=ConflictStatus.AMBIGUOUS,
                    )
                    for c in exact
                ],
            )
        return MatchOutcome(
            unresolved=UnresolvedResource(
                id=f"unres_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                resource_type=ResourceType.COST_CENTER,
                question=f"Which cost center satisfies '{requirement}'?",
            )
        )

    def _match_integration(self, step_id: str, requirement: str, text: str) -> MatchOutcome:
        """Map system/tool requirements to known integration capabilities (read-only)."""
        key = "generic"
        if "email" in text:
            key = "email"
        elif any(k in text for k in ("calendar", "meeting", "schedule")):
            key = "calendar"
        elif any(k in text for k in ("purchas", "procurement", "po ", "purchase order", "draft po")):
            key = "purchasing"
        elif any(k in text for k in ("supplier list", "vendor list", "approved supplier", "supplier directory")):
            key = "supplier_directory"
        elif any(k in text for k in ("contact directory", "employee directory", "company directory", "internal contact")):
            key = "directory"
        elif any(k in text for k in ("supplier", "vendor", "quotation", "rfq")):
            key = "supplier_channel"
        elif "budget" in text or "billing" in text:
            key = "billing"
        elif "notif" in text:
            key = "notification"
        elif any(k in text for k in ("word processing", "software", "document", "file", "form", "template", "memo")):
            key = "document_store"
        elif "directory" in text or "list" in text:
            key = "directory"

        return MatchOutcome(
            assigned=ResourceCandidate(
                resource_id=f"integration:{key}",
                resource_type=ResourceType.INTEGRATION,
                display_name=f"{key.replace('_', ' ').title()} capability",
                reason=f"Mapped system requirement '{requirement}' to org integration '{key}' (no side effects).",
                data_source=DataSource.INTEGRATION_CATALOG,
                confidence=0.8,
                authorization_status=AuthorizationStatus.NOT_APPLICABLE,
                active_status=True,
                metadata={"integration_key": key, "requirement": requirement},
            )
        )

    def _ambiguous(
        self, step_id: str, requirement: str, candidates: list[ResourceCandidate]
    ) -> MatchOutcome:
        return MatchOutcome(
            candidates=candidates,
            conflict=ResourceConflict(
                id=f"conf_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                conflict_status=ConflictStatus.AMBIGUOUS,
                message="Multiple resources match; clarification required unless an org rule applies",
                candidates=candidates,
            ),
            unresolved=UnresolvedResource(
                id=f"unres_{step_id}_{_slug(requirement)}",
                step_id=step_id,
                requirement=requirement,
                resource_type=candidates[0].resource_type if candidates else ResourceType.UNKNOWN,
                question=f"Multiple matches for '{requirement}'. Which resource should be used?",
                candidates=candidates,
            ),
        )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:40] or "req"
