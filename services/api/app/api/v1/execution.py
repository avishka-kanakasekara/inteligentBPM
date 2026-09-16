"""Agent 4 execution API — controlled tool gateway."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.agents.execution.catalog import TOOL_CATALOG
from app.agents.execution.service import ExecutionService
from app.auth.deps import (
    OrganizationContext,
    get_current_user,
    require_permission,
)
from app.contracts.schemas import (
    ExecutionInvokeRequest,
    ExecutionStartRequest,
    ExecutionStateResponse,
    PurchaseOrderSubmitRequest,
    QuotationCompareRequest,
    ToolDefinitionResponse,
    ToolInvocationResponse,
)
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.security.errors import NotFoundError
from app.security.jwt import AuthenticatedUser

router = APIRouter(tags=["execution"])

_NOT_RUN_ID = UUID("00000000-0000-0000-0000-000000000000")


def _empty_execution(process_id: UUID) -> ExecutionStateResponse:
    return ExecutionStateResponse(
        process_id=process_id,
        process_run_id=_NOT_RUN_ID,
        status="not_run",
        dry_run=False,
        pause_reason="Agent 4 has not been run yet.",
    )


@router.get("/tools", response_model=list[ToolDefinitionResponse])
async def list_tools(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> list[ToolDefinitionResponse]:
    return [
        ToolDefinitionResponse.model_validate(t.model_dump(mode="json"))
        for t in TOOL_CATALOG.values()
    ]


@router.post("/processes/{process_id}/execute", response_model=ExecutionStateResponse)
async def start_execution(
    process_id: UUID,
    body: ExecutionStartRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> ExecutionStateResponse:
    service = ExecutionService(org.organization_id)
    corr = get_correlation_id(request)
    if body.auto_run and not body.dry_run:
        result = service.auto_run_execution(
            process_id,
            user_id=user.id,
            correlation_id=corr,
            permissions=org.permissions,
            dry_run=False,
            process_version_id=body.process_version_id,
            approval_id=body.approval_id,
            max_steps=body.max_steps,
        )
    else:
        result = service.start_execution(
            process_id,
            user_id=user.id,
            correlation_id=corr,
            permissions=org.permissions,
            dry_run=body.dry_run,
            process_version_id=body.process_version_id,
            approval_id=body.approval_id,
        )
    return ExecutionStateResponse.model_validate(result)


@router.post("/processes/{process_id}/execution/advance", response_model=ExecutionStateResponse)
async def advance_execution(
    process_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
    max_steps: int = 10,
) -> ExecutionStateResponse:
    """Continue Gemini tool selection + real tool execution for an existing run."""
    service = ExecutionService(org.organization_id)
    result = service.advance_execution(
        process_id,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
        permissions=org.permissions,
        max_steps=max_steps,
    )
    return ExecutionStateResponse.model_validate(result)


@router.get("/processes/{process_id}/execution", response_model=ExecutionStateResponse)
async def get_execution(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> ExecutionStateResponse:
    service = ExecutionService(org.organization_id)
    try:
        return ExecutionStateResponse.model_validate(service.get_execution(process_id))
    except NotFoundError:
        return _empty_execution(process_id)

@router.post("/processes/{process_id}/execution/resume", response_model=ExecutionStateResponse)
async def resume_execution(
    process_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> ExecutionStateResponse:
    service = ExecutionService(org.organization_id)
    result = service.resume_execution(
        process_id,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
    )
    return ExecutionStateResponse.model_validate(result)


@router.post(
    "/processes/{process_id}/execution/tools",
    response_model=ToolInvocationResponse,
)
async def invoke_tool(
    process_id: UUID,
    body: ExecutionInvokeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> ToolInvocationResponse:
    service = ExecutionService(org.organization_id)
    inv = service.invoke_tool(
        process_id,
        tool_name=body.tool_name,
        arguments=body.arguments,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
        permissions=org.permissions,
        run_id=body.process_run_id,
        dry_run=body.dry_run,
    )
    return ToolInvocationResponse.model_validate(inv.model_dump(mode="json"))


@router.post(
    "/processes/{process_id}/execution/propose",
)
async def propose_execution_action(
    process_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
    run_id: UUID | None = None,
) -> dict[str, Any]:
    service = ExecutionService(org.organization_id)
    proposal = service.propose_next_tool(
        process_id,
        user_id=user.id,
        correlation_id=get_correlation_id(request),
        run_id=run_id,
        permissions=org.permissions,
    )
    return proposal.model_dump(mode="json")


@router.get("/processes/{process_id}/quotations")
async def list_quotations(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> dict[str, Any]:
    service = ExecutionService(org.organization_id)
    return {"items": service.list_quotations(process_id)}


@router.post("/processes/{process_id}/quotations/compare")
async def compare_quotations(
    process_id: UUID,
    body: QuotationCompareRequest,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> dict[str, Any]:
    service = ExecutionService(org.organization_id)
    return service.compare_quotations(
        process_id,
        quotation_ids=body.quotation_ids,
        explain=body.explain,
    )


@router.get("/processes/{process_id}/purchase-orders")
async def list_purchase_orders(
    process_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> dict[str, Any]:
    service = ExecutionService(org.organization_id)
    return {"items": service.list_purchase_orders(process_id)}


@router.post("/purchase-orders/{purchase_order_id}/submit", response_model=ToolInvocationResponse)
async def submit_purchase_order(
    purchase_order_id: UUID,
    body: PurchaseOrderSubmitRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.EXECUTION_RUN))],
) -> ToolInvocationResponse:
    if body.process_id is None:
        from app.security.errors import ValidationAppError

        raise ValidationAppError("process_id is required")
    service = ExecutionService(org.organization_id)
    inv = service.invoke_tool(
        body.process_id,
        tool_name="purchase_order.submit",
        arguments={
            "purchase_order_id": str(purchase_order_id),
            "idempotency_key": body.idempotency_key,
        },
        user_id=user.id,
        correlation_id=get_correlation_id(request),
        permissions=org.permissions,
        run_id=body.process_run_id,
        dry_run=body.dry_run,
    )
    return ToolInvocationResponse.model_validate(inv.model_dump(mode="json"))
