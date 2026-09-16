"""Limit enforcement helpers and FastAPI middleware for entitlement snapshots."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.billing.service import EntitlementService, LimitExceeded
from app.billing.usage import UsageService


METERED_ROUTES: tuple[tuple[str, str, str, float], ...] = (
    ("POST", "/v1/process-runs", "process.monthly_runs", 1.0),
)


class EntitlementLimitMiddleware(BaseHTTPMiddleware):
    """
    Server-side limit middleware.

    Attaches entitlement/usage snapshots to the request and enforces known metered
    write routes before handlers run. The frontend may hide features; this is authority.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        path = request.url.path.rstrip("/") or "/"
        method = request.method.upper()
        org_header = request.headers.get("x-organization-id") or request.headers.get(
            "X-Organization-Id"
        )

        if org_header and method != "OPTIONS":
            try:
                org_id = UUID(org_header)
                request.state.entitlements = EntitlementService().snapshot_for_org(org_id)
                request.state.usage = UsageService().summary(org_id)

                for m, route_path, meter, qty in METERED_ROUTES:
                    target = route_path.rstrip("/")
                    if method == m and path == target:
                        try:
                            EntitlementService().assert_meter(org_id, meter, increment=qty)
                        except LimitExceeded as exc:
                            return JSONResponse(
                                status_code=exc.status_code,
                                content={
                                    "error": {
                                        "code": exc.code,
                                        "message": exc.message,
                                        "details": exc.details,
                                    }
                                },
                            )
            except (ValueError, AttributeError):
                pass

        return await call_next(request)  # type: ignore[no-any-return]


def enforce_feature(organization_id: UUID, feature_code: str) -> None:
    EntitlementService().assert_feature(organization_id, feature_code)


def enforce_meter(organization_id: UUID, meter_code: str, *, increment: float | int = 1) -> None:
    EntitlementService().assert_meter(organization_id, meter_code, increment=increment)


def record_and_enforce_meter(
    organization_id: UUID,
    meter_code: str,
    *,
    quantity: float | int = 1,
    idempotency_key: str | None = None,
    resource_id: UUID | None = None,
) -> dict[str, Any]:
    EntitlementService().assert_meter(organization_id, meter_code, increment=quantity)
    return UsageService().record(
        organization_id=organization_id,
        meter_code=meter_code,
        quantity=quantity,
        idempotency_key=idempotency_key,
        resource_id=resource_id,
    )
