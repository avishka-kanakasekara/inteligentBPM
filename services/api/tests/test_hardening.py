"""Production hardening tests — headers, limits, SSRF, redaction, metrics, readiness."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.execution.url_allowlist import sanitize_outbound_urls
from app.observability.alerts import evaluate_alerts
from app.observability.metrics import (
    M_API_ERRORS,
    M_API_REQUESTS,
    M_CROSS_TENANT,
    M_GEMINI_FAILURES,
    M_GEMINI_REQUESTS,
    M_TOKEN_USAGE,
    metrics,
)
from app.security.log_filter import redact_string, sanitize_for_log
from app.security.rate_limit import SlidingWindowRateLimiter, login_abuse_protector
from app.security.ssrf import SSRFBlocked, assert_safe_outbound_url
from app.services.documents.malware import MalwareScanAdapter
from app.services.documents.validation import validate_upload
from app.services.readiness import check_migrations, check_secrets


def test_security_headers_and_csp(client: TestClient) -> None:
    response = client.get("/v1/healthz")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in response.headers
    assert "default-src" in response.headers["Content-Security-Policy"]
    assert response.headers.get("Referrer-Policy") == "no-referrer"


def test_cors_allowlist(client: TestClient) -> None:
    response = client.options(
        "/v1/healthz",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code in {200, 204}
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_request_size_limit(client: TestClient, auth_headers_a: dict[str, str]) -> None:
    # Oversized Content-Length is rejected before body read
    response = client.post(
        "/v1/processes",
        headers={**auth_headers_a, "Content-Length": str(2_000_000)},
        content=b"{}",
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"


def test_rate_limiter_unit() -> None:
    limiter = SlidingWindowRateLimiter()
    for _ in range(3):
        ok, _ = limiter.hit("k", limit=3, window_seconds=60)
        assert ok
    ok, retry = limiter.hit("k", limit=3, window_seconds=60)
    assert ok is False
    assert retry > 0


def test_stale_bearer_tokens_do_not_trigger_login_lockout(client: TestClient) -> None:
    """Invalid API sessions must not lock the IP (that broke /auth/organizations)."""
    login_abuse_protector._failures.clear()
    login_abuse_protector._lockouts.clear()
    login_abuse_protector.max_failures = 3
    login_abuse_protector.window_seconds = 60
    login_abuse_protector.lockout_seconds = 60

    for _ in range(5):
        response = client.get("/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401

    still_auth = client.get("/v1/auth/me", headers={"Authorization": "Bearer still-bad"})
    assert still_auth.status_code == 401

    login_abuse_protector._failures.clear()
    login_abuse_protector._lockouts.clear()
    login_abuse_protector.max_failures = 10


def test_login_abuse_protector_unit() -> None:
    login_abuse_protector._failures.clear()
    login_abuse_protector._lockouts.clear()
    login_abuse_protector.max_failures = 3
    login_abuse_protector.window_seconds = 60
    login_abuse_protector.lockout_seconds = 60

    key = "login:test-ip"
    for _ in range(3):
        login_abuse_protector.record_failure(key)
    with pytest.raises(Exception) as exc:
        login_abuse_protector.assert_allowed(key)
    assert getattr(exc.value, "code", None) == "RATE_LIMITED"

    login_abuse_protector._failures.clear()
    login_abuse_protector._lockouts.clear()
    login_abuse_protector.max_failures = 10


def test_file_size_and_mime_and_malware() -> None:
    with pytest.raises(Exception):
        validate_upload(file_name="x.exe", content=b"MZ\x90\x00", max_bytes=100)

    ok = validate_upload(
        file_name="note.txt",
        content=b"hello world",
        declared_mime="text/plain",
        max_bytes=100,
    )
    assert ok.mime_type == "text/plain"

    scanner = MalwareScanAdapter()
    eicar = (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )
    result = scanner.scan(eicar, mime_type="text/plain")
    assert result.clean is False


def test_ssrf_and_url_allowlist() -> None:
    with pytest.raises(SSRFBlocked):
        assert_safe_outbound_url(
            "http://169.254.169.254/latest/meta-data/",
            allowed_hosts=frozenset({"example.com"}),
            resolve_dns=False,
        )
    with pytest.raises(SSRFBlocked):
        assert_safe_outbound_url(
            "http://evil.example/path",
            allowed_hosts=frozenset({"mail.mock.local"}),
            resolve_dns=False,
        )
    assert_safe_outbound_url(
        "https://mail.mock.local/send",
        allowed_hosts=frozenset({"mail.mock.local"}),
        resolve_dns=False,
    )
    with pytest.raises(SSRFBlocked):
        sanitize_outbound_urls({"url": "https://not-allowed.example/x"})


def test_sensitive_log_filtering() -> None:
    payload = sanitize_for_log(
        {
            "access_token": "eyJhbGciOiJIUzI1NiJ9.aaa.bbb",
            "api_key": "sk-live-secret",
            "password": "hunter2",
            "email_body": "Confidential contract text " * 20,
            "user": "user@example.com",
            "safe": "ok",
        }
    )
    assert payload["access_token"] == "[REDACTED]"
    assert payload["api_key"] == "[REDACTED]"
    assert payload["password"] == "[REDACTED]"
    assert "Confidential" not in str(payload["email_body"])
    assert "[REDACTED_EMAIL]" in redact_string("mail me at user@example.com")
    assert "sk-live" not in redact_string("api_key=sk-live-secret")


def test_metrics_and_alerts(client: TestClient) -> None:
    metrics.reset()
    metrics.incr(M_API_REQUESTS, value=30)
    metrics.incr(M_API_ERRORS, value=5)
    metrics.incr(M_GEMINI_REQUESTS, value=20)
    metrics.incr(M_GEMINI_FAILURES, value=8)
    metrics.incr(M_TOKEN_USAGE, value=6_000_000)
    metrics.incr(M_CROSS_TENANT, value=10)

    alerts = evaluate_alerts()
    names = {a.name for a in alerts}
    assert "api_error_rate" in names
    assert "llm_failures" in names
    assert "excessive_token_usage" in names
    assert "suspicious_tenant_access" in names

    response = client.get("/v1/metrics")
    assert response.status_code == 200
    assert "counters" in response.json()

    alerts_resp = client.get("/v1/alerts")
    assert alerts_resp.status_code == 200
    assert "alerts" in alerts_resp.json()


def test_health_ready_migration_checks(client: TestClient) -> None:
    health = client.get("/v1/healthz")
    assert health.status_code == 200

    ready = client.get("/v1/readyz")
    assert ready.status_code in {200, 503}
    body = ready.json()
    assert "checks" in body

    deps = client.get("/v1/healthz/deps")
    assert deps.status_code == 200
    names = {c["name"] for c in deps.json()["checks"]}
    assert "migrations" in names
    assert "secrets" in names

    from app.config import get_settings

    mig = check_migrations(get_settings())
    assert mig.ready is True
    secrets = check_secrets(get_settings())
    assert secrets.ready is True


def test_csrf_bearer_exempt(
    client: TestClient,
    auth_headers_a: dict[str, str],
) -> None:
    # Bearer clients are not blocked by CSRF double-submit
    response = client.post(
        "/v1/processes",
        headers=auth_headers_a,
        json={"name": "Hardened Process", "description": "ok"},
    )
    assert response.status_code == 201
