"""Idempotent sample company seed for Acme Corporation."""

from __future__ import annotations

from uuid import UUID

from app.contracts.common import utcnow
from app.database.memory import (
    BudgetRecord,
    CostCenterRecord,
    DepartmentRecord,
    EmployeeManagerLinkRecord,
    EmployeeRecord,
    MemoryStore,
    PolicyRecord,
    SupplierContactRecord,
    SupplierProductRecord,
    SupplierRecord,
    get_memory_store,
)
from app.database.seed_demo import seed_agent4_demo_process, seed_demo_processes

DEFAULT_ORG_ID = UUID("76ec608f-37a4-45fa-bb58-fb81c0710720")
DEFAULT_USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

# Stable IDs so restarts do not duplicate rows
DEPT_PROC = UUID("a76ec608-d001-4000-8000-000000000001")
DEPT_FIN = UUID("a76ec608-d001-4000-8000-000000000002")
DEPT_IT = UUID("a76ec608-d001-4000-8000-000000000003")
DEPT_OPS = UUID("a76ec608-d001-4000-8000-000000000004")
DEPT_HR = UUID("a76ec608-d001-4000-8000-000000000005")

CC_PROC = UUID("a76ec608-c001-4000-8000-000000000001")
CC_IT = UUID("a76ec608-c001-4000-8000-000000000002")
CC_OPS = UUID("a76ec608-c001-4000-8000-000000000003")

EMP_OWNER = UUID("a76ec608-e001-4000-8000-000000000001")
EMP_PROC_MGR = UUID("a76ec608-e001-4000-8000-000000000002")
EMP_BUYER = UUID("a76ec608-e001-4000-8000-000000000003")
EMP_FIN_MGR = UUID("a76ec608-e001-4000-8000-000000000004")
EMP_IT_MGR = UUID("a76ec608-e001-4000-8000-000000000005")
EMP_ANALYST = UUID("a76ec608-e001-4000-8000-000000000006")
EMP_COMPLIANCE = UUID("a76ec608-e001-4000-8000-000000000007")
EMP_OPS = UUID("a76ec608-e001-4000-8000-000000000008")

SUP_NORTHWIND = UUID("a76ec608-a001-4000-8000-000000000001")
SUP_CONTOSO = UUID("a76ec608-a001-4000-8000-000000000002")
SUP_FABRIKAM = UUID("a76ec608-a001-4000-8000-000000000003")
SUP_PENDING = UUID("a76ec608-a001-4000-8000-000000000004")
SUP_KANAKA = UUID("a76ec608-a001-4000-8000-000000000005")

POL_PROC = UUID("a76ec608-f001-4000-8000-000000000001")
POL_FIN = UUID("a76ec608-f001-4000-8000-000000000002")
POL_SEC = UUID("a76ec608-f001-4000-8000-000000000003")

BUD_PROC = UUID("a76ec608-b001-4000-8000-000000000001")
BUD_IT = UUID("a76ec608-b001-4000-8000-000000000002")


def _put(mapping: dict, record_id: UUID, record: object) -> None:
    mapping[record_id] = record


def _ensure_kanaka_supplier(
    store: MemoryStore,
    *,
    organization_id: UUID,
    now=None,
) -> None:
    """Ensure live-email demo supplier Kanaka exists (safe to call repeatedly)."""
    now = now or utcnow()
    if SUP_KANAKA not in store.suppliers:
        _put(
            store.suppliers,
            SUP_KANAKA,
            SupplierRecord(
                id=SUP_KANAKA,
                organization_id=organization_id,
                name="Kanaka",
                code="KN-05",
                status="active",
                created_at=now,
                updated_at=now,
                approval_status="approved",
                website="https://kanaka.example",
                country_code="LK",
            ),
        )
    contact_id = UUID("a76ec608-a101-4000-8000-000000000005")
    if contact_id not in store.supplier_contacts:
        _put(
            store.supplier_contacts,
            contact_id,
            SupplierContactRecord(
                id=contact_id,
                organization_id=organization_id,
                supplier_id=SUP_KANAKA,
                full_name="Avi Kanaka",
                email="kadavishkakanakasekara@gmail.com",
                is_primary=True,
                status="active",
                created_at=now,
                updated_at=now,
                role_title="Sales",
            ),
        )


def seed_sample_company(
    store: MemoryStore | None = None,
    *,
    organization_id: UUID = DEFAULT_ORG_ID,
    user_id: UUID = DEFAULT_USER_ID,
    include_process: bool = True,
) -> None:
    """Seed departments, employees, suppliers, policies, budgets for local demos."""
    store = store or get_memory_store()
    now = utcnow()

    # Idempotent: if company directory already present, still ensure Kanaka demo supplier
    if EMP_OWNER in store.employees and SUP_NORTHWIND in store.suppliers:
        if include_process:
            _ensure_kanaka_supplier(store, organization_id=organization_id, now=now)
            seed_demo_processes(store, organization_id=organization_id, user_id=user_id)
            seed_agent4_demo_process(store, organization_id=organization_id, user_id=user_id)
        return

    org = store.organizations.get(organization_id)
    if org is not None:
        org.legal_name = "Acme Corporation Inc."
        org.trading_name = "Acme"
        org.industry = "Technology / Professional Services"
        org.country_code = "US"
        org.tax_id = "US-98-7654321"
        org.default_timezone = "America/New_York"
        org.default_currency = "USD"
        org.updated_at = now
        store.organizations[organization_id] = org

    departments = [
        DepartmentRecord(
            id=DEPT_PROC,
            organization_id=organization_id,
            name="Procurement",
            code="PROC",
            status="active",
            created_at=now,
            updated_at=now,
        ),
        DepartmentRecord(
            id=DEPT_FIN,
            organization_id=organization_id,
            name="Finance",
            code="FIN",
            status="active",
            created_at=now,
            updated_at=now,
        ),
        DepartmentRecord(
            id=DEPT_IT,
            organization_id=organization_id,
            name="Information Technology",
            code="IT",
            status="active",
            created_at=now,
            updated_at=now,
        ),
        DepartmentRecord(
            id=DEPT_OPS,
            organization_id=organization_id,
            name="Operations",
            code="OPS",
            status="active",
            created_at=now,
            updated_at=now,
        ),
        DepartmentRecord(
            id=DEPT_HR,
            organization_id=organization_id,
            name="Human Resources",
            code="HR",
            status="active",
            created_at=now,
            updated_at=now,
        ),
    ]
    for dept in departments:
        _put(store.departments, dept.id, dept)

    for cc in (
        CostCenterRecord(
            id=CC_PROC,
            organization_id=organization_id,
            code="CC-PROC",
            name="Procurement Spend",
            department_id=DEPT_PROC,
            status="active",
            created_at=now,
            updated_at=now,
        ),
        CostCenterRecord(
            id=CC_IT,
            organization_id=organization_id,
            code="CC-IT",
            name="IT Hardware & SaaS",
            department_id=DEPT_IT,
            status="active",
            created_at=now,
            updated_at=now,
        ),
        CostCenterRecord(
            id=CC_OPS,
            organization_id=organization_id,
            code="CC-OPS",
            name="Facilities & Ops",
            department_id=DEPT_OPS,
            status="active",
            created_at=now,
            updated_at=now,
        ),
    ):
        _put(store.cost_centers, cc.id, cc)

    employees = [
        EmployeeRecord(
            id=EMP_OWNER,
            organization_id=organization_id,
            full_name="Alex Owner",
            email="owner@demo.bpm.local",
            title="Chief Executive Officer",
            department_id=DEPT_OPS,
            is_manager=True,
            status="active",
            created_at=now,
            updated_at=now,
            employee_code="E-001",
            role_code="owner",
            approval_authority_limit=100000.0,
        ),
        EmployeeRecord(
            id=EMP_PROC_MGR,
            organization_id=organization_id,
            full_name="Jordan Lee",
            email="jordan.lee@acme.example",
            title="Procurement Manager",
            department_id=DEPT_PROC,
            is_manager=True,
            status="active",
            created_at=now,
            updated_at=now,
            employee_code="E-010",
            role_code="manager",
            approval_authority_limit=25000.0,
        ),
        EmployeeRecord(
            id=EMP_BUYER,
            organization_id=organization_id,
            full_name="Sam Rivera",
            email="sam.rivera@acme.example",
            title="Procurement Specialist",
            department_id=DEPT_PROC,
            is_manager=False,
            status="active",
            created_at=now,
            updated_at=now,
            employee_code="E-011",
            role_code="buyer",
            approval_authority_limit=2500.0,
        ),
        EmployeeRecord(
            id=EMP_FIN_MGR,
            organization_id=organization_id,
            full_name="Casey Morgan",
            email="casey.morgan@acme.example",
            title="Finance Manager",
            department_id=DEPT_FIN,
            is_manager=True,
            status="active",
            created_at=now,
            updated_at=now,
            employee_code="E-020",
            role_code="finance",
            approval_authority_limit=50000.0,
        ),
        EmployeeRecord(
            id=EMP_IT_MGR,
            organization_id=organization_id,
            full_name="Taylor Kim",
            email="taylor.kim@acme.example",
            title="IT Manager",
            department_id=DEPT_IT,
            is_manager=True,
            status="active",
            created_at=now,
            updated_at=now,
            employee_code="E-030",
            role_code="manager",
            approval_authority_limit=15000.0,
        ),
        EmployeeRecord(
            id=EMP_ANALYST,
            organization_id=organization_id,
            full_name="Riley Chen",
            email="riley.chen@acme.example",
            title="Business Analyst",
            department_id=DEPT_OPS,
            is_manager=False,
            status="active",
            created_at=now,
            updated_at=now,
            employee_code="E-040",
            role_code="analyst",
            approval_authority_limit=500.0,
        ),
        EmployeeRecord(
            id=EMP_COMPLIANCE,
            organization_id=organization_id,
            full_name="Avery Brooks",
            email="avery.brooks@acme.example",
            title="Compliance Officer",
            department_id=DEPT_FIN,
            is_manager=False,
            status="active",
            created_at=now,
            updated_at=now,
            employee_code="E-021",
            role_code="compliance",
            approval_authority_limit=0.0,
        ),
        EmployeeRecord(
            id=EMP_OPS,
            organization_id=organization_id,
            full_name="Morgan Patel",
            email="morgan.patel@acme.example",
            title="Operations Coordinator",
            department_id=DEPT_OPS,
            is_manager=False,
            status="active",
            created_at=now,
            updated_at=now,
            employee_code="E-041",
            role_code="employee",
            approval_authority_limit=1000.0,
        ),
    ]
    for emp in employees:
        _put(store.employees, emp.id, emp)

    store.departments[DEPT_PROC].manager_employee_id = EMP_PROC_MGR
    store.departments[DEPT_FIN].manager_employee_id = EMP_FIN_MGR
    store.departments[DEPT_IT].manager_employee_id = EMP_IT_MGR
    store.departments[DEPT_OPS].manager_employee_id = EMP_OWNER
    # Re-assign to trigger persist wrappers if present
    for dept_id in (DEPT_PROC, DEPT_FIN, DEPT_IT, DEPT_OPS):
        store.departments[dept_id] = store.departments[dept_id]

    links = [
        (EMP_BUYER, EMP_PROC_MGR),
        (EMP_PROC_MGR, EMP_OWNER),
        (EMP_FIN_MGR, EMP_OWNER),
        (EMP_IT_MGR, EMP_OWNER),
        (EMP_ANALYST, EMP_OWNER),
        (EMP_COMPLIANCE, EMP_FIN_MGR),
        (EMP_OPS, EMP_OWNER),
    ]
    for idx, (employee_id, manager_id) in enumerate(links, start=1):
        link_id = UUID(f"a76ec608-a301-4000-8000-{idx:012d}")
        _put(
            store.employee_manager_links,
            link_id,
            EmployeeManagerLinkRecord(
                id=link_id,
                organization_id=organization_id,
                employee_id=employee_id,
                manager_employee_id=manager_id,
                link_type="direct",
                status="active",
                created_at=now,
                updated_at=now,
            ),
        )

    suppliers = [
        SupplierRecord(
            id=SUP_NORTHWIND,
            organization_id=organization_id,
            name="Northwind Supplies",
            code="NW-01",
            status="active",
            created_at=now,
            updated_at=now,
            approval_status="approved",
            website="https://northwind.example",
            country_code="US",
        ),
        SupplierRecord(
            id=SUP_CONTOSO,
            organization_id=organization_id,
            name="Contoso Components",
            code="CC-02",
            status="active",
            created_at=now,
            updated_at=now,
            approval_status="approved",
            website="https://contoso.example",
            country_code="US",
        ),
        SupplierRecord(
            id=SUP_FABRIKAM,
            organization_id=organization_id,
            name="Fabrikam IT Services",
            code="FK-03",
            status="active",
            created_at=now,
            updated_at=now,
            approval_status="approved",
            website="https://fabrikam.example",
            country_code="GB",
        ),
        SupplierRecord(
            id=SUP_PENDING,
            organization_id=organization_id,
            name="TechSupply Co",
            code="TS-04",
            status="active",
            created_at=now,
            updated_at=now,
            approval_status="pending",
            website="https://techsupply.example",
            country_code="US",
        ),
        SupplierRecord(
            id=SUP_KANAKA,
            organization_id=organization_id,
            name="Kanaka",
            code="KN-05",
            status="active",
            created_at=now,
            updated_at=now,
            approval_status="approved",
            website="https://kanaka.example",
            country_code="LK",
        ),
    ]
    for supplier in suppliers:
        _put(store.suppliers, supplier.id, supplier)

    contacts = [
        (
            UUID("a76ec608-a101-4000-8000-000000000001"),
            SUP_NORTHWIND,
            "Casey Contact",
            "casey@northwind.example",
            "Account Manager",
        ),
        (
            UUID("a76ec608-a101-4000-8000-000000000002"),
            SUP_CONTOSO,
            "Dana Sales",
            "dana@contoso.example",
            "Sales Lead",
        ),
        (
            UUID("a76ec608-a101-4000-8000-000000000003"),
            SUP_FABRIKAM,
            "Ellis Support",
            "ellis@fabrikam.example",
            "Customer Success",
        ),
        (
            UUID("a76ec608-a101-4000-8000-000000000004"),
            SUP_PENDING,
            "Quinn Onboarding",
            "quinn@techsupply.example",
            "Partnerships",
        ),
        (
            UUID("a76ec608-a101-4000-8000-000000000005"),
            SUP_KANAKA,
            "Avi Kanaka",
            "kadavishkakanakasekara@gmail.com",
            "Sales",
        ),
    ]
    for contact_id, supplier_id, name, email, role in contacts:
        _put(
            store.supplier_contacts,
            contact_id,
            SupplierContactRecord(
                id=contact_id,
                organization_id=organization_id,
                supplier_id=supplier_id,
                full_name=name,
                email=email,
                is_primary=True,
                status="active",
                created_at=now,
                updated_at=now,
                role_title=role,
            ),
        )

    products = [
        (
            UUID("a76ec608-a201-4000-8000-000000000001"),
            SUP_NORTHWIND,
            "NW-LAP-14",
            "14-inch Business Laptop",
            1199.0,
            "each",
        ),
        (
            UUID("a76ec608-a201-4000-8000-000000000002"),
            SUP_NORTHWIND,
            "NW-MON-27",
            "27-inch Monitor",
            349.0,
            "each",
        ),
        (
            UUID("a76ec608-a201-4000-8000-000000000003"),
            SUP_CONTOSO,
            "CC-DOCK-01",
            "USB-C Docking Station",
            189.0,
            "each",
        ),
        (
            UUID("a76ec608-a201-4000-8000-000000000004"),
            SUP_FABRIKAM,
            "FK-CLOUD-M",
            "Managed Cloud Support (monthly)",
            2500.0,
            "month",
        ),
    ]
    for product_id, supplier_id, sku, name, price, uom in products:
        _put(
            store.supplier_products,
            product_id,
            SupplierProductRecord(
                id=product_id,
                organization_id=organization_id,
                supplier_id=supplier_id,
                name=name,
                sku=sku,
                unit_price=price,
                currency_code="USD",
                status="active",
                created_at=now,
                updated_at=now,
                unit_of_measure=uom,
            ),
        )

    for policy in (
        PolicyRecord(
            id=POL_PROC,
            organization_id=organization_id,
            code="PROC-001",
            title="Procurement Approval Policy",
            status="active",
            created_at=now,
            updated_at=now,
            category="procurement",
            description=(
                "Purchases above $2,500 require manager approval. "
                "Purchases above $10,000 require dual quotes from approved suppliers. "
                "Purchases above $25,000 require finance approval."
            ),
            owner_employee_id=EMP_PROC_MGR,
        ),
        PolicyRecord(
            id=POL_FIN,
            organization_id=organization_id,
            code="FIN-001",
            title="Spend Authority Policy",
            status="active",
            created_at=now,
            updated_at=now,
            category="finance",
            description="Employees may only approve spend within their authority limit.",
            owner_employee_id=EMP_FIN_MGR,
        ),
        PolicyRecord(
            id=POL_SEC,
            organization_id=organization_id,
            code="SEC-200",
            title="Vendor Security Review",
            status="active",
            created_at=now,
            updated_at=now,
            category="security",
            description="New IT vendors require a completed security questionnaire before approval.",
            owner_employee_id=EMP_COMPLIANCE,
        ),
    ):
        _put(store.policies, policy.id, policy)

    for budget in (
        BudgetRecord(
            id=BUD_PROC,
            organization_id=organization_id,
            name="FY2026 Procurement Budget",
            fiscal_year=2026,
            amount_total=250000.0,
            currency_code="USD",
            status="active",
            created_at=now,
            updated_at=now,
            department_id=DEPT_PROC,
            cost_center_id=CC_PROC,
        ),
        BudgetRecord(
            id=BUD_IT,
            organization_id=organization_id,
            name="FY2026 IT Hardware Budget",
            fiscal_year=2026,
            amount_total=120000.0,
            currency_code="USD",
            status="active",
            created_at=now,
            updated_at=now,
            department_id=DEPT_IT,
            cost_center_id=CC_IT,
        ),
    ):
        _put(store.budgets, budget.id, budget)

    if include_process:
        seed_demo_processes(store, organization_id=organization_id, user_id=user_id)
        seed_agent4_demo_process(store, organization_id=organization_id, user_id=user_id)
