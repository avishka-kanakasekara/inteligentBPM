"""Organization directory management services (CRUD, rules, CSV import)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.audit import AuditService
from app.contracts.common import utcnow
from app.database.memory import (
    BudgetRecord,
    CostCenterRecord,
    DepartmentRecord,
    EmployeeManagerLinkRecord,
    EmployeeRecord,
    OrganizationRecord,
    PolicyRecord,
    SupplierContactRecord,
    SupplierProductRecord,
    SupplierRecord,
    get_memory_store,
    new_id,
)
from app.repositories.memory_repos import (
    BudgetRepository,
    CostCenterRepository,
    DepartmentRepository,
    EmployeeManagerLinkRepository,
    EmployeeRepository,
    OrganizationRepository,
    PolicyRepository,
    SupplierContactRepository,
    SupplierProductRepository,
    SupplierRepository,
)
from app.security.errors import ConflictError, NotFoundError, ValidationAppError

APPROVED_SUPPLIER = "approved"
ACTIVE = "active"
INACTIVE = "inactive"


def _norm_email(email: str | None) -> str | None:
    if email is None:
        return None
    value = email.strip().lower()
    return value or None


@dataclass
class ImportRowError:
    row_number: int
    field: str | None
    code: str
    message: str


@dataclass
class ImportPreviewResult:
    valid_rows: list[dict[str, Any]]
    errors: list[ImportRowError]
    duplicates: list[ImportRowError]
    total_rows: int


class OrganizationProfileService:
    def __init__(self) -> None:
        self.orgs = OrganizationRepository()
        self.audit = AuditService()

    def get(self, organization_id: UUID) -> OrganizationRecord:
        org = self.orgs.get(organization_id)
        if org is None:
            raise NotFoundError("Organization not found")
        return org

    def update_profile(
        self,
        organization_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
        **fields: Any,
    ) -> OrganizationRecord:
        org = self.orgs.update_profile(organization_id, **fields)
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action="organization.profile_updated",
            resource_type="organization",
            resource_id=organization_id,
            correlation_id=correlation_id,
            payload={k: v for k, v in fields.items() if v is not None},
        )
        return org


class EmployeeService:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.repo = EmployeeRepository(organization_id)
        self.links = EmployeeManagerLinkRepository(organization_id)
        self.audit = AuditService()

    def list_all(self) -> list[EmployeeRecord]:
        return self.repo.list_all()

    def get(self, employee_id: UUID) -> EmployeeRecord:
        return self.repo.get(employee_id)

    def assert_assignable(self, employee_id: UUID) -> EmployeeRecord:
        """Inactive employees cannot be assigned to new process steps."""
        employee = self.repo.get(employee_id)
        if employee.status != ACTIVE:
            raise ValidationAppError(
                "Inactive employees cannot be assigned to new process steps",
                details={"employee_id": str(employee_id), "status": employee.status},
            )
        return employee

    def create(
        self,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
        full_name: str,
        email: str,
        title: str | None = None,
        department_id: UUID | None = None,
        is_manager: bool = False,
        employee_code: str | None = None,
        role_code: str | None = None,
        approval_authority_limit: float | None = None,
        approval_authority_currency: str = "USD",
    ) -> EmployeeRecord:
        email_norm = _norm_email(email)
        if not email_norm:
            raise ValidationAppError("email is required")
        self.repo.assert_no_active_email_duplicate(email_norm)
        record = self.repo.create(
            full_name=full_name.strip(),
            email=email_norm,
            title=title,
            department_id=department_id,
            is_manager=is_manager,
            employee_code=employee_code,
            role_code=role_code,
            approval_authority_limit=approval_authority_limit,
            approval_authority_currency=approval_authority_currency,
            status=ACTIVE,
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="employee.created",
            resource_type="employee",
            resource_id=record.id,
            correlation_id=correlation_id,
            payload={"email": record.email, "role_code": record.role_code},
        )
        return record

    def update(
        self,
        employee_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
        **fields: Any,
    ) -> EmployeeRecord:
        if "email" in fields and fields["email"] is not None:
            email_norm = _norm_email(fields["email"])
            fields["email"] = email_norm
            if email_norm:
                self.repo.assert_no_active_email_duplicate(email_norm, exclude_id=employee_id)
        record = self.repo.update(employee_id, **fields)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="employee.updated",
            resource_type="employee",
            resource_id=record.id,
            correlation_id=correlation_id,
            payload={k: v for k, v in fields.items() if v is not None},
        )
        return record

    def deactivate(
        self,
        employee_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> EmployeeRecord:
        """Soft-deactivate; historical process references remain valid."""
        record = self.repo.update(employee_id, status=INACTIVE)
        # Soft-deactivate manager links involving this employee
        for link in self.links.list_all():
            if link.employee_id == employee_id or link.manager_employee_id == employee_id:
                if link.status == ACTIVE:
                    self.links.update(link.id, status=INACTIVE)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="employee.deactivated",
            resource_type="employee",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def set_manager_link(
        self,
        *,
        employee_id: UUID,
        manager_employee_id: UUID,
        link_type: str = "direct",
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> EmployeeManagerLinkRecord:
        if employee_id == manager_employee_id:
            raise ValidationAppError("Employee cannot manage themselves")
        employee = self.repo.get(employee_id)
        manager = self.repo.get(manager_employee_id)
        if employee.status != ACTIVE or manager.status != ACTIVE:
            raise ValidationAppError("Both employee and manager must be active")
        if not manager.is_manager:
            raise ValidationAppError(
                "Ambiguous manager relationship: target is not marked as a manager",
                details={"manager_employee_id": str(manager_employee_id)},
            )
        # Do not guess: refuse if multiple active direct managers already exist
        existing = [
            link
            for link in self.links.list_for_employee(employee_id)
            if link.status == ACTIVE and link.link_type == link_type
        ]
        if existing and existing[0].manager_employee_id != manager_employee_id:
            raise ConflictError(
                "Ambiguous manager relationship: an active manager already exists; "
                "deactivate the existing link before assigning another",
                code="AMBIGUOUS_MANAGER",
                details={
                    "employee_id": str(employee_id),
                    "existing_manager_id": str(existing[0].manager_employee_id),
                },
            )
        if existing and existing[0].manager_employee_id == manager_employee_id:
            return existing[0]
        link = self.links.create(
            employee_id=employee_id,
            manager_employee_id=manager_employee_id,
            link_type=link_type,
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="employee.manager_linked",
            resource_type="employee_manager_link",
            resource_id=link.id,
            correlation_id=correlation_id,
            payload={
                "employee_id": str(employee_id),
                "manager_employee_id": str(manager_employee_id),
                "link_type": link_type,
            },
        )
        return link


class SupplierService:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.repo = SupplierRepository(organization_id)
        self.contacts = SupplierContactRepository(organization_id)
        self.products = SupplierProductRepository(organization_id)
        self.audit = AuditService()

    def list_all(self) -> list[SupplierRecord]:
        return self.repo.list_all()

    def get(self, supplier_id: UUID) -> SupplierRecord:
        return self.repo.get(supplier_id)

    def assert_approved(self, supplier_id: UUID) -> SupplierRecord:
        supplier = self.repo.get(supplier_id)
        if supplier.approval_status != APPROVED_SUPPLIER:
            raise ValidationAppError(
                "Unapproved suppliers cannot be treated as approved suppliers",
                details={
                    "supplier_id": str(supplier_id),
                    "approval_status": supplier.approval_status,
                },
            )
        if supplier.status != ACTIVE:
            raise ValidationAppError(
                "Inactive suppliers cannot be used as approved suppliers",
                details={"supplier_id": str(supplier_id), "status": supplier.status},
            )
        return supplier

    def create(
        self,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
        name: str,
        code: str | None = None,
        website: str | None = None,
        country_code: str | None = None,
        approval_status: str = "pending",
    ) -> SupplierRecord:
        record = self.repo.create(
            name=name.strip(),
            code=code,
            website=website,
            country_code=country_code,
            approval_status=approval_status,
            status=ACTIVE,
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="supplier.created",
            resource_type="supplier",
            resource_id=record.id,
            correlation_id=correlation_id,
            payload={"name": record.name, "approval_status": record.approval_status},
        )
        return record

    def update(
        self,
        supplier_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
        **fields: Any,
    ) -> SupplierRecord:
        record = self.repo.update(supplier_id, **fields)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="supplier.updated",
            resource_type="supplier",
            resource_id=record.id,
            correlation_id=correlation_id,
            payload={k: v for k, v in fields.items() if v is not None},
        )
        return record

    def deactivate(
        self,
        supplier_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> SupplierRecord:
        record = self.repo.update(supplier_id, status=INACTIVE)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="supplier.deactivated",
            resource_type="supplier",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def add_contact(
        self,
        *,
        supplier_id: UUID,
        full_name: str,
        email: str | None,
        is_primary: bool = False,
        phone: str | None = None,
        role_title: str | None = None,
        allow_duplicate_email: bool = False,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> SupplierContactRecord:
        self.repo.get(supplier_id)
        email_norm = _norm_email(email)
        if email_norm and not allow_duplicate_email:
            self.contacts.assert_no_active_email_duplicate(
                supplier_id, email_norm, allow_duplicate=False
            )
        record = self.contacts.create(
            supplier_id=supplier_id,
            full_name=full_name.strip(),
            email=email_norm,
            is_primary=is_primary,
            phone=phone,
            role_title=role_title,
            allow_duplicate_email=allow_duplicate_email,
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="supplier_contact.created",
            resource_type="supplier_contact",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def add_product(
        self,
        *,
        supplier_id: UUID,
        name: str,
        sku: str | None = None,
        unit_price: float | None = None,
        currency_code: str = "USD",
        description: str | None = None,
        unit_of_measure: str | None = None,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> SupplierProductRecord:
        self.repo.get(supplier_id)
        record = self.products.create(
            supplier_id=supplier_id,
            name=name.strip(),
            sku=sku,
            unit_price=unit_price,
            currency_code=currency_code,
            description=description,
            unit_of_measure=unit_of_measure,
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="supplier_product.created",
            resource_type="supplier_product",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record


class DepartmentService:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.repo = DepartmentRepository(organization_id)
        self.audit = AuditService()

    def list_all(self) -> list[DepartmentRecord]:
        return self.repo.list_all()

    def create(
        self,
        *,
        name: str,
        code: str | None,
        parent_department_id: UUID | None,
        manager_employee_id: UUID | None,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> DepartmentRecord:
        record = self.repo.create(
            name=name.strip(),
            code=code,
            parent_department_id=parent_department_id,
            manager_employee_id=manager_employee_id,
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="department.created",
            resource_type="department",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def update(
        self,
        department_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
        **fields: Any,
    ) -> DepartmentRecord:
        record = self.repo.update(department_id, **fields)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="department.updated",
            resource_type="department",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def deactivate(
        self,
        department_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> DepartmentRecord:
        record = self.repo.update(department_id, status=INACTIVE)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="department.deactivated",
            resource_type="department",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record


class CostCenterService:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.repo = CostCenterRepository(organization_id)
        self.audit = AuditService()

    def list_all(self) -> list[CostCenterRecord]:
        return self.repo.list_all()

    def create(
        self,
        *,
        code: str,
        name: str,
        department_id: UUID | None,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> CostCenterRecord:
        record = self.repo.create(code=code.strip(), name=name.strip(), department_id=department_id)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="cost_center.created",
            resource_type="cost_center",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def update(
        self,
        cost_center_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
        **fields: Any,
    ) -> CostCenterRecord:
        record = self.repo.update(cost_center_id, **fields)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="cost_center.updated",
            resource_type="cost_center",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def deactivate(
        self,
        cost_center_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> CostCenterRecord:
        record = self.repo.update(cost_center_id, status=INACTIVE)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="cost_center.deactivated",
            resource_type="cost_center",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record


class BudgetService:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.repo = BudgetRepository(organization_id)
        self.audit = AuditService()

    def list_all(self) -> list[BudgetRecord]:
        return self.repo.list_all()

    def create(
        self,
        *,
        name: str,
        fiscal_year: int,
        amount_total: float,
        currency_code: str,
        department_id: UUID | None,
        cost_center_id: UUID | None,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> BudgetRecord:
        record = self.repo.create(
            name=name.strip(),
            fiscal_year=fiscal_year,
            amount_total=amount_total,
            currency_code=currency_code,
            department_id=department_id,
            cost_center_id=cost_center_id,
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="budget.created",
            resource_type="budget",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def update(
        self,
        budget_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
        **fields: Any,
    ) -> BudgetRecord:
        record = self.repo.update(budget_id, **fields)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="budget.updated",
            resource_type="budget",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def deactivate(
        self,
        budget_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> BudgetRecord:
        record = self.repo.update(budget_id, status="cancelled")
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="budget.deactivated",
            resource_type="budget",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record


class PolicyService:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.repo = PolicyRepository(organization_id)
        self.audit = AuditService()

    def list_all(self) -> list[PolicyRecord]:
        return self.repo.list_all()

    def create(
        self,
        *,
        code: str,
        title: str,
        category: str | None,
        description: str | None,
        owner_employee_id: UUID | None,
        metadata: dict[str, Any] | None,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> PolicyRecord:
        record = self.repo.create(
            code=code.strip(),
            title=title.strip(),
            category=category,
            description=description,
            owner_employee_id=owner_employee_id,
            metadata=metadata or {},
        )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="policy.created",
            resource_type="policy",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def update(
        self,
        policy_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
        **fields: Any,
    ) -> PolicyRecord:
        record = self.repo.update(policy_id, **fields)
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="policy.updated",
            resource_type="policy",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record

    def deactivate(
        self,
        policy_id: UUID,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> PolicyRecord:
        record = self.repo.update(policy_id, status="archived")
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="policy.deactivated",
            resource_type="policy",
            resource_id=record.id,
            correlation_id=correlation_id,
        )
        return record


class CsvImportService:
    """CSV preview + commit with validation, duplicate detection, and error reporting."""

    EMPLOYEE_REQUIRED = ("full_name", "email")
    SUPPLIER_REQUIRED = ("name",)

    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.employees = EmployeeService(organization_id)
        self.suppliers = SupplierService(organization_id)
        self.audit = AuditService()

    @staticmethod
    def _parse_csv(content: str) -> list[dict[str, str]]:
        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None:
            raise ValidationAppError("CSV must include a header row")
        rows: list[dict[str, str]] = []
        for raw in reader:
            rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()})
        return rows

    def preview_employees(self, content: str) -> ImportPreviewResult:
        rows = self._parse_csv(content)
        errors: list[ImportRowError] = []
        duplicates: list[ImportRowError] = []
        valid: list[dict[str, Any]] = []
        seen_emails: set[str] = set()
        existing = {
            e.email.lower()
            for e in self.employees.list_all()
            if e.status == ACTIVE
        }

        for idx, row in enumerate(rows, start=2):
            for field in self.EMPLOYEE_REQUIRED:
                if not row.get(field):
                    errors.append(
                        ImportRowError(idx, field, "REQUIRED", f"{field} is required")
                    )
            email = _norm_email(row.get("email"))
            if email:
                if email in seen_emails:
                    duplicates.append(
                        ImportRowError(
                            idx, "email", "DUPLICATE_IN_FILE", "Duplicate email in CSV"
                        )
                    )
                elif email in existing:
                    duplicates.append(
                        ImportRowError(
                            idx,
                            "email",
                            "DUPLICATE_ACTIVE",
                            "Active employee with this email already exists",
                        )
                    )
                else:
                    seen_emails.add(email)

            manager_email = _norm_email(row.get("manager_email"))
            if manager_email:
                matches = [
                    e
                    for e in self.employees.list_all()
                    if e.email == manager_email and e.status == ACTIVE and e.is_manager
                ]
                if len(matches) == 0:
                    errors.append(
                        ImportRowError(
                            idx,
                            "manager_email",
                            "MANAGER_NOT_FOUND",
                            "Manager email does not uniquely resolve to an active manager "
                            "(relationships are never guessed)",
                        )
                    )
                elif len(matches) > 1:
                    errors.append(
                        ImportRowError(
                            idx,
                            "manager_email",
                            "AMBIGUOUS_MANAGER",
                            "Ambiguous manager relationship; multiple matches found",
                        )
                    )

            if not any(e.row_number == idx for e in errors + duplicates):
                valid.append(
                    {
                        "full_name": row.get("full_name", ""),
                        "email": email,
                        "title": row.get("title") or None,
                        "role_code": row.get("role_code") or None,
                        "is_manager": (row.get("is_manager") or "").lower() in {"1", "true", "yes"},
                        "manager_email": manager_email,
                        "approval_authority_limit": (
                            float(row["approval_authority_limit"])
                            if row.get("approval_authority_limit")
                            else None
                        ),
                    }
                )

        return ImportPreviewResult(
            valid_rows=valid,
            errors=errors,
            duplicates=duplicates,
            total_rows=len(rows),
        )

    def commit_employees(
        self,
        content: str,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        preview = self.preview_employees(content)
        if preview.errors or preview.duplicates:
            raise ValidationAppError(
                "Import validation failed",
                details={
                    "errors": [e.__dict__ for e in preview.errors],
                    "duplicates": [d.__dict__ for d in preview.duplicates],
                },
            )
        created: list[str] = []
        for row in preview.valid_rows:
            employee = self.employees.create(
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
                full_name=row["full_name"],
                email=row["email"],
                title=row.get("title"),
                is_manager=bool(row.get("is_manager")),
                role_code=row.get("role_code"),
                approval_authority_limit=row.get("approval_authority_limit"),
            )
            created.append(str(employee.id))
            manager_email = row.get("manager_email")
            if manager_email:
                managers = [
                    e
                    for e in self.employees.list_all()
                    if e.email == manager_email and e.is_manager and e.status == ACTIVE
                ]
                if len(managers) != 1:
                    raise ValidationAppError(
                        "Ambiguous manager relationship must not be guessed",
                        details={"manager_email": manager_email},
                    )
                self.employees.set_manager_link(
                    employee_id=employee.id,
                    manager_employee_id=managers[0].id,
                    actor_user_id=actor_user_id,
                    correlation_id=correlation_id,
                )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="employees.imported",
            resource_type="employee",
            correlation_id=correlation_id,
            payload={"created_count": len(created)},
        )
        return {"created_ids": created, "created_count": len(created)}

    def preview_suppliers(self, content: str) -> ImportPreviewResult:
        rows = self._parse_csv(content)
        errors: list[ImportRowError] = []
        duplicates: list[ImportRowError] = []
        valid: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        existing = {s.name.lower() for s in self.suppliers.list_all() if s.status == ACTIVE}

        for idx, row in enumerate(rows, start=2):
            name = (row.get("name") or "").strip()
            if not name:
                errors.append(ImportRowError(idx, "name", "REQUIRED", "name is required"))
            else:
                key = name.lower()
                if key in seen_names:
                    duplicates.append(
                        ImportRowError(idx, "name", "DUPLICATE_IN_FILE", "Duplicate name in CSV")
                    )
                elif key in existing:
                    duplicates.append(
                        ImportRowError(
                            idx,
                            "name",
                            "DUPLICATE_ACTIVE",
                            "Active supplier with this name already exists",
                        )
                    )
                else:
                    seen_names.add(key)

            approval = (row.get("approval_status") or "pending").lower()
            if approval not in {"pending", "approved", "rejected", "suspended"}:
                errors.append(
                    ImportRowError(
                        idx, "approval_status", "INVALID", "Invalid approval_status"
                    )
                )

            if not any(e.row_number == idx for e in errors + duplicates):
                valid.append(
                    {
                        "name": name,
                        "code": row.get("code") or None,
                        "country_code": row.get("country_code") or None,
                        "website": row.get("website") or None,
                        "approval_status": approval,
                        "contact_name": row.get("contact_name") or None,
                        "contact_email": _norm_email(row.get("contact_email")),
                        "allow_duplicate_email": (row.get("allow_duplicate_email") or "").lower()
                        in {"1", "true", "yes"},
                    }
                )

        return ImportPreviewResult(
            valid_rows=valid,
            errors=errors,
            duplicates=duplicates,
            total_rows=len(rows),
        )

    def commit_suppliers(
        self,
        content: str,
        *,
        actor_user_id: UUID,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        preview = self.preview_suppliers(content)
        if preview.errors or preview.duplicates:
            raise ValidationAppError(
                "Import validation failed",
                details={
                    "errors": [e.__dict__ for e in preview.errors],
                    "duplicates": [d.__dict__ for d in preview.duplicates],
                },
            )
        created: list[str] = []
        for row in preview.valid_rows:
            supplier = self.suppliers.create(
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
                name=row["name"],
                code=row.get("code"),
                website=row.get("website"),
                country_code=row.get("country_code"),
                approval_status=row.get("approval_status") or "pending",
            )
            created.append(str(supplier.id))
            if row.get("contact_name"):
                self.suppliers.add_contact(
                    supplier_id=supplier.id,
                    full_name=row["contact_name"],
                    email=row.get("contact_email"),
                    allow_duplicate_email=bool(row.get("allow_duplicate_email")),
                    actor_user_id=actor_user_id,
                    correlation_id=correlation_id,
                )
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="suppliers.imported",
            resource_type="supplier",
            correlation_id=correlation_id,
            payload={"created_count": len(created)},
        )
        return {"created_ids": created, "created_count": len(created)}


# Keep a lightweight registry of org role labels for directory UI
ORG_ROLE_CATALOG = [
    {"code": "owner", "label": "Owner", "description": "Full organization control"},
    {"code": "admin", "label": "Admin", "description": "Configure org and directory"},
    {"code": "manager", "label": "Manager", "description": "Manage team and approvals"},
    {"code": "employee", "label": "Employee", "description": "Standard participant"},
    {"code": "compliance", "label": "Compliance", "description": "Policy and risk oversight"},
    {"code": "auditor", "label": "Auditor", "description": "Read-only audit access"},
]


def seed_demo_directory(organization_id: UUID) -> None:
    """Optional helper for local demos — not used by tests by default."""
    store = get_memory_store()
    if any(e.organization_id == organization_id for e in store.employees.values()):
        return
    now = utcnow()
    dept = DepartmentRecord(
        id=new_id(),
        organization_id=organization_id,
        name="Operations",
        code="OPS",
        status=ACTIVE,
        created_at=now,
        updated_at=now,
    )
    store.departments[dept.id] = dept
