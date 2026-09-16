"""Security helpers and JWT validation for Supabase Auth tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from urllib.parse import urljoin

import httpx
import jwt

from app.config import Settings


class AuthenticationError(Exception):
    def __init__(
        self,
        message: str = "Authentication required",
        *,
        code: str = "AUTH_UNAUTHORIZED",
    ) -> None:
        super().__init__(message)
        self.code = code


class AuthorizationError(Exception):
    def __init__(self, message: str = "Forbidden", *, code: str = "AUTH_FORBIDDEN") -> None:
        super().__init__(message)
        self.code = code


class TenantMismatchError(Exception):
    def __init__(self, message: str = "Organization context mismatch") -> None:
        super().__init__(message)
        self.code = "TENANT_MISMATCH"


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID
    email: str | None
    role: str
    claims: dict[str, Any]


def _user_from_payload(payload: dict[str, Any]) -> AuthenticatedUser:
    sub = payload.get("sub") or payload.get("id")
    if not sub:
        raise AuthenticationError("Token missing subject")
    try:
        user_id = UUID(str(sub))
    except ValueError as exc:
        raise AuthenticationError("Token subject is not a valid UUID") from exc

    exp = payload.get("exp")
    if exp is not None and datetime.fromtimestamp(int(exp), tz=UTC) < datetime.now(UTC):
        raise AuthenticationError("Token expired")

    return AuthenticatedUser(
        id=user_id,
        email=payload.get("email"),
        role=str(payload.get("role") or "authenticated"),
        claims=payload,
    )


def _validate_via_auth_api(token: str, settings: Settings) -> AuthenticatedUser:
    """Validate access tokens through Supabase Auth when JWT secret is unavailable."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise AuthenticationError(
            "SUPABASE_JWT_SECRET is not configured (and Auth API fallback is unavailable)"
        )
    url = urljoin(settings.supabase_url.rstrip("/") + "/", "auth/v1/user")
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": settings.supabase_anon_key,
    }
    try:
        response = httpx.get(url, headers=headers, timeout=5.0)
    except httpx.HTTPError as exc:
        raise AuthenticationError("Unable to validate token with Supabase Auth") from exc
    if response.status_code == 401:
        raise AuthenticationError("Invalid or expired token")
    if response.status_code >= 400:
        raise AuthenticationError("Invalid or expired token")
    data = response.json()
    if not isinstance(data, dict):
        raise AuthenticationError("Invalid auth response")
    # Auth /user returns the user object; map into claim-like shape
    payload = {
        "sub": data.get("id"),
        "email": data.get("email"),
        "role": (data.get("role") or "authenticated"),
        **{k: v for k, v in data.items() if k not in {"id", "email", "role"}},
    }
    return _user_from_payload(payload)


def _decode_hs256_with_secret(token: str, settings: Settings) -> AuthenticatedUser:
    if not settings.supabase_jwt_secret:
        raise AuthenticationError("SUPABASE_JWT_SECRET is not configured")
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_audience,
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired token") from exc
    return _user_from_payload(payload)


def validate_supabase_jwt(token: str, settings: Settings) -> AuthenticatedUser:
    if settings.app_env != "production" and token.startswith("mock-access-token:"):
        parts = token.split(":", 1)
        raw_id = parts[1] if len(parts) > 1 else "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        try:
            user_id = UUID(raw_id)
        except ValueError:
            user_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        return AuthenticatedUser(
            id=user_id,
            email="owner@demo.bpm.local",
            role="authenticated",
            claims={"sub": str(user_id), "email": "owner@demo.bpm.local"},
        )

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired token") from exc

    algorithm = str(header.get("alg") or "HS256")
    # Modern hosted Supabase projects issue ES256 access tokens — validate via Auth API.
    if algorithm != "HS256":
        return _validate_via_auth_api(token, settings)

    if settings.supabase_jwt_secret:
        try:
            return _decode_hs256_with_secret(token, settings)
        except AuthenticationError:
            # Misconfigured legacy secret — fall back to Supabase Auth API.
            return _validate_via_auth_api(token, settings)

    return _validate_via_auth_api(token, settings)
