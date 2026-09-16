"""Exception handlers producing the standard error envelope."""

from __future__ import annotations

from typing import Any

from bpm_contracts import ErrorBody, ErrorResponse
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import SettingsValidationError
from app.core.logging import get_logger
from app.middleware.correlation import get_correlation_id
from app.observability.errors import error_tracker
from app.observability.metrics import M_CROSS_TENANT, metrics
from app.observability.tracing import current_trace_id
from app.security.errors import AppError
from app.security.jwt import AuthenticationError, AuthorizationError, TenantMismatchError
from app.security.log_filter import sanitize_for_log

logger = get_logger()


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    correlation_id: str,
    details: object | None = None,
) -> JSONResponse:
    details_value: dict[str, Any] | list[Any] | None
    if details is None or isinstance(details, (dict, list)):
        details_value = details
    else:
        details_value = {"value": details}
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details_value,
            correlation_id=correlation_id,
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def authn_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        logger.warning("auth_failed", path=str(request.url.path), code=exc.code)
        return _error_response(
            status_code=401,
            code=exc.code,
            message=str(exc),
            correlation_id=get_correlation_id(request),
        )

    @app.exception_handler(AuthorizationError)
    async def authz_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
        return _error_response(
            status_code=403,
            code=exc.code,
            message=str(exc),
            correlation_id=get_correlation_id(request),
        )

    @app.exception_handler(TenantMismatchError)
    async def tenant_handler(request: Request, exc: TenantMismatchError) -> JSONResponse:
        metrics.incr(M_CROSS_TENANT)
        logger.warning(
            "cross_tenant_denied",
            path=str(request.url.path),
            code=exc.code,
        )
        return _error_response(
            status_code=403,
            code=exc.code,
            message=str(exc),
            correlation_id=get_correlation_id(request),
        )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            error_tracker.capture(
                exc,
                path=str(request.url.path),
                correlation_id=get_correlation_id(request),
                trace_id=current_trace_id(),
                extras={"code": exc.code},
            )
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            correlation_id=get_correlation_id(request),
            details=sanitize_for_log(exc.details) if exc.details else None,
        )

    @app.exception_handler(SettingsValidationError)
    async def settings_validation_handler(
        request: Request, exc: SettingsValidationError
    ) -> JSONResponse:
        return _error_response(
            status_code=500,
            code="ENV_VALIDATION_FAILED",
            message=str(exc),
            correlation_id=get_correlation_id(request),
            details={"missing": exc.missing},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = "HTTP_ERROR"
        if exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 401:
            code = "AUTH_UNAUTHORIZED"
        elif exc.status_code == 403:
            code = "AUTH_FORBIDDEN"
        return _error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
            correlation_id=get_correlation_id(request),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed",
            correlation_id=get_correlation_id(request),
            details=list(exc.errors()),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = get_correlation_id(request)
        error_tracker.capture(
            exc,
            path=str(request.url.path),
            correlation_id=correlation_id,
            trace_id=current_trace_id(),
        )
        logger.exception("unhandled_error", error=str(exc), correlation_id=correlation_id)
        return _error_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
            correlation_id=correlation_id,
        )
