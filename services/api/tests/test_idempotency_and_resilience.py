"""Idempotency, retries, circuit breaking, and failure recovery tests."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.llm.failures import LLMError
from app.llm.model_registry import ModelRegistry
from app.llm.retry import CircuitBreaker, LLMRetryPolicy
from app.llm.types import AgentKind, LLMFailureKind
from app.security.errors import ConflictError
from app.services.idempotency import IdempotencyService


def test_idempotency_service_replay_and_conflict() -> None:
    svc = IdempotencyService()
    org_id = uuid4()
    key = f"idem-key-{uuid4()}"
    scope = "tool_execution"

    payload1 = {"action": "send_email", "to": "supplier@example.com"}

    # 1. First call begins: returns None (indicating new execution allowed)
    replay = svc.begin(
        organization_id=org_id,
        scope=scope,
        key=key,
        payload=payload1,
    )
    assert replay is None

    # 2. Complete execution
    svc.complete(
        organization_id=org_id,
        scope=scope,
        key=key,
        response_status=200,
        response_body={"message_id": "msg-12345", "delivered": True},
    )

    # 3. Replay with identical key and payload: returns cached response
    cached = svc.begin(
        organization_id=org_id,
        scope=scope,
        key=key,
        payload=payload1,
    )
    assert cached is not None
    assert cached["replay"] is True
    assert cached["status"] == 200
    assert cached["body"]["message_id"] == "msg-12345"

    # 4. Replay with SAME key but DIFFERENT payload: raises ConflictError
    payload2 = {"action": "send_email", "to": "different@example.com"}
    with pytest.raises(ConflictError):
        svc.begin(
            organization_id=org_id,
            scope=scope,
            key=key,
            payload=payload2,
        )


def test_idempotent_usage_event_recording(
    client: TestClient,
    auth_headers_a: dict[str, str],
) -> None:
    idem_key = f"idem-usage-{uuid4()}"

    resp1 = client.post(
        "/v1/billing/usage",
        headers=auth_headers_a,
        json={"meter_code": "llm_tokens", "quantity": 150, "idempotency_key": idem_key},
    )
    assert resp1.status_code == 201
    body1 = resp1.json()

    # Replay with same key in body: should return identical event id
    resp2 = client.post(
        "/v1/billing/usage",
        headers=auth_headers_a,
        json={"meter_code": "llm_tokens", "quantity": 150, "idempotency_key": idem_key},
    )
    assert resp2.status_code == 201
    body2 = resp2.json()
    assert body2["id"] == body1["id"]
    assert body2["quantity"] == 150.0


def test_llm_retry_policy_logic() -> None:
    policy = LLMRetryPolicy(max_attempts=3, base_delay_seconds=0.1, max_delay_seconds=2.0)

    # Transient errors are retryable for attempt < max_attempts
    err_rate_limit = LLMError("429 rate limit", kind=LLMFailureKind.RATE_LIMIT, retryable=True)
    assert policy.should_retry(err_rate_limit, attempt=1) is True
    assert policy.should_retry(err_rate_limit, attempt=2) is True
    assert policy.should_retry(err_rate_limit, attempt=3) is False  # Max attempts reached

    # Backoff calculation
    assert policy.delay_seconds(1) == 0.1
    assert policy.delay_seconds(2) == 0.2
    assert policy.delay_seconds(3) == 0.4
    assert policy.delay_seconds(10) <= 2.0  # Capped at max_delay_seconds

    # Permanent errors must NOT be retried
    err_validation = LLMError("Bad schema", kind=LLMFailureKind.VALIDATION_ERROR, retryable=False)
    assert policy.should_retry(err_validation, attempt=1) is False


def test_circuit_breaker_trip_and_reset() -> None:
    breaker = CircuitBreaker(failure_threshold=3, reset_seconds=0.05)

    assert breaker.allow() is True
    assert breaker.is_open is False

    # Record 2 failures (below threshold)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow() is True

    # 3rd failure trips the breaker
    breaker.record_failure()
    assert breaker.is_open is True
    assert breaker.allow() is False

    # Wait for reset interval
    time.sleep(0.06)
    # Once reset_seconds passes, breaker allows probe request
    assert breaker.allow() is True

    # Successful call resets failure count
    breaker.record_success()
    assert breaker.is_open is False


def test_model_fallback_resolution_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-2.0-flash")

    registry = ModelRegistry()
    primary = registry.resolve(AgentKind.PLANNER, allow_fallback=False)
    fallback = registry.fallback(AgentKind.PLANNER)

    assert primary == "gemini-2.5-flash"
    assert fallback == "gemini-2.0-flash"
    assert primary != fallback
