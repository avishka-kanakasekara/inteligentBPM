"""Secure HTTP headers and Content-Security-Policy."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings


DEFAULT_CSP = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        settings = get_settings()
        csp = getattr(settings, "content_security_policy", None) or DEFAULT_CSP

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
        response.headers.setdefault("X-XSS-Protection", "0")
        if getattr(settings, "app_env", "local") == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
        if getattr(settings, "csp_report_only", False):
            response.headers.setdefault("Content-Security-Policy-Report-Only", csp)
        else:
            response.headers.setdefault("Content-Security-Policy", csp)
        # Cache control for API responses
        if request.url.path.startswith("/v1/") or request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
