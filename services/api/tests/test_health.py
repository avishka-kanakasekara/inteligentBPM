from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("BPM_LOAD_DOTENV", "0")
    monkeypatch.setenv("SKIP_DEPENDENCY_CHECKS", "false")
    monkeypatch.setenv("PERSISTENCE_MODE", "memory")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    from app.config import reset_settings_cache
    from app.main import create_app

    reset_settings_cache()
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client
    reset_settings_cache()


def test_api_starts_and_healthz(client: TestClient) -> None:
    response = client.get("/v1/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "service" in payload
    assert "version" in payload
    assert response.headers.get("X-Correlation-Id")

    compat = client.get("/api/v1/healthz")
    assert compat.status_code == 200


def test_readyz_detects_missing_dependencies(client: TestClient) -> None:
    response = client.get("/v1/readyz")
    assert response.status_code == 503
    payload = response.json()
    assert payload["ready"] is False
    names = {check["name"]: check for check in payload["checks"]}
    assert names["redis"]["ready"] is False


def test_environment_validation_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("BPM_LOAD_DOTENV", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setenv("SKIP_DEPENDENCY_CHECKS", "false")
    monkeypatch.setenv("PERSISTENCE_MODE", "postgres")

    from app.config import (
        SettingsValidationError,
        reset_settings_cache,
        validate_settings_or_raise,
    )

    reset_settings_cache()
    with pytest.raises(SettingsValidationError) as exc_info:
        validate_settings_or_raise(require_runtime_deps=True)

    message = str(exc_info.value)
    assert "Environment validation failed" in message
    assert "REDIS_URL" in exc_info.value.missing
    assert "SUPABASE_URL" in exc_info.value.missing


def test_shared_contracts_importable() -> None:
    from bpm_contracts import HealthResponse, ReadinessResponse

    health = HealthResponse(service="api", version="0.1.0")
    readiness = ReadinessResponse(ready=True, service="api", checks=[])
    assert health.status == "ok"
    assert readiness.ready is True


def test_correlation_id_echo(client: TestClient) -> None:
    response = client.get("/v1/healthz", headers={"X-Correlation-Id": "test-corr-123"})
    assert response.headers["X-Correlation-Id"] == "test-corr-123"
