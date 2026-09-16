"""Retry policy and circuit breaker for LLM calls."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from app.llm.failures import LLMError
from app.llm.types import LLMFailureKind


@dataclass
class LLMRetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    # Failure kinds that may be retried
    retryable_kinds: frozenset[LLMFailureKind] = field(
        default_factory=lambda: frozenset(
            {
                LLMFailureKind.TIMEOUT,
                LLMFailureKind.RATE_LIMIT,
                LLMFailureKind.TRANSIENT,
                LLMFailureKind.MODEL_UNAVAILABLE,
                LLMFailureKind.INVALID_JSON,
            }
        )
    )

    def should_retry(self, error: LLMError, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        return error.retryable and error.kind in self.retryable_kinds

    def delay_seconds(self, attempt: int) -> float:
        # attempt is 1-based after a failure
        delay = self.base_delay_seconds * (2 ** max(attempt - 1, 0))
        return min(delay, self.max_delay_seconds)


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    reset_seconds: float = 60.0
    _failures: int = 0
    _opened_at: float | None = None
    _lock: Lock = field(default_factory=Lock)

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if time.monotonic() - self._opened_at >= self.reset_seconds:
                self._opened_at = None
                self._failures = 0
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            return time.monotonic() - self._opened_at < self.reset_seconds
