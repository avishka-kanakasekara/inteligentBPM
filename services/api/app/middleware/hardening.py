"""Request body size limits and API rate limiting middleware."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.observability.metrics import (
    M_API_ERRORS,
    M_API_LATENCY,
    M_API_REQUESTS,
    M_CROSS_TENANT,
    M_PLAN_LIMIT,
    metrics,
)
from app.observability.tracing import format_traceparent, start_span
from app.security.rate_limit import RateLimitExceeded, api_rate_limiter, login_abuse_protector


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        max_bytes = int(getattr(settings, "max_request_bytes", 1_048_576) or 1_048_576)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "INVALID_CONTENT_LENGTH", "message": "Bad Content-Length"}},
                )
            if length > max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "REQUEST_TOO_LARGE",
                            "message": f"Request body exceeds {max_bytes} bytes",
                            "details": {"max_bytes": max_bytes},
                        }
                    },
                )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.endswith(("/healthz", "/readyz", "/metrics", "/alerts")):
            return await call_next(request)

        settings = get_settings()
        ip = _client_ip(request)
        limit = settings.effective_rate_limit_per_minute()
        allowed, retry_after = api_rate_limiter.hit(
            f"api:{ip}", limit=limit, window_seconds=60.0
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(int(retry_after) + 1)},
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Rate limit exceeded",
                        "details": {"retry_after_seconds": retry_after},
                    }
                },
            )

        # Login abuse gate only for credential-submission style routes (none currently;
        # browser auth goes to Supabase). Do not lock /auth/organizations on stale JWTs.
        if request.url.path.rstrip("/").endswith("/auth/login"):
            try:
                login_abuse_protector.assert_allowed(f"login:{ip}")
            except RateLimitExceeded as exc:
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(int(exc.retry_after) + 1)},
                    content={
                        "error": {
                            "code": exc.code,
                            "message": exc.message,
                            "details": exc.details,
                        }
                    },
                )

        return await call_next(request)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """API latency metrics, tracing, and error accounting."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        method = request.method
        traceparent = request.headers.get("traceparent")
        started = time.perf_counter()
        metrics.incr(M_API_REQUESTS, method=method)

        with start_span(f"{method} {path}", traceparent=traceparent, path=path) as span:
            try:
                response = await call_next(request)
            except Exception:
                metrics.incr(M_API_ERRORS, method=method, status="500")
                raise
            elapsed_ms = (time.perf_counter() - started) * 1000
            metrics.observe(M_API_LATENCY, elapsed_ms, method=method)
            if response.status_code >= 500:
                metrics.incr(M_API_ERRORS, method=method, status=str(response.status_code))
            if response.status_code == 403:
                # Heuristic: TENANT_MISMATCH / authz often surfaces as 403
                body_hint = response.headers.get("x-error-code", "")
                if "TENANT" in body_hint or "FORBIDDEN" in body_hint:
                    metrics.incr(M_CROSS_TENANT)
            if response.status_code == 402:
                metrics.incr(M_PLAN_LIMIT)
            response.headers["traceparent"] = format_traceparent(span.trace_id, span.span_id)
            response.headers["X-Trace-Id"] = span.trace_id
            return response
