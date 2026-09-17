"""Repositories backed by the in-memory store (foundation persistence)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from app.contracts.common import utcnow
from app.database.memory import (
    ApprovalRecord,
    AuditEventRecord,
    BudgetRecord,
    CostCenterRecord,
    DepartmentRecord,
    DocumentChunkRecord,
    DocumentRecord,
    EmployeeManagerLinkRecord,
    EmployeeRecord,
    IdempotencyRecord,
    MembershipRecord,
    MemoryStore,
    OrganizationRecord,
    PolicyRecord,
    ProcessDefinitionRecord,
    ProcessRunRecord,
    ProcessVersionRecord,
    SupplierContactRecord,
    SupplierProductRecord,
    SupplierRecord,
    get_memory_store,
    new_id,
)
from app.domain.enums import (
    ApprovalStatus,
    DocumentStatus,
    MembershipStatus,
    OrgRole,
    ProcessRunStatus,
)
from app.repositories.base import TenantScopedRepository
from app.security.errors import ConflictError, NotFoundError, ValidationAppError


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "organization"


class OrganizationRepository:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or get_memory_store()

    def list_for_user(self, user_id: UUID) -> list[tuple[OrganizationRecord, MembershipRecord]]:
        with self.store.lock:
            memberships = [
                m
                for m in self.store.memberships.values()
                if m.user_id == user_id and m.status == MembershipStatus.ACTIVE
            ]
            result: list[tuple[OrganizationRecord, MembershipRecord]] = []
            for membership in memberships:
                org = self.store.organizations.get(membership.organization_id)
                if org is not None:
                    result.append((org, membership))
            return result

    def get(self, organization_id: UUID) -> OrganizationRecord | None:
        return self.store.organizations.get(organization_id)

    def create(self, *, name: str, plan_code: str, owner_user_id: UUID) -> OrganizationRecord:
        with self.store.lock:
            now = utcnow()
            org_id = new_id()
            slug = _slugify(name)
            existing_slugs = {o.slug for o in self.store.organizations.values()}
            base = slug
            i = 1
            while slug in existing_slugs:
                slug = f"{base}-{i}"
                i += 1
            org = OrganizationRecord(
                id=org_id,
                name=name,
                slug=slug,
                plan_code=plan_code,
                status="active",
                row_version=1,
                created_at=now,
                updated_at=now,
            )
            membership = MembershipRecord(
                id=new_id(),
                organization_id=org_id,
                user_id=owner_user_id,
                role=OrgRole.OWNER,
                status=MembershipStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            self.store.organizations[org_id] = org
            self.store.memberships[membership.id] = membership
        # Seed subscription outside lock to avoid nested entitlement store contention
        from app.billing.service import EntitlementService

        EntitlementService().ensure_subscription(org_id, plan_code=plan_code)
        return org

    def update(
        self,
        organization_id: UUID,
        *,
        name: str | None = None,
        plan_code: str | None = None,
        expected_row_version: int | None = None,
    ) -> OrganizationRecord:
        with self.store.lock:
            org = self.store.organizations.get(organization_id)
            if org is None:
                raise NotFoundError("Organization not found")
            if expected_row_version is not None and org.row_version != expected_row_version:
                raise ConflictError(
                    "Organization version conflict",
                    code="PROCESS_VERSION_CONFLICT",
                    details={"row_version": org.row_version},
                )
            if name is not None:
                org.name = name
            if plan_code is not None:
                org.plan_code = plan_code
            org.row_version += 1
            org.updated_at = utcnow()
            return org

    def update_profile(self, organization_id: UUID, **fields: Any) -> OrganizationRecord:
        with self.store.lock:
            org = self.store.organizations.get(organization_id)
            if org is None:
                raise NotFoundError("Organization not found")
            allowed = {
                "name",
                "legal_name",
                "trading_name",
                "industry",
                "country_code",
                "tax_id",
                "tax_registration",
                "tax_country_code",
                "default_timezone",
                "default_currency",
                "tax_information",
                "plan_code",
            }
            for key, value in fields.items():
                if key in allowed and value is not None:
                    setattr(org, key, value)
            org.row_version += 1
            org.updated_at = utcnow()
            return org


class MembershipRepository:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or get_memory_store()

    def get_active(self, organization_id: UUID, user_id: UUID) -> MembershipRecord | None:
        for membership in self.store.memberships.values():
            if (
                membership.organization_id == organization_id
                and membership.user_id == user_id
                and membership.status == MembershipStatus.ACTIVE
            ):
                return membership
        return None


class TenantRepository(TenantScopedRepository):
    def __init__(self, organization_id: UUID, store: MemoryStore | None = None) -> None:
        super().__init__(organization_id)
        self.store = store or get_memory_store()


class EmployeeRepository(TenantRepository):
    def list_all(self) -> list[EmployeeRecord]:
        return [
            e
            for e in self.store.employees.values()
            if e.organization_id == self.organization_id
        ]

    def list_managers(self) -> list[EmployeeRecord]:
        return [e for e in self.list_all() if e.is_manager and e.status == "active"]

    def assert_no_active_email_duplicate(
        self, email: str, *, exclude_id: UUID | None = None
    ) -> None:
        for employee in self.list_all():
            if employee.status != "active":
                continue
            if exclude_id is not None and employee.id == exclude_id:
                continue
            if employee.email.lower() == email.lower():
                raise ConflictError(
                    "Active employee with this email already exists in the organization",
                    code="DUPLICATE_EMPLOYEE_EMAIL",
                    details={"email": email},
                )

    def create(self, **kwargs: Any) -> EmployeeRecord:
        now = utcnow()
        record = EmployeeRecord(
            id=new_id(),
            organization_id=self.organization_id,
            created_at=now,
            updated_at=now,
            status=kwargs.get("status", "active"),
            is_manager=bool(kwargs.get("is_manager", False)),
            full_name=kwargs["full_name"],
            email=kwargs["email"],
            title=kwargs.get("title"),
            department_id=kwargs.get("department_id"),
            employee_code=kwargs.get("employee_code"),
            role_code=kwargs.get("role_code"),
            approval_authority_limit=kwargs.get("approval_authority_limit"),
            approval_authority_currency=kwargs.get("approval_authority_currency", "USD"),
        )
        self.store.employees[record.id] = record
        return record

    def get(self, employee_id: UUID) -> EmployeeRecord:
        record = self.store.employees.get(employee_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Employee not found",
        )

    def update(self, employee_id: UUID, **fields: Any) -> EmployeeRecord:
        record = self.get(employee_id)
        allowed = {
            "full_name",
            "email",
            "title",
            "department_id",
            "is_manager",
            "status",
            "employee_code",
            "role_code",
            "approval_authority_limit",
            "approval_authority_currency",
        }
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record


class EmployeeManagerLinkRepository(TenantRepository):
    def list_all(self) -> list[EmployeeManagerLinkRecord]:
        return [
            link
            for link in self.store.employee_manager_links.values()
            if link.organization_id == self.organization_id
        ]

    def list_for_employee(self, employee_id: UUID) -> list[EmployeeManagerLinkRecord]:
        return [link for link in self.list_all() if link.employee_id == employee_id]

    def create(
        self,
        *,
        employee_id: UUID,
        manager_employee_id: UUID,
        link_type: str = "direct",
    ) -> EmployeeManagerLinkRecord:
        now = utcnow()
        record = EmployeeManagerLinkRecord(
            id=new_id(),
            organization_id=self.organization_id,
            employee_id=employee_id,
            manager_employee_id=manager_employee_id,
            link_type=link_type,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self.store.employee_manager_links[record.id] = record
        return record

    def update(self, link_id: UUID, **fields: Any) -> EmployeeManagerLinkRecord:
        record = self.store.employee_manager_links.get(link_id)
        record = self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Manager link not found",
        )
        for key, value in fields.items():
            if key in {"status", "link_type"} and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record


class DepartmentRepository(TenantRepository):
    def list_all(self) -> list[DepartmentRecord]:
        return [
            d
            for d in self.store.departments.values()
            if d.organization_id == self.organization_id
        ]

    def get(self, department_id: UUID) -> DepartmentRecord:
        record = self.store.departments.get(department_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Department not found",
        )

    def create(
        self,
        *,
        name: str,
        code: str | None = None,
        parent_department_id: UUID | None = None,
        manager_employee_id: UUID | None = None,
    ) -> DepartmentRecord:
        now = utcnow()
        record = DepartmentRecord(
            id=new_id(),
            organization_id=self.organization_id,
            name=name,
            code=code,
            status="active",
            parent_department_id=parent_department_id,
            manager_employee_id=manager_employee_id,
            created_at=now,
            updated_at=now,
        )
        self.store.departments[record.id] = record
        return record

    def update(self, department_id: UUID, **fields: Any) -> DepartmentRecord:
        record = self.get(department_id)
        for key, value in fields.items():
            if key in {
                "name",
                "code",
                "status",
                "parent_department_id",
                "manager_employee_id",
            } and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record


class CostCenterRepository(TenantRepository):
    def list_all(self) -> list[CostCenterRecord]:
        return [
            c
            for c in self.store.cost_centers.values()
            if c.organization_id == self.organization_id
        ]

    def get(self, cost_center_id: UUID) -> CostCenterRecord:
        record = self.store.cost_centers.get(cost_center_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Cost center not found",
        )

    def create(
        self,
        *,
        code: str,
        name: str,
        department_id: UUID | None = None,
    ) -> CostCenterRecord:
        now = utcnow()
        record = CostCenterRecord(
            id=new_id(),
            organization_id=self.organization_id,
            code=code,
            name=name,
            department_id=department_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self.store.cost_centers[record.id] = record
        return record

    def update(self, cost_center_id: UUID, **fields: Any) -> CostCenterRecord:
        record = self.get(cost_center_id)
        for key, value in fields.items():
            if key in {"code", "name", "department_id", "status"} and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record


class SupplierRepository(TenantRepository):
    def list_all(self) -> list[SupplierRecord]:
        return [
            s
            for s in self.store.suppliers.values()
            if s.organization_id == self.organization_id
        ]

    def create(
        self,
        *,
        name: str,
        code: str | None = None,
        website: str | None = None,
        country_code: str | None = None,
        approval_status: str = "pending",
        status: str = "active",
    ) -> SupplierRecord:
        now = utcnow()
        record = SupplierRecord(
            id=new_id(),
            organization_id=self.organization_id,
            name=name,
            code=code,
            status=status,
            approval_status=approval_status,
            website=website,
            country_code=country_code,
            created_at=now,
            updated_at=now,
        )
        self.store.suppliers[record.id] = record
        return record

    def get(self, supplier_id: UUID) -> SupplierRecord:
        record = self.store.suppliers.get(supplier_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Supplier not found",
        )

    def update(self, supplier_id: UUID, **fields: Any) -> SupplierRecord:
        record = self.get(supplier_id)
        for key, value in fields.items():
            if key in {
                "name",
                "code",
                "status",
                "approval_status",
                "website",
                "country_code",
            } and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record


class SupplierContactRepository(TenantRepository):
    def list_all(self, supplier_id: UUID | None = None) -> list[SupplierContactRecord]:
        contacts = [
            c
            for c in self.store.supplier_contacts.values()
            if c.organization_id == self.organization_id
        ]
        if supplier_id is not None:
            contacts = [c for c in contacts if c.supplier_id == supplier_id]
        return contacts

    def assert_no_active_email_duplicate(
        self,
        supplier_id: UUID,
        email: str,
        *,
        allow_duplicate: bool,
        exclude_id: UUID | None = None,
    ) -> None:
        if allow_duplicate:
            return
        for contact in self.list_all(supplier_id):
            if contact.status != "active" or not contact.email:
                continue
            if exclude_id is not None and contact.id == exclude_id:
                continue
            if contact.email.lower() == email.lower() and not contact.allow_duplicate_email:
                raise ConflictError(
                    "Active supplier contact with this email already exists for the supplier",
                    code="DUPLICATE_SUPPLIER_CONTACT_EMAIL",
                    details={"email": email, "supplier_id": str(supplier_id)},
                )

    def create(
        self,
        *,
        supplier_id: UUID,
        full_name: str,
        email: str | None = None,
        is_primary: bool = False,
        phone: str | None = None,
        role_title: str | None = None,
        allow_duplicate_email: bool = False,
    ) -> SupplierContactRecord:
        SupplierRepository(self.organization_id, self.store).get(supplier_id)
        now = utcnow()
        record = SupplierContactRecord(
            id=new_id(),
            organization_id=self.organization_id,
            supplier_id=supplier_id,
            full_name=full_name,
            email=email,
            is_primary=is_primary,
            status="active",
            phone=phone,
            role_title=role_title,
            allow_duplicate_email=allow_duplicate_email,
            created_at=now,
            updated_at=now,
        )
        self.store.supplier_contacts[record.id] = record
        return record

    def get(self, contact_id: UUID) -> SupplierContactRecord:
        record = self.store.supplier_contacts.get(contact_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Supplier contact not found",
        )

    def update(self, contact_id: UUID, **fields: Any) -> SupplierContactRecord:
        record = self.get(contact_id)
        for key, value in fields.items():
            if key in {
                "full_name",
                "email",
                "is_primary",
                "status",
                "phone",
                "role_title",
                "allow_duplicate_email",
            } and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record


class SupplierProductRepository(TenantRepository):
    def list_all(self, supplier_id: UUID | None = None) -> list[SupplierProductRecord]:
        products = [
            p
            for p in self.store.supplier_products.values()
            if p.organization_id == self.organization_id
        ]
        if supplier_id is not None:
            products = [p for p in products if p.supplier_id == supplier_id]
        return products

    def create(
        self,
        *,
        supplier_id: UUID,
        name: str,
        sku: str | None = None,
        unit_price: float | None = None,
        currency_code: str = "USD",
        description: str | None = None,
        unit_of_measure: str | None = None,
    ) -> SupplierProductRecord:
        SupplierRepository(self.organization_id, self.store).get(supplier_id)
        now = utcnow()
        record = SupplierProductRecord(
            id=new_id(),
            organization_id=self.organization_id,
            supplier_id=supplier_id,
            name=name,
            sku=sku,
            unit_price=unit_price,
            currency_code=currency_code,
            status="active",
            description=description,
            unit_of_measure=unit_of_measure,
            created_at=now,
            updated_at=now,
        )
        self.store.supplier_products[record.id] = record
        return record

    def get(self, product_id: UUID) -> SupplierProductRecord:
        record = self.store.supplier_products.get(product_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Supplier product not found",
        )

    def update(self, product_id: UUID, **fields: Any) -> SupplierProductRecord:
        record = self.get(product_id)
        for key, value in fields.items():
            if key in {
                "name",
                "sku",
                "unit_price",
                "currency_code",
                "status",
                "description",
                "unit_of_measure",
            } and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record


class BudgetRepository(TenantRepository):
    def list_all(self) -> list[BudgetRecord]:
        return [
            b
            for b in self.store.budgets.values()
            if b.organization_id == self.organization_id
        ]

    def get(self, budget_id: UUID) -> BudgetRecord:
        record = self.store.budgets.get(budget_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Budget not found",
        )

    def create(
        self,
        *,
        name: str,
        fiscal_year: int,
        amount_total: float,
        currency_code: str = "USD",
        department_id: UUID | None = None,
        cost_center_id: UUID | None = None,
    ) -> BudgetRecord:
        now = utcnow()
        record = BudgetRecord(
            id=new_id(),
            organization_id=self.organization_id,
            name=name,
            fiscal_year=fiscal_year,
            amount_total=amount_total,
            currency_code=currency_code,
            status="active",
            department_id=department_id,
            cost_center_id=cost_center_id,
            created_at=now,
            updated_at=now,
        )
        self.store.budgets[record.id] = record
        return record

    def update(self, budget_id: UUID, **fields: Any) -> BudgetRecord:
        record = self.get(budget_id)
        for key, value in fields.items():
            if key in {
                "name",
                "fiscal_year",
                "amount_total",
                "currency_code",
                "status",
                "department_id",
                "cost_center_id",
            } and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record


class PolicyRepository(TenantRepository):
    def list_all(self) -> list[PolicyRecord]:
        return [
            p
            for p in self.store.policies.values()
            if p.organization_id == self.organization_id
        ]

    def get(self, policy_id: UUID) -> PolicyRecord:
        record = self.store.policies.get(policy_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Policy not found",
        )

    def create(
        self,
        *,
        code: str,
        title: str,
        category: str | None = None,
        description: str | None = None,
        owner_employee_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PolicyRecord:
        now = utcnow()
        record = PolicyRecord(
            id=new_id(),
            organization_id=self.organization_id,
            code=code,
            title=title,
            status="draft",
            category=category,
            description=description,
            owner_employee_id=owner_employee_id,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self.store.policies[record.id] = record
        return record

    def update(self, policy_id: UUID, **fields: Any) -> PolicyRecord:
        record = self.get(policy_id)
        for key, value in fields.items():
            if key in {
                "code",
                "title",
                "status",
                "category",
                "description",
                "owner_employee_id",
                "metadata",
            } and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record


class DocumentRepository(TenantRepository):
    def list_all(self) -> list[DocumentRecord]:
        return [
            d
            for d in self.store.documents.values()
            if d.organization_id == self.organization_id
        ]

    def get(self, document_id: UUID) -> DocumentRecord:
        record = self.store.documents.get(document_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Document not found",
        )

    def create(
        self,
        *,
        title: str,
        storage_path: str,
        uploaded_by_user_id: UUID | None,
        file_name: str | None = None,
        mime_type: str | None = None,
        byte_size: int | None = None,
        content_hash: str | None = None,
        source_type: str = "upload",
        classification: str = "internal",
        access_scope: str = "organization",
        document_type: str = "general",
    ) -> DocumentRecord:
        if not storage_path.startswith(f"{self.organization_id}/"):
            raise ValidationAppError(
                "storage_path must be prefixed with the authenticated organization_id"
            )
        now = utcnow()
        record = DocumentRecord(
            id=new_id(),
            organization_id=self.organization_id,
            title=title,
            storage_path=storage_path,
            status=DocumentStatus.UPLOADED,
            uploaded_by_user_id=uploaded_by_user_id,
            created_at=now,
            updated_at=now,
            file_name=file_name or title,
            mime_type=mime_type,
            byte_size=byte_size,
            content_hash=content_hash,
            source_type=source_type,
            classification=classification,
            access_scope=access_scope,
            document_type=document_type,
            owner_user_id=uploaded_by_user_id,
            created_by_user_id=uploaded_by_user_id,
        )
        self.store.documents[record.id] = record
        return record

    def update(self, document_id: UUID, **fields: Any) -> DocumentRecord:
        record = self.get(document_id)
        for key, value in fields.items():
            if hasattr(record, key) and value is not None:
                setattr(record, key, value)
        record.updated_at = utcnow()
        return record

    def delete(self, document_id: UUID) -> None:
        record = self.get(document_id)
        for chunk_id, chunk in list(self.store.document_chunks.items()):
            if chunk.document_id == record.id:
                del self.store.document_chunks[chunk_id]
        del self.store.documents[record.id]

    def list_chunks(self, document_id: UUID) -> list[DocumentChunkRecord]:
        self.get(document_id)
        return [
            c
            for c in self.store.document_chunks.values()
            if c.organization_id == self.organization_id and c.document_id == document_id
        ]


class ProcessRepository(TenantRepository):
    def list_all(self) -> list[ProcessDefinitionRecord]:
        return [
            p
            for p in self.store.processes.values()
            if p.organization_id == self.organization_id
        ]

    def get(self, process_id: UUID) -> ProcessDefinitionRecord:
        record = self.store.processes.get(process_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Process not found",
        )

    def create(
        self,
        *,
        name: str,
        description: str | None,
        created_by_user_id: UUID | None,
    ) -> ProcessDefinitionRecord:
        now = utcnow()
        record = ProcessDefinitionRecord(
            id=new_id(),
            organization_id=self.organization_id,
            name=name,
            description=description,
            status="draft",
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        self.store.processes[record.id] = record
        return record

    def list_versions(self, process_id: UUID) -> list[ProcessVersionRecord]:
        self.get(process_id)
        return [
            v
            for v in self.store.process_versions.values()
            if v.organization_id == self.organization_id and v.process_id == process_id
        ]

    def create_version(
        self,
        process_id: UUID,
        *,
        plan_snapshot: dict[str, Any],
        parent_version_id: UUID | None = None,
        status: str = "ready",
    ) -> ProcessVersionRecord:
        self.get(process_id)
        versions = self.list_versions(process_id)
        version_number = max((v.version_number for v in versions), default=0) + 1
        snapshot_hash = hashlib.sha256(
            json.dumps(plan_snapshot, sort_keys=True, default=str).encode()
        ).hexdigest()
        now = utcnow()
        record = ProcessVersionRecord(
            id=new_id(),
            organization_id=self.organization_id,
            process_id=process_id,
            version_number=version_number,
            plan_snapshot=plan_snapshot,
            plan_snapshot_hash=snapshot_hash,
            status=status,
            created_at=now,
            updated_at=now,
            parent_version_id=parent_version_id,
        )
        self.store.process_versions[record.id] = record
        return record

    def get_version(self, process_id: UUID, version_id: UUID) -> ProcessVersionRecord:
        self.get(process_id)
        record = self.store.process_versions.get(version_id)
        if record is None or record.process_id != process_id:
            return self.require(
                None,
                record_organization_id=None,
                message="Process version not found",
            )
        return self.require(
            record,
            record_organization_id=record.organization_id,
            message="Process version not found",
        )

    def confirm_version(
        self,
        process_id: UUID,
        version_id: UUID,
        *,
        confirmed_by_user_id: UUID,
    ) -> ProcessVersionRecord:
        record = self.get_version(process_id, version_id)
        now = utcnow()
        record.status = "confirmed"
        record.confirmed_at = now
        record.confirmed_by_user_id = confirmed_by_user_id
        record.is_immutable = True
        record.updated_at = now
        from app.config import get_settings
        from app.database.postgres_persistence import persist_mutation

        if get_settings().persistence_mode == "postgres":
            persist_mutation(self.store, "process_versions", record.id)
        return record

    def set_status(self, process_id: UUID, status: str) -> ProcessDefinitionRecord:
        record = self.get(process_id)
        record.status = status
        record.updated_at = utcnow()
        from app.config import get_settings
        from app.database.postgres_persistence import persist_mutation

        if get_settings().persistence_mode == "postgres":
            persist_mutation(self.store, "processes", record.id)
        return record


class ApprovalRepository(TenantRepository):
    def list_all(self) -> list[ApprovalRecord]:
        return [
            a
            for a in self.store.approvals.values()
            if a.organization_id == self.organization_id
        ]

    def get(self, approval_id: UUID) -> ApprovalRecord:
        record = self.store.approvals.get(approval_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Approval not found",
        )

    def decide(
        self,
        approval_id: UUID,
        *,
        decision: str,
        decided_by_user_id: UUID,
        note: str | None,
        expected_row_version: int,
    ) -> ApprovalRecord:
        record = self.get(approval_id)
        if record.row_version != expected_row_version:
            raise ConflictError(
                "Approval version conflict",
                code="APPROVAL_VERSION_CONFLICT",
                details={"row_version": record.row_version},
            )
        if record.status != ApprovalStatus.PENDING:
            raise ConflictError("Approval is not pending", code="APPROVAL_INVALIDATED")
        if decision not in {"approved", "rejected"}:
            raise ValidationAppError("decision must be approved or rejected")
        if (
            decision == "approved"
            and record.prohibited_action
            and not record.override_required
        ):
            raise ValidationAppError(
                "Users cannot approve prohibited actions unless explicitly authorized"
            )
        # Override packages are allowed when override_required is set (audited workflow)
        record.status = ApprovalStatus(decision)
        record.decided_by_user_id = decided_by_user_id
        record.decision_note = note
        record.row_version += 1
        record.updated_at = utcnow()
        from app.config import get_settings
        from app.database.postgres_persistence import persist_mutation

        if get_settings().persistence_mode == "postgres":
            persist_mutation(self.store, "approvals", record.id)
        return record


class ProcessRunRepository(TenantRepository):
    def list_all(self) -> list[ProcessRunRecord]:
        return [
            r
            for r in self.store.process_runs.values()
            if r.organization_id == self.organization_id
        ]

    def get(self, run_id: UUID) -> ProcessRunRecord:
        record = self.store.process_runs.get(run_id)
        return self.require(
            record,
            record_organization_id=getattr(record, "organization_id", None),
            message="Process run not found",
        )

    def create(
        self,
        *,
        process_id: UUID,
        process_version_id: UUID | None,
        initiated_by_user_id: UUID | None,
        correlation_id: str | None,
    ) -> ProcessRunRecord:
        ProcessRepository(self.organization_id, self.store).get(process_id)
        now = utcnow()
        record = ProcessRunRecord(
            id=new_id(),
            organization_id=self.organization_id,
            process_id=process_id,
            process_version_id=process_version_id,
            status=ProcessRunStatus.DRAFT,
            initiated_by_user_id=initiated_by_user_id,
            correlation_id=correlation_id,
            created_at=now,
            updated_at=now,
        )
        self.store.process_runs[record.id] = record
        self.store.run_events.setdefault(record.id, []).append(
            {
                "type": "run.created",
                "at": now.isoformat(),
                "status": record.status.value,
            }
        )
        return record

    def set_status(self, run_id: UUID, status: ProcessRunStatus) -> ProcessRunRecord:
        record = self.get(run_id)
        record.status = status
        record.updated_at = utcnow()
        from app.config import get_settings
        from app.database.postgres_persistence import persist_mutation

        if get_settings().persistence_mode == "postgres":
            persist_mutation(self.store, "process_runs", record.id)
        self.store.run_events.setdefault(record.id, []).append(
            {
                "type": "run.status_changed",
                "at": record.updated_at.isoformat(),
                "status": status.value,
            }
        )
        return record

    def events(self, run_id: UUID) -> list[dict[str, Any]]:
        self.get(run_id)
        return list(self.store.run_events.get(run_id, []))


class AuditRepository:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or get_memory_store()

    def append(
        self,
        *,
        organization_id: UUID,
        actor_user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        correlation_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEventRecord:
        event = AuditEventRecord(
            id=new_id(),
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            payload=payload or {},
            created_at=utcnow(),
        )
        self.store.audit_events.append(event)
        return event

    def list_for_org(self, organization_id: UUID) -> list[AuditEventRecord]:
        return [e for e in self.store.audit_events if e.organization_id == organization_id]


class IdempotencyRepository:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or get_memory_store()

    def get(
        self, organization_id: UUID, scope: str, key: str
    ) -> IdempotencyRecord | None:
        return self.store.idempotency.get((organization_id, scope, key))

    def begin(
        self,
        *,
        organization_id: UUID,
        scope: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyRecord:
        existing = self.get(organization_id, scope, key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError(
                    "Idempotency key reused with different payload",
                    code="IDEMPOTENCY_CONFLICT",
                )
            return existing
        now = utcnow()
        record = IdempotencyRecord(
            organization_id=organization_id,
            scope=scope,
            key=key,
            request_hash=request_hash,
            status="in_progress",
            response_status=None,
            response_body=None,
            created_at=now,
            updated_at=now,
        )
        self.store.idempotency[(organization_id, scope, key)] = record
        return record

    def complete(
        self,
        *,
        organization_id: UUID,
        scope: str,
        key: str,
        response_status: int,
        response_body: dict[str, Any],
    ) -> IdempotencyRecord:
        record = self.get(organization_id, scope, key)
        if record is None:
            raise NotFoundError("Idempotency record not found")
        record.status = "completed"
        record.response_status = response_status
        record.response_body = response_body
        record.updated_at = utcnow()
        return record
