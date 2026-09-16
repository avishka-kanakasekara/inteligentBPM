"""CSRF protection for cookie/session mutating requests; Origin allowlist checks."""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Awaitable, Callable
from hashlib import sha256

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_COOKIE = "bpm_csrf"
CSRF_HEADER = "X-CSRF-Token"
# Provider callbacks authenticate via signatures / shared secrets — not browser cookies.
CSRF_EXEMPT_SUFFIXES = (
    "/billing/webhooks",
    "/webhooks",
)


def _csrf_secret() -> str:
    settings = get_settings()
    return (
        getattr(settings, "app_signing_secret", None)
        or getattr(settings, "integrations_secret_key", None)
        or "dev-csrf-secret"
    )


def mint_csrf_token() -> str:
    nonce = secrets.token_urlsafe(16)
    sig = hmac.new(_csrf_secret().encode(), nonce.encode(), sha256).hexdigest()[:32]
    return f"{nonce}.{sig}"


def verify_csrf_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, sig = token.rsplit(".", 1)
    expected = hmac.new(_csrf_secret().encode(), nonce.encode(), sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expected)


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Double-submit CSRF for cookie-authenticated flows.

    Bearer-token API clients (Authorization header) are exempt — they are not
    subject to classic CSRF. Cookie-only mutating requests require a matching
    X-CSRF-Token header and Origin allowlist check.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if request.method in SAFE_METHODS:
            response = await call_next(request)
            # Issue CSRF cookie for browser clients
            if CSRF_COOKIE not in request.cookies:
                token = mint_csrf_token()
                response.set_cookie(
                    CSRF_COOKIE,
                    token,
                    httponly=False,
                    samesite="lax",
                    secure=settings.app_env == "production",
                    path="/",
                )
            return response

        # Mutating request
        path = request.url.path
        if any(path.endswith(suffix) for suffix in CSRF_EXEMPT_SUFFIXES):
            return await call_next(request)

        has_bearer = bool(request.headers.get("authorization"))
        if has_bearer:
            # Still validate Origin when present against CORS allowlist
            origin = request.headers.get("origin")
            if origin and origin not in settings.cors_origin_list and settings.app_env == "production":
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "CSRF_ORIGIN", "message": "Origin not allowed"}},
                )
            return await call_next(request)

        # Cookie session path
        cookie_token = request.cookies.get(CSRF_COOKIE)
        header_token = request.headers.get(CSRF_HEADER)
        origin = request.headers.get("origin")
        if origin and origin not in settings.cors_origin_list:
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "CSRF_ORIGIN", "message": "Origin not allowed"}},
            )
        if not cookie_token or not header_token or cookie_token != header_token:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "CSRF_FAILED",
                        "message": "CSRF token missing or invalid",
                    }
                },
            )
        if not verify_csrf_token(header_token):
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "CSRF_FAILED", "message": "CSRF token invalid"}},
            )
        return await call_next(request)
