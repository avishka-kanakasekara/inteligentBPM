"""JWT validation — HS256 legacy and ES256 Supabase Auth API fallback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt as pyjwt
import pytest

from app.config import get_settings, reset_settings_cache
from app.security.jwt import AuthenticatedUser, validate_supabase_jwt


@pytest.fixture()
def settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("BPM_LOAD_DOTENV", "0")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-supabase-jwt-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    reset_settings_cache()
    return get_settings()


def test_hs256_token_validates_with_secret(settings) -> None:
    now = datetime.now(UTC)
    token = pyjwt.encode(
        {
            "sub": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "email": "owner@demo.bpm.local",
            "role": "authenticated",
            "aud": "authenticated",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )
    user = validate_supabase_jwt(token, settings)
    assert user.id == UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def test_es256_token_uses_auth_api(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    token = pyjwt.encode(
        {
            "sub": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "email": "user@example.com",
            "role": "authenticated",
            "aud": "authenticated",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        "not-used-for-es256-test",
        algorithm="HS256",
    )
    header = pyjwt.get_unverified_header(token)
    header["alg"] = "ES256"

    def fake_header(_token: str) -> dict[str, str]:
        return header

    def fake_auth_api(_token: str, _settings: object) -> AuthenticatedUser:
        assert _token == token
        return AuthenticatedUser(
            id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            email="user@example.com",
            role="authenticated",
            claims={"sub": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"},
        )

    monkeypatch.setattr("app.security.jwt.jwt.get_unverified_header", fake_header)
    monkeypatch.setattr("app.security.jwt._validate_via_auth_api", fake_auth_api)

    user = validate_supabase_jwt(token, settings)
    assert user.id == UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
