"""Organization directory and commercial data endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.auth.deps import (
    OrganizationContext,
    get_current_user,
    ignore_client_organization_id,
    require_permission,
)
from app.contracts.common import Page
from app.contracts.schemas import (
    BudgetCreate,
    BudgetResponse,
    BudgetUpdate,
    CostCenterCreate,
    CostCenterResponse,
    CostCenterUpdate,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
    ManagerLinkCreate,
    ManagerLinkResponse,
    PolicyCreate,
    PolicyResponse,
    PolicyUpdate,
    RoleCatalogItem,
    SupplierContactCreate,
    SupplierContactResponse,
    SupplierCreate,
    SupplierProductCreate,
    SupplierProductResponse,
    SupplierResponse,
    SupplierUpdate,
)
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.repositories.query import ListParams, apply_list, list_params
from app.security.jwt import AuthenticatedUser
from app.services.org_management import (
    ORG_ROLE_CATALOG,
    BudgetService,
    CostCenterService,
    DepartmentService,
    EmployeeService,
    PolicyService,
    SupplierService,
)

router = APIRouter(tags=["organization-data"])


def _employee_page(
    items: list,
    params: ListParams,
) -> Page[EmployeeResponse]:
    page = apply_list(
        items,
        params,
        search_fields=[lambda e: e.full_name, lambda e: e.email, lambda e: e.role_code or ""],
        status_getter=lambda e: e.status,
        sort_fields={"name": lambda e: e.full_name, "created_at": lambda e: e.created_at},
    )
    return Page(
        items=[EmployeeResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )


@router.get("/employees", response_model=Page[EmployeeResponse])
async def list_employees(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[EmployeeResponse]:
    return _employee_page(EmployeeService(org.organization_id).list_all(), params)


@router.post("/employees", response_model=EmployeeResponse, status_code=201)
async def create_employee(
    body: EmployeeCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_MANAGE))],
) -> EmployeeResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    from app.billing.service import EntitlementService
    from app.repositories.memory_repos import EmployeeRepository

    active = sum(
        1
        for e in EmployeeRepository(org.organization_id).list_all()
        if e.status == "active"
    )
    EntitlementService().assert_within_limit(
        org.organization_id,
        "organization.max_users",
        current_usage=active,
        increment=1,
    )
    record = EmployeeService(org.organization_id).create(
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
        full_name=body.full_name,
        email=body.email,
        title=body.title,
        department_id=body.department_id,
        is_manager=body.is_manager,
        employee_code=body.employee_code,
        role_code=body.role_code,
        approval_authority_limit=body.approval_authority_limit,
        approval_authority_currency=body.approval_authority_currency,
    )
    return EmployeeResponse.model_validate(record, from_attributes=True)


@router.get("/employees/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_READ))],
) -> EmployeeResponse:
    record = EmployeeService(org.organization_id).get(employee_id)
    return EmployeeResponse.model_validate(record, from_attributes=True)


@router.patch("/employees/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: UUID,
    body: EmployeeUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_MANAGE))],
) -> EmployeeResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = EmployeeService(org.organization_id).update(
        employee_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
        **body.model_dump(exclude_unset=True, exclude={"organization_id"}),
    )
    return EmployeeResponse.model_validate(record, from_attributes=True)


@router.post("/employees/{employee_id}/deactivate", response_model=EmployeeResponse)
async def deactivate_employee(
    employee_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_MANAGE))],
) -> EmployeeResponse:
    record = EmployeeService(org.organization_id).deactivate(
        employee_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return EmployeeResponse.model_validate(record, from_attributes=True)


@router.get("/managers", response_model=Page[EmployeeResponse])
async def list_managers(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[EmployeeResponse]:
    items = [e for e in EmployeeService(org.organization_id).list_all() if e.is_manager]
    return _employee_page(items, params)


@router.post("/manager-links", response_model=ManagerLinkResponse, status_code=201)
async def create_manager_link(
    body: ManagerLinkCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_MANAGE))],
) -> ManagerLinkResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    link = EmployeeService(org.organization_id).set_manager_link(
        employee_id=body.employee_id,
        manager_employee_id=body.manager_employee_id,
        link_type=body.link_type,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return ManagerLinkResponse.model_validate(link, from_attributes=True)


@router.get("/roles", response_model=list[RoleCatalogItem])
async def list_roles(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_READ))],
) -> list[RoleCatalogItem]:
    _ = org
    return [RoleCatalogItem.model_validate(item) for item in ORG_ROLE_CATALOG]


@router.get("/departments", response_model=Page[DepartmentResponse])
async def list_departments(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[DepartmentResponse]:
    items = DepartmentService(org.organization_id).list_all()
    page = apply_list(
        items,
        params,
        search_fields=[lambda d: d.name, lambda d: d.code or ""],
        status_getter=lambda d: d.status,
        sort_fields={"name": lambda d: d.name},
    )
    return Page(
        items=[DepartmentResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )


@router.post("/departments", response_model=DepartmentResponse, status_code=201)
async def create_department(
    body: DepartmentCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_MANAGE))],
) -> DepartmentResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = DepartmentService(org.organization_id).create(
        name=body.name,
        code=body.code,
        parent_department_id=body.parent_department_id,
        manager_employee_id=body.manager_employee_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return DepartmentResponse.model_validate(record, from_attributes=True)


@router.patch("/departments/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: UUID,
    body: DepartmentUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_MANAGE))],
) -> DepartmentResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = DepartmentService(org.organization_id).update(
        department_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
        **body.model_dump(exclude_unset=True, exclude={"organization_id"}),
    )
    return DepartmentResponse.model_validate(record, from_attributes=True)


@router.post("/departments/{department_id}/deactivate", response_model=DepartmentResponse)
async def deactivate_department(
    department_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_MANAGE))],
) -> DepartmentResponse:
    record = DepartmentService(org.organization_id).deactivate(
        department_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return DepartmentResponse.model_validate(record, from_attributes=True)


@router.get("/cost-centers", response_model=Page[CostCenterResponse])
async def list_cost_centers(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[CostCenterResponse]:
    items = CostCenterService(org.organization_id).list_all()
    page = apply_list(
        items,
        params,
        search_fields=[lambda c: c.code, lambda c: c.name],
        status_getter=lambda c: c.status,
        sort_fields={"name": lambda c: c.name, "code": lambda c: c.code},
    )
    return Page(
        items=[CostCenterResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )


@router.post("/cost-centers", response_model=CostCenterResponse, status_code=201)
async def create_cost_center(
    body: CostCenterCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.ORG_CONFIGURE))],
) -> CostCenterResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = CostCenterService(org.organization_id).create(
        code=body.code,
        name=body.name,
        department_id=body.department_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return CostCenterResponse.model_validate(record, from_attributes=True)


@router.patch("/cost-centers/{cost_center_id}", response_model=CostCenterResponse)
async def update_cost_center(
    cost_center_id: UUID,
    body: CostCenterUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.ORG_CONFIGURE))],
) -> CostCenterResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = CostCenterService(org.organization_id).update(
        cost_center_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
        **body.model_dump(exclude_unset=True, exclude={"organization_id"}),
    )
    return CostCenterResponse.model_validate(record, from_attributes=True)


@router.post("/cost-centers/{cost_center_id}/deactivate", response_model=CostCenterResponse)
async def deactivate_cost_center(
    cost_center_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.ORG_CONFIGURE))],
) -> CostCenterResponse:
    record = CostCenterService(org.organization_id).deactivate(
        cost_center_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return CostCenterResponse.model_validate(record, from_attributes=True)


@router.get("/suppliers", response_model=Page[SupplierResponse])
async def list_suppliers(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[SupplierResponse]:
    items = SupplierService(org.organization_id).list_all()
    page = apply_list(
        items,
        params,
        search_fields=[lambda s: s.name, lambda s: s.code or ""],
        status_getter=lambda s: s.status,
        sort_fields={"name": lambda s: s.name},
    )
    return Page(
        items=[SupplierResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )


@router.post("/suppliers", response_model=SupplierResponse, status_code=201)
async def create_supplier(
    body: SupplierCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_MANAGE))],
) -> SupplierResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    from app.billing.service import EntitlementService
    from app.repositories.memory_repos import SupplierRepository

    active = sum(
        1
        for s in SupplierRepository(org.organization_id).list_all()
        if s.status == "active"
    )
    EntitlementService().assert_within_limit(
        org.organization_id,
        "organization.max_suppliers",
        current_usage=active,
        increment=1,
    )
    record = SupplierService(org.organization_id).create(
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
        name=body.name,
        code=body.code,
        website=body.website,
        country_code=body.country_code,
        approval_status=body.approval_status,
    )
    return SupplierResponse.model_validate(record, from_attributes=True)


@router.get("/suppliers/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_READ))],
) -> SupplierResponse:
    record = SupplierService(org.organization_id).get(supplier_id)
    return SupplierResponse.model_validate(record, from_attributes=True)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: UUID,
    body: SupplierUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_MANAGE))],
) -> SupplierResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = SupplierService(org.organization_id).update(
        supplier_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
        **body.model_dump(exclude_unset=True, exclude={"organization_id"}),
    )
    return SupplierResponse.model_validate(record, from_attributes=True)


@router.post("/suppliers/{supplier_id}/deactivate", response_model=SupplierResponse)
async def deactivate_supplier(
    supplier_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_MANAGE))],
) -> SupplierResponse:
    record = SupplierService(org.organization_id).deactivate(
        supplier_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return SupplierResponse.model_validate(record, from_attributes=True)


@router.get("/supplier-contacts", response_model=Page[SupplierContactResponse])
async def list_supplier_contacts(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[SupplierContactResponse]:
    items = SupplierService(org.organization_id).contacts.list_all()
    page = apply_list(
        items,
        params,
        search_fields=[lambda c: c.full_name, lambda c: c.email or ""],
        sort_fields={"name": lambda c: c.full_name},
    )
    return Page(
        items=[
            SupplierContactResponse.model_validate(i, from_attributes=True) for i in page.items
        ],
        meta=page.meta,
    )


@router.post("/supplier-contacts", response_model=SupplierContactResponse, status_code=201)
async def create_supplier_contact(
    body: SupplierContactCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_MANAGE))],
) -> SupplierContactResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = SupplierService(org.organization_id).add_contact(
        supplier_id=body.supplier_id,
        full_name=body.full_name,
        email=body.email,
        is_primary=body.is_primary,
        phone=body.phone,
        role_title=body.role_title,
        allow_duplicate_email=body.allow_duplicate_email,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return SupplierContactResponse.model_validate(record, from_attributes=True)


@router.post("/supplier-products", response_model=SupplierProductResponse, status_code=201)
async def create_supplier_product(
    body: SupplierProductCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_MANAGE))],
) -> SupplierProductResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = SupplierService(org.organization_id).add_product(
        supplier_id=body.supplier_id,
        name=body.name,
        sku=body.sku,
        unit_price=body.unit_price,
        currency_code=body.currency_code,
        description=body.description,
        unit_of_measure=body.unit_of_measure,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return SupplierProductResponse.model_validate(record, from_attributes=True)


@router.get("/supplier-products", response_model=Page[SupplierProductResponse])
async def list_supplier_products(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[SupplierProductResponse]:
    items = SupplierService(org.organization_id).products.list_all()
    page = apply_list(
        items,
        params,
        search_fields=[lambda p: p.name, lambda p: p.sku or ""],
        status_getter=lambda p: p.status,
        sort_fields={"name": lambda p: p.name},
    )
    return Page(
        items=[
            SupplierProductResponse.model_validate(i, from_attributes=True) for i in page.items
        ],
        meta=page.meta,
    )


@router.get("/budgets", response_model=Page[BudgetResponse])
async def list_budgets(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[BudgetResponse]:
    items = BudgetService(org.organization_id).list_all()
    page = apply_list(
        items,
        params,
        search_fields=[lambda b: b.name],
        status_getter=lambda b: b.status,
        sort_fields={"name": lambda b: b.name, "fiscal_year": lambda b: b.fiscal_year},
    )
    return Page(
        items=[BudgetResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )


@router.post("/budgets", response_model=BudgetResponse, status_code=201)
async def create_budget(
    body: BudgetCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.ORG_CONFIGURE))],
) -> BudgetResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = BudgetService(org.organization_id).create(
        name=body.name,
        fiscal_year=body.fiscal_year,
        amount_total=body.amount_total,
        currency_code=body.currency_code,
        department_id=body.department_id,
        cost_center_id=body.cost_center_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return BudgetResponse.model_validate(record, from_attributes=True)


@router.patch("/budgets/{budget_id}", response_model=BudgetResponse)
async def update_budget(
    budget_id: UUID,
    body: BudgetUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.ORG_CONFIGURE))],
) -> BudgetResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = BudgetService(org.organization_id).update(
        budget_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
        **body.model_dump(exclude_unset=True, exclude={"organization_id"}),
    )
    return BudgetResponse.model_validate(record, from_attributes=True)


@router.get("/policies", response_model=Page[PolicyResponse])
async def list_policies(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.POLICIES_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[PolicyResponse]:
    items = PolicyService(org.organization_id).list_all()
    page = apply_list(
        items,
        params,
        search_fields=[lambda p: p.code, lambda p: p.title],
        status_getter=lambda p: p.status,
        sort_fields={"code": lambda p: p.code, "title": lambda p: p.title},
    )
    return Page(
        items=[PolicyResponse.model_validate(i, from_attributes=True) for i in page.items],
        meta=page.meta,
    )


@router.post("/policies", response_model=PolicyResponse, status_code=201)
async def create_policy(
    body: PolicyCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.POLICIES_MANAGE))],
) -> PolicyResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = PolicyService(org.organization_id).create(
        code=body.code,
        title=body.title,
        category=body.category,
        description=body.description,
        owner_employee_id=body.owner_employee_id,
        metadata=body.metadata,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return PolicyResponse.model_validate(record, from_attributes=True)


@router.patch("/policies/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: UUID,
    body: PolicyUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.POLICIES_MANAGE))],
) -> PolicyResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    record = PolicyService(org.organization_id).update(
        policy_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
        **body.model_dump(exclude_unset=True, exclude={"organization_id"}),
    )
    return PolicyResponse.model_validate(record, from_attributes=True)


@router.post("/policies/{policy_id}/deactivate", response_model=PolicyResponse)
async def deactivate_policy(
    policy_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.POLICIES_MANAGE))],
) -> PolicyResponse:
    record = PolicyService(org.organization_id).deactivate(
        policy_id,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return PolicyResponse.model_validate(record, from_attributes=True)
