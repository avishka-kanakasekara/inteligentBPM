"""Agent 2 — Resource and Company Context Allocation service."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.agents.allocation.integrations import list_integration_availability
from app.agents.allocation.matcher import DeterministicResourceMatcher, OrgCatalog
from app.agents.allocation.models import (
    AllocationAssistOutput,
    AuthorizationStatus,
    ClarificationChoice,
    ConflictStatus,
    DataSource,
    OrganizationProfileSnapshot,
    ResourceAllocationRequest,
    ResourceAllocationResult,
    ResourceAssignment,
    ResourceCandidate,
    ResourceType,
    UnresolvedResource,
)
from app.agents.discovery.models import ProcessPlan
from app.audit import AuditService
from app.contracts.common import utcnow
from app.database.memory import AllocationResultRecord, get_memory_store, new_id
from app.llm.client import FakeGeminiClient, GeminiClient, create_gemini_client
from app.llm.prompt_registry import PromptRegistry
from app.llm.structured import StructuredGenerationService
from app.llm.types import AgentExecutionContext, AgentKind
from app.repositories.memory_repos import (
    BudgetRepository,
    CostCenterRepository,
    DepartmentRepository,
    EmployeeManagerLinkRepository,
    EmployeeRepository,
    OrganizationRepository,
    ProcessRepository,
    SupplierContactRepository,
    SupplierProductRepository,
    SupplierRepository,
)
from app.security.errors import NotFoundError, ValidationAppError
import structlog

logger = structlog.get_logger()


class AllocationService:
    """
    Bind plan steps to company resources.

    Deterministic backend queries first. Gemini only for ambiguity / explanations.
    Never sends email, creates POs, approves spending, mutates org data, or invents resources.
    """

    def __init__(
        self,
        organization_id: UUID,
        *,
        client: GeminiClient | None = None,
        structured: StructuredGenerationService | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.store = get_memory_store()
        self.processes = ProcessRepository(organization_id)
        self.employees = EmployeeRepository(organization_id)
        self.manager_links = EmployeeManagerLinkRepository(organization_id)
        self.departments = DepartmentRepository(organization_id)
        self.suppliers = SupplierRepository(organization_id)
        self.contacts = SupplierContactRepository(organization_id)
        self.products = SupplierProductRepository(organization_id)
        self.budgets = BudgetRepository(organization_id)
        self.cost_centers = CostCenterRepository(organization_id)
        self.client = client or create_gemini_client()
        self.structured = structured or StructuredGenerationService(client=self.client)
        self.prompts = PromptRegistry()
        self.audit = AuditService()

    def _load_catalog(self) -> OrgCatalog:
        return OrgCatalog(
            organization_id=self.organization_id,
            employees=self.employees.list_all(),
            departments=self.departments.list_all(),
            suppliers=self.suppliers.list_all(),
            contacts=self.contacts.list_all(),
            products=self.products.list_all(),
            budgets=self.budgets.list_all(),
            cost_centers=self.cost_centers.list_all(),
            manager_links=self.manager_links.list_all(),
        )

    def _org_profile(self) -> OrganizationProfileSnapshot:
        org = OrganizationRepository().get(self.organization_id)
        if org is None:
            raise NotFoundError("Organization not found")
        return OrganizationProfileSnapshot(
            organization_id=org.id,
            name=org.name,
            plan_code=org.plan_code,
            industry=org.industry,
            country_code=org.country_code,
            default_currency=org.default_currency,
            status=org.status,
        )

    def _resolve_version(
        self, process_id: UUID, version_id: UUID | None
    ) -> tuple[Any, ProcessPlan]:
        versions = self.processes.list_versions(process_id)
        if not versions:
            raise ValidationAppError("Process has no plan versions to allocate")
        if version_id is not None:
            version = self.processes.get_version(process_id, version_id)
        else:
            # Prefer confirmed, else latest
            confirmed = [v for v in versions if v.status == "confirmed"]
            version = max(confirmed or versions, key=lambda v: v.version_number)
        plan = ProcessPlan.model_validate(version.plan_snapshot)
        return version, plan

    def _requirements_for_step(self, step: Any) -> list[str]:
        reqs: list[str] = []
        for item in list(step.required_resources) + list(step.approval_requirements):
            if item and item not in reqs:
                reqs.append(item)
        return reqs

    def allocate(
        self,
        process_id: UUID,
        *,
        user_id: UUID,
        correlation_id: str | None,
        permissions: frozenset[str],
        request: ResourceAllocationRequest | None = None,
    ) -> ResourceAllocationResult:
        request = request or ResourceAllocationRequest(process_id=process_id)
        if request.process_id != process_id:
            raise ValidationAppError("process_id mismatch")

        version, plan = self._resolve_version(process_id, request.process_version_id)
        catalog = self._load_catalog()
        matcher = DeterministicResourceMatcher(catalog)
        profile = self._org_profile()
        integrations = list_integration_availability(profile.plan_code)

        # Infer department / employee context from intent when possible
        preferred_dept = self._infer_department_id(plan, catalog)
        employee_context = self._infer_employee_context(plan, catalog)

        assignments: list[ResourceAssignment] = []
        all_candidates: list[ResourceCandidate] = []
        conflicts = []
        unresolved = []
        clarifying: list[str] = []
        needs_llm = False

        clarification_map = {
            (c.step_id, c.requirement.strip().lower()): c for c in request.clarification_choices
        }

        plan_context = " ".join(
            [
                getattr(plan, "goal", "") or "",
                " ".join(
                    f"{getattr(s, 'title', '')} {getattr(s, 'description', '')}"
                    for s in (plan.steps or [])
                ),
            ]
        )
        used_contact_ids: set[str] = set()

        for step in plan.steps:
            for requirement in self._requirements_for_step(step):
                key = (step.step_id, requirement.strip().lower())
                if key in clarification_map:
                    choice = clarification_map[key]
                    assigned = self._assignment_from_choice(
                        step.step_id, requirement, choice, catalog
                    )
                    if assigned is not None:
                        assignments.append(assigned)
                        if assigned.resource_type == ResourceType.SUPPLIER_CONTACT:
                            used_contact_ids.add(assigned.resource_id)
                    else:
                        unresolved.append(
                            UnresolvedResource(
                                id=f"unres_{step.step_id}_clarify",
                                step_id=step.step_id,
                                requirement=requirement,
                                question=(
                                    "Clarification choice did not match a valid active "
                                    "resource in this organization."
                                ),
                            )
                        )
                    continue

                outcome = matcher.match(
                    step_id=step.step_id,
                    requirement=requirement,
                    preferred_department_id=preferred_dept,
                    employee_context_id=employee_context,
                    context_text=plan_context,
                    exclude_resource_ids=used_contact_ids,
                )
                if outcome.assigned is not None:
                    assignments.append(
                        ResourceAssignment(
                            step_id=step.step_id,
                            requirement=requirement,
                            resource_id=outcome.assigned.resource_id,
                            resource_type=outcome.assigned.resource_type,
                            reason=outcome.assigned.reason,
                            data_source=outcome.assigned.data_source,
                            confidence=outcome.assigned.confidence,
                            authorization_status=outcome.assigned.authorization_status,
                            active_status=outcome.assigned.active_status,
                            conflict_status=outcome.assigned.conflict_status,
                            display_name=outcome.assigned.display_name,
                            metadata=outcome.assigned.metadata,
                        )
                    )
                    if outcome.assigned.resource_type == ResourceType.SUPPLIER_CONTACT:
                        used_contact_ids.add(outcome.assigned.resource_id)
                else:
                    needs_llm = True
                if outcome.candidates:
                    all_candidates.extend(outcome.candidates)
                if outcome.conflict:
                    conflicts.append(outcome.conflict)
                    clarifying.append(outcome.conflict.message)
                if outcome.unresolved:
                    unresolved.append(outcome.unresolved)
                    clarifying.append(outcome.unresolved.question)

        llm_used = False
        assist_summary = ""
        # Call Gemini only when directory matching left blocking gaps that need judgment.
        blocking_gaps = [
            u
            for u in unresolved
            if u.blocking
            and u.resource_type
            in {
                ResourceType.EMPLOYEE,
                ResourceType.MANAGER,
                ResourceType.APPROVAL_AUTHORITY,
                ResourceType.SUPPLIER,
                ResourceType.SUPPLIER_CONTACT,
                ResourceType.DEPARTMENT,
                ResourceType.BUDGET,
                ResourceType.UNKNOWN,
            }
        ]
        should_call_llm = bool(blocking_gaps) or bool(conflicts)
        if should_call_llm:
            assist = self._llm_assist(
                plan=plan,
                catalog=catalog,
                unresolved=unresolved,
                conflicts=conflicts,
                candidates=all_candidates,
                assignments=assignments,
                user_id=user_id,
                correlation_id=correlation_id,
                permissions=permissions,
                process_id=process_id,
            )
            if assist is not None:
                llm_used = True
                assist_summary = assist.reasoning_summary
                applied = self._apply_llm_proposals(
                    assist=assist,
                    catalog=catalog,
                    assignments=assignments,
                    unresolved=unresolved,
                    clarifying=clarifying,
                )
                if applied:
                    assist_summary = (
                        (assist_summary + " " if assist_summary else "")
                        + f"Gemini proposed {applied} catalog-validated assignment(s)."
                    )
                clarifying = list(dict.fromkeys(clarifying + assist.clarifying_questions))
                for alt in assist.alternative_suggestions:
                    if unresolved:
                        unresolved[0].suggested_alternatives.append(alt)

        # Drop clarifying questions that were resolved by assignment
        assigned_keys = {(a.step_id, a.requirement.strip().lower()) for a in assignments}
        unresolved = [
            u
            for u in unresolved
            if (u.step_id, u.requirement.strip().lower()) not in assigned_keys
        ]

        # Artifacts / catalogs / software are informational — don't block allocation
        artifact_tokens = (
            "quote",
            "invoice",
            "manifest",
            "monitor",
            "purchase order",
            "draft po",
            "approved po",
            "submitted po",
            "po details",
            "received ",
            "selected quote",
            "delivery",
            "physical ",
            "specification",
            "specifications",
            "quotation",
            "requirements",
            "original requirements",
            "reviewed quotation",
            "approved quotation",
            "quotation details",
            "prepared quote",
            "approved supplier list",
            "supplier list",
            "contact directory",
            "word processing",
            "software",
            "directory",
            "template",
            "rfq pack",
            "memo",
            "winning supplier",
            "received supplier",
        )
        for u in unresolved:
            req = u.requirement.lower()
            if u.resource_type == ResourceType.INTEGRATION:
                u.blocking = False
                u.question = (
                    f"System/catalog '{u.requirement}' is available via org integrations — "
                    "no person/supplier pick required."
                )
                continue
            if any(t in req for t in artifact_tokens):
                u.blocking = False
                u.question = (
                    f"Informational deliverable '{u.requirement}' — "
                    "no directory person/supplier required."
                )

        clarifying = list(dict.fromkeys([u.question for u in unresolved if u.blocking]))

        status: str
        blocking_unresolved = [u for u in unresolved if u.blocking]
        if blocking_unresolved or any(c.conflict_status != ConflictStatus.NONE for c in conflicts):
            status = "needs_clarification" if blocking_unresolved else "blocked"
            if blocking_unresolved:
                status = "needs_clarification"
        elif conflicts:
            status = "blocked"
        elif assignments:
            status = "resolved"
        else:
            status = "needs_clarification"

        if not plan.steps:
            status = "blocked"

        result = ResourceAllocationResult(
            organization_id=self.organization_id,
            process_id=process_id,
            process_version_id=version.id,
            status=status,  # type: ignore[arg-type]
            organization_profile=profile,
            assignments=assignments,
            candidates=all_candidates,
            conflicts=conflicts,
            unresolved=unresolved,
            integrations=integrations,
            clarifying_questions=clarifying[:12],
            reasoning_summary=(
                assist_summary
                or (
                    f"Allocated {len(assignments)} resource(s) from the organization directory "
                    "(employees, suppliers, budgets, integrations). "
                    "Agent 2 did not invent resources or execute side effects."
                )
            ),
            llm_used=llm_used,
            invented_resources=False,
            side_effects_executed=False,
            created_at=utcnow(),
            updated_at=utcnow(),
        )

        self._persist(result)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=user_id,
            action="allocation.completed",
            resource_type="process",
            resource_id=process_id,
            correlation_id=correlation_id,
            payload={
                "version_id": str(version.id),
                "status": result.status,
                "assignment_count": len(result.assignments),
                "unresolved_count": len(result.unresolved),
                "llm_used": llm_used,
            },
        )
        try:
            from app.agents.risk.service import RiskAnalysisService

            RiskAnalysisService(self.organization_id).invalidate_for_process(
                process_id,
                reason="Resource allocation changes invalidate the risk result",
            )
        except Exception:
            pass
        return result

    def get_allocation(self, process_id: UUID) -> ResourceAllocationResult:
        self.processes.get(process_id)
        records = [
            r
            for r in self.store.allocations.values()
            if r.organization_id == self.organization_id and r.process_id == process_id
        ]
        if not records:
            raise NotFoundError("Allocation not found")
        latest = max(records, key=lambda r: r.updated_at)
        return ResourceAllocationResult.model_validate(latest.result_snapshot)

    def _persist(self, result: ResourceAllocationResult) -> AllocationResultRecord:
        now = utcnow()
        record = AllocationResultRecord(
            id=new_id(),
            organization_id=self.organization_id,
            process_id=result.process_id,
            process_version_id=result.process_version_id,
            status=result.status,
            result_snapshot=result.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        self.store.allocations[record.id] = record
        return record

    def _assignment_from_choice(
        self,
        step_id: str,
        requirement: str,
        choice: ClarificationChoice,
        catalog: OrgCatalog,
    ) -> ResourceAssignment | None:
        # Validate choice against tenant catalog — never invent
        resource_id = choice.resource_id
        if choice.resource_type == ResourceType.INTEGRATION or resource_id.startswith(
            "integration:"
        ):
            key = resource_id.split(":", 1)[1] if ":" in resource_id else resource_id
            return ResourceAssignment(
                step_id=step_id,
                requirement=requirement,
                resource_id=f"integration:{key}",
                resource_type=ResourceType.INTEGRATION,
                reason="Integration capability mapping",
                data_source=DataSource.INTEGRATION_CATALOG,
                confidence=0.85,
                authorization_status=AuthorizationStatus.NOT_APPLICABLE,
                active_status=True,
                display_name=f"{key.replace('_', ' ').title()} capability",
            )
        try:
            rid = UUID(resource_id)
        except ValueError:
            return None

        if choice.resource_type in {
            ResourceType.EMPLOYEE,
            ResourceType.MANAGER,
            ResourceType.APPROVAL_AUTHORITY,
        }:
            emp = next((e for e in catalog.employees if e.id == rid), None)
            if emp is None or emp.organization_id != self.organization_id:
                return None
            if emp.status != "active":
                return None
            return ResourceAssignment(
                step_id=step_id,
                requirement=requirement,
                resource_id=str(emp.id),
                resource_type=choice.resource_type,
                reason="User clarification choice",
                data_source=DataSource.USER_CLARIFICATION,
                confidence=1.0,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
                display_name=emp.full_name,
                metadata={"email": emp.email, "role_code": emp.role_code, "is_manager": emp.is_manager},
            )
        if choice.resource_type == ResourceType.SUPPLIER:
            sup = next((s for s in catalog.suppliers if s.id == rid), None)
            if (
                sup is None
                or sup.organization_id != self.organization_id
                or sup.status != "active"
                or sup.approval_status != "approved"
            ):
                return None
            return ResourceAssignment(
                step_id=step_id,
                requirement=requirement,
                resource_id=str(sup.id),
                resource_type=ResourceType.SUPPLIER,
                reason="User clarification choice",
                data_source=DataSource.USER_CLARIFICATION,
                confidence=1.0,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
                display_name=sup.name,
            )
        if choice.resource_type == ResourceType.DEPARTMENT:
            dept = next((d for d in catalog.departments if d.id == rid), None)
            if dept is None or dept.status != "active":
                return None
            return ResourceAssignment(
                step_id=step_id,
                requirement=requirement,
                resource_id=str(dept.id),
                resource_type=ResourceType.DEPARTMENT,
                reason="User clarification choice",
                data_source=DataSource.USER_CLARIFICATION,
                confidence=1.0,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
                display_name=dept.name,
            )
        if choice.resource_type == ResourceType.BUDGET:
            bud = next((b for b in catalog.budgets if b.id == rid), None)
            if bud is None or bud.status != "active":
                return None
            return ResourceAssignment(
                step_id=step_id,
                requirement=requirement,
                resource_id=str(bud.id),
                resource_type=ResourceType.BUDGET,
                reason="User clarification choice",
                data_source=DataSource.USER_CLARIFICATION,
                confidence=1.0,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
                display_name=bud.name,
            )
        if choice.resource_type == ResourceType.SUPPLIER_CONTACT:
            contact = next((c for c in catalog.contacts if c.id == rid), None)
            if contact is None:
                return None
            return ResourceAssignment(
                step_id=step_id,
                requirement=requirement,
                resource_id=str(contact.id),
                resource_type=ResourceType.SUPPLIER_CONTACT,
                reason="User clarification choice",
                data_source=DataSource.USER_CLARIFICATION,
                confidence=1.0,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
                display_name=contact.full_name,
                metadata={"email": contact.email, "supplier_id": str(contact.supplier_id)},
            )
        return None

    def _infer_department_id(self, plan: ProcessPlan, catalog: OrgCatalog) -> UUID | None:
        names: list[str] = []
        if plan.intent:
            names.extend(plan.intent.systems)
            names.extend(plan.intent.actors)
        for step in plan.steps:
            names.extend(step.required_resources)
        for name in names:
            key = name.strip().lower()
            for d in catalog.departments:
                if d.status == "active" and (
                    d.name.lower() == key or (d.code and d.code.lower() == key)
                ):
                    return d.id
        # Single active department → deterministic context
        active = [d for d in catalog.departments if d.status == "active"]
        if len(active) == 1:
            return active[0].id
        return None

    def _infer_employee_context(self, plan: ProcessPlan, catalog: OrgCatalog) -> UUID | None:
        if not plan.intent:
            return None
        for actor in plan.intent.actors:
            key = actor.strip().lower()
            matches = [
                e
                for e in catalog.employees
                if e.status == "active"
                and (e.full_name.lower() == key or e.email.lower() == key)
            ]
            if len(matches) == 1:
                return matches[0].id
        return None

    def _directory_payload(self, catalog: OrgCatalog) -> dict[str, Any]:
        return {
            "employees": [
                {
                    "id": str(e.id),
                    "full_name": e.full_name,
                    "email": e.email,
                    "title": e.title,
                    "role_code": e.role_code,
                    "is_manager": e.is_manager,
                    "department_id": str(e.department_id) if e.department_id else None,
                    "approval_authority_limit": e.approval_authority_limit,
                    "status": e.status,
                }
                for e in catalog.employees
                if e.status == "active"
            ],
            "departments": [
                {
                    "id": str(d.id),
                    "name": d.name,
                    "code": d.code,
                    "manager_employee_id": str(d.manager_employee_id)
                    if d.manager_employee_id
                    else None,
                }
                for d in catalog.departments
                if d.status == "active"
            ],
            "suppliers": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "code": s.code,
                    "approval_status": s.approval_status,
                    "status": s.status,
                }
                for s in catalog.suppliers
                if s.status == "active"
            ],
            "supplier_contacts": [
                {
                    "id": str(c.id),
                    "supplier_id": str(c.supplier_id),
                    "full_name": c.full_name,
                    "email": c.email,
                }
                for c in catalog.contacts
            ],
            "budgets": [
                {
                    "id": str(b.id),
                    "name": b.name,
                    "code": getattr(b, "code", None),
                    "amount": getattr(b, "amount", None),
                }
                for b in catalog.budgets
                if b.status == "active"
            ],
            "cost_centers": [
                {"id": str(c.id), "name": c.name, "code": c.code}
                for c in catalog.cost_centers
                if c.status == "active"
            ],
        }

    def _apply_llm_proposals(
        self,
        *,
        assist: AllocationAssistOutput,
        catalog: OrgCatalog,
        assignments: list[ResourceAssignment],
        unresolved: list[UnresolvedResource],
        clarifying: list[str],
    ) -> int:
        """Validate Gemini proposed_assignments against the org catalog and apply them."""
        existing = {(a.step_id, a.requirement.strip().lower()) for a in assignments}
        applied = 0
        for raw in assist.proposed_assignments or []:
            if not isinstance(raw, dict):
                continue
            step_id = str(raw.get("step_id") or "").strip()
            requirement = str(raw.get("requirement") or "").strip()
            resource_id = str(raw.get("resource_id") or "").strip()
            resource_type_raw = str(raw.get("resource_type") or "unknown").strip().lower()
            reason = str(raw.get("reason") or "Gemini catalog match").strip()
            display_hint = str(
                raw.get("display_name") or raw.get("name") or raw.get("full_name") or ""
            ).strip()
            if not step_id or not requirement:
                continue
            key = (step_id, requirement.lower())
            if key in existing:
                continue
            try:
                rtype = ResourceType(resource_type_raw)
            except ValueError:
                rtype = ResourceType.UNKNOWN

            assigned = None
            if resource_id:
                choice = ClarificationChoice(
                    step_id=step_id,
                    requirement=requirement,
                    resource_id=resource_id,
                    resource_type=rtype if rtype != ResourceType.UNKNOWN else ResourceType.EMPLOYEE,
                )
                assigned = self._assignment_from_choice(step_id, requirement, choice, catalog)
                if assigned is None and rtype == ResourceType.UNKNOWN:
                    for guess in (
                        ResourceType.EMPLOYEE,
                        ResourceType.SUPPLIER,
                        ResourceType.SUPPLIER_CONTACT,
                        ResourceType.DEPARTMENT,
                        ResourceType.BUDGET,
                        ResourceType.MANAGER,
                        ResourceType.APPROVAL_AUTHORITY,
                    ):
                        choice.resource_type = guess
                        assigned = self._assignment_from_choice(
                            step_id, requirement, choice, catalog
                        )
                        if assigned is not None:
                            break

            if assigned is None and display_hint:
                assigned = self._assignment_from_display_name(
                    step_id, requirement, display_hint, catalog, preferred_type=rtype
                )

            if assigned is None:
                continue
            assigned.reason = reason
            assigned.data_source = DataSource.LLM_INTERPRETATION
            assigned.confidence = min(0.95, max(0.7, assigned.confidence))
            assignments.append(assigned)
            existing.add(key)
            applied += 1
        return applied

    def _assignment_from_display_name(
        self,
        step_id: str,
        requirement: str,
        display_name: str,
        catalog: OrgCatalog,
        *,
        preferred_type: ResourceType = ResourceType.UNKNOWN,
    ) -> ResourceAssignment | None:
        key = display_name.strip().lower()
        if not key:
            return None
        emp = next(
            (e for e in catalog.employees if e.status == "active" and e.full_name.lower() == key),
            None,
        )
        if emp and preferred_type in {
            ResourceType.UNKNOWN,
            ResourceType.EMPLOYEE,
            ResourceType.MANAGER,
            ResourceType.APPROVAL_AUTHORITY,
        }:
            rtype = (
                preferred_type
                if preferred_type != ResourceType.UNKNOWN
                else ResourceType.EMPLOYEE
            )
            return ResourceAssignment(
                step_id=step_id,
                requirement=requirement,
                resource_id=str(emp.id),
                resource_type=rtype,
                reason=f"Gemini matched directory person {emp.full_name}",
                data_source=DataSource.LLM_INTERPRETATION,
                confidence=0.9,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
                display_name=emp.full_name,
            )
        contact = next(
            (c for c in catalog.contacts if c.full_name.lower() == key or (c.email and c.email.lower() == key)),
            None,
        )
        if contact and preferred_type in {
            ResourceType.UNKNOWN,
            ResourceType.SUPPLIER_CONTACT,
        }:
            return ResourceAssignment(
                step_id=step_id,
                requirement=requirement,
                resource_id=str(contact.id),
                resource_type=ResourceType.SUPPLIER_CONTACT,
                reason=f"Gemini matched supplier contact {contact.full_name}",
                data_source=DataSource.LLM_INTERPRETATION,
                confidence=0.9,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
                display_name=contact.full_name,
            )
        supplier = next(
            (
                s
                for s in catalog.suppliers
                if s.status == "active"
                and s.approval_status == "approved"
                and s.name.lower() == key
            ),
            None,
        )
        if supplier and preferred_type in {ResourceType.UNKNOWN, ResourceType.SUPPLIER}:
            return ResourceAssignment(
                step_id=step_id,
                requirement=requirement,
                resource_id=str(supplier.id),
                resource_type=ResourceType.SUPPLIER,
                reason=f"Gemini matched approved supplier {supplier.name}",
                data_source=DataSource.LLM_INTERPRETATION,
                confidence=0.9,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                active_status=True,
                display_name=supplier.name,
            )
        return None

    def _llm_assist(
        self,
        *,
        plan: ProcessPlan,
        catalog: OrgCatalog,
        unresolved: list,
        conflicts: list,
        candidates: list[ResourceCandidate],
        assignments: list[ResourceAssignment] | None = None,
        user_id: UUID,
        correlation_id: str | None,
        permissions: frozenset[str],
        process_id: UUID,
    ) -> AllocationAssistOutput | None:
        if isinstance(self.client, FakeGeminiClient) and not self.client.structured_queue:
            return self._heuristic_assist(unresolved, conflicts, candidates, catalog)

        directory_summary = {
            "organization_directory": self._directory_payload(catalog),
            "already_assigned": [
                {
                    "step_id": a.step_id,
                    "requirement": a.requirement,
                    "resource_id": a.resource_id,
                    "display_name": a.display_name,
                    "resource_type": a.resource_type.value,
                }
                for a in (assignments or [])
                if a.resource_type != ResourceType.INTEGRATION
            ],
            "unresolved": [
                {
                    "step_id": u.step_id,
                    "requirement": u.requirement,
                    "resource_type": u.resource_type.value,
                    "question": u.question,
                    "candidate_ids": [c.resource_id for c in u.candidates[:8]],
                    "candidate_names": [c.display_name for c in u.candidates[:8]],
                }
                for u in unresolved
                if u.blocking
            ],
            "conflicts": [c.model_dump(mode="json") for c in conflicts[:10]],
        }
        # Compact plan — full dump times out Gemini on large processes
        compact_plan = {
            "goal": getattr(plan, "goal", None) or getattr(plan, "title", None),
            "steps": [
                {
                    "id": getattr(s, "id", None) or getattr(s, "step_id", None),
                    "title": getattr(s, "title", None) or getattr(s, "name", None),
                    "required_resources": getattr(s, "required_resources", None)
                    or getattr(s, "resources", None)
                    or [],
                }
                for s in (getattr(plan, "steps", None) or [])[:40]
            ],
        }
        system, user_prompt = self.prompts.render(
            AgentKind.RESOURCE,
            "allocate_resources",
            plan_json=json.dumps(compact_plan),
            directory=json.dumps(directory_summary),
        )
        system += (
            " You MUST fill proposed_assignments for every unresolved requirement you can "
            "map to an existing directory resource. Each proposed_assignment needs "
            "step_id, requirement, resource_id (exact UUID from directory), resource_type, "
            "and reason. Only use IDs present in organization_directory. "
            "Prefer named people (e.g. Jordan Lee) and approved suppliers. "
            "Never invent employees, suppliers, or contacts. Never send email, create POs, "
            "approve spending, or change organization data."
        )
        ctx = AgentExecutionContext(
            organization_id=self.organization_id,
            process_id=process_id,
            correlation_id=correlation_id,
            trace_id=correlation_id,
            actor_user_id=user_id,
            agent=AgentKind.RESOURCE,
            permissions=permissions,
        )
        try:
            result = self.structured.generate(
                context=ctx,
                output_model=AllocationAssistOutput,
                system_instruction=system,
                user_prompt=user_prompt,
                max_output_tokens=2048,
            )
            return result.data
        except Exception as exc:
            logger.warning("allocation.llm_assist_failed", error=str(exc))
            return self._heuristic_assist(unresolved, conflicts, candidates, catalog)

    def _heuristic_assist(
        self,
        unresolved: list,
        conflicts: list,
        candidates: list[ResourceCandidate],
        catalog: OrgCatalog | None = None,
    ) -> AllocationAssistOutput:
        questions = [u.question for u in unresolved]
        explanations = [c.message for c in conflicts]
        alternatives = [
            f"Consider {c.display_name} ({c.resource_type.value})" for c in candidates[:5]
        ]
        proposals: list[dict[str, str]] = []
        if catalog is not None:
            for u in unresolved:
                req = u.requirement.strip().lower()
                # Prefer explicit candidates already scored by the matcher
                if u.candidates:
                    typed = [
                        c
                        for c in u.candidates
                        if c.resource_type == u.resource_type or u.resource_type == ResourceType.UNKNOWN
                    ]
                    pool = typed or list(u.candidates)
                    # Prefer managers / higher confidence for approval gaps
                    if u.resource_type == ResourceType.APPROVAL_AUTHORITY:
                        managers = [
                            c
                            for c in pool
                            if (c.metadata or {}).get("is_manager")
                            or c.resource_type
                            in {ResourceType.MANAGER, ResourceType.APPROVAL_AUTHORITY}
                        ]
                        if managers:
                            pool = managers
                    top = sorted(
                        pool,
                        key=lambda c: (
                            c.confidence,
                            (c.metadata or {}).get("approval_authority_limit") or 0,
                        ),
                        reverse=True,
                    )[0]
                    threshold = (
                        0.6
                        if u.resource_type
                        in {ResourceType.APPROVAL_AUTHORITY, ResourceType.MANAGER}
                        else 0.85
                    )
                    # Only auto-pick clear winners — keep true ambiguity for human clarification.
                    # Never auto-pick a supplier when the gap is a missing supplier contact.
                    if (
                        top.confidence >= threshold
                        and top.active_status
                        and not (
                            u.resource_type == ResourceType.SUPPLIER_CONTACT
                            and top.resource_type == ResourceType.SUPPLIER
                        )
                    ):
                        proposals.append(
                            {
                                "step_id": u.step_id,
                                "requirement": u.requirement,
                                "resource_id": top.resource_id,
                                "resource_type": top.resource_type.value,
                                "reason": f"Best directory candidate: {top.display_name}",
                                "display_name": top.display_name,
                            }
                        )
                        continue
                # Name-in-requirement heuristic
                emp_hits = [
                    e
                    for e in catalog.employees
                    if e.status == "active"
                    and len(e.full_name) >= 3
                    and e.full_name.lower() in req
                ]
                if len(emp_hits) == 1:
                    e = emp_hits[0]
                    proposals.append(
                        {
                            "step_id": u.step_id,
                            "requirement": u.requirement,
                            "resource_id": str(e.id),
                            "resource_type": "employee",
                            "reason": f"Heuristic name match to {e.full_name}",
                        }
                    )
                    continue
                if "contact" in req:
                    continue
                if u.resource_type in {
                    ResourceType.SUPPLIER_CONTACT,
                    ResourceType.INTEGRATION,
                }:
                    continue
                sup_hits = [
                    s
                    for s in catalog.suppliers
                    if s.status == "active"
                    and s.approval_status == "approved"
                    and len(s.name) >= 3
                    and s.name.lower() in req
                ]
                if len(sup_hits) == 1:
                    s = sup_hits[0]
                    proposals.append(
                        {
                            "step_id": u.step_id,
                            "requirement": u.requirement,
                            "resource_id": str(s.id),
                            "resource_type": "supplier",
                            "reason": f"Heuristic supplier match to {s.name}",
                        }
                    )
        return AllocationAssistOutput(
            clarifying_questions=questions,
            conflict_explanations=explanations,
            candidate_explanations=[
                f"{c.display_name}: {c.reason}" for c in candidates[:8]
            ],
            alternative_suggestions=alternatives,
            proposed_assignments=proposals,
            reasoning_summary=(
                "Deterministic matching plus heuristic name matching against the company directory. "
                "Clarification required only for remaining unresolved items; no resources were invented."
            ),
        )
