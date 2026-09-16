"""CSV import preview and commit endpoints for organization management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.deps import (
    OrganizationContext,
    get_current_user,
    ignore_client_organization_id,
    require_permission,
)
from app.contracts.schemas import (
    ImportCommitResponse,
    ImportPreviewRequest,
    ImportPreviewResponse,
    ImportRowErrorResponse,
)
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.security.jwt import AuthenticatedUser
from app.services.org_management import CsvImportService, ImportPreviewResult

router = APIRouter(prefix="/imports", tags=["imports"])


def _preview_response(result: ImportPreviewResult) -> ImportPreviewResponse:
    return ImportPreviewResponse(
        total_rows=result.total_rows,
        valid_count=len(result.valid_rows),
        error_count=len(result.errors),
        duplicate_count=len(result.duplicates),
        valid_rows=result.valid_rows,
        errors=[ImportRowErrorResponse(**e.__dict__) for e in result.errors],
        duplicates=[ImportRowErrorResponse(**d.__dict__) for d in result.duplicates],
    )


@router.post("/employees/preview", response_model=ImportPreviewResponse)
async def preview_employee_import(
    body: ImportPreviewRequest,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_MANAGE))],
) -> ImportPreviewResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    result = CsvImportService(org.organization_id).preview_employees(body.csv_content)
    return _preview_response(result)


@router.post("/employees/commit", response_model=ImportCommitResponse)
async def commit_employee_import(
    body: ImportPreviewRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DIRECTORY_MANAGE))],
) -> ImportCommitResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    result = CsvImportService(org.organization_id).commit_employees(
        body.csv_content,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return ImportCommitResponse(**result)


@router.post("/suppliers/preview", response_model=ImportPreviewResponse)
async def preview_supplier_import(
    body: ImportPreviewRequest,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_MANAGE))],
) -> ImportPreviewResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    result = CsvImportService(org.organization_id).preview_suppliers(body.csv_content)
    return _preview_response(result)


@router.post("/suppliers/commit", response_model=ImportCommitResponse)
async def commit_supplier_import(
    body: ImportPreviewRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.SUPPLIERS_MANAGE))],
) -> ImportCommitResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    result = CsvImportService(org.organization_id).commit_suppliers(
        body.csv_content,
        actor_user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return ImportCommitResponse(**result)
