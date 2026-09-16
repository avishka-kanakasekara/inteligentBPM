"""In-process rate limiting and login-abuse protection (Redis optional, no Docker)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Deque

from app.security.errors import AppError


class RateLimitExceeded(AppError):
    def __init__(self, message: str = "Rate limit exceeded", *, retry_after: float = 1.0) -> None:
        super().__init__(
            message,
            code="RATE_LIMITED",
            status_code=429,
            details={"retry_after_seconds": retry_after},
        )
        self.retry_after = retry_after


@dataclass
class _Bucket:
    events: Deque[float] = field(default_factory=deque)


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window limiter suitable for single-process / native workers."""

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = defaultdict(_Bucket)
        self._lock = Lock()

    def hit(self, key: str, *, limit: int, window_seconds: float) -> tuple[bool, float]:
        """
        Record a hit. Returns (allowed, retry_after_seconds).
        """
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets[key]
            cutoff = now - window_seconds
            while bucket.events and bucket.events[0] < cutoff:
                bucket.events.popleft()
            if len(bucket.events) >= limit:
                retry_after = max(0.1, window_seconds - (now - bucket.events[0]))
                return False, retry_after
            bucket.events.append(now)
            return True, 0.0

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)


# Process-wide limiters
api_rate_limiter = SlidingWindowRateLimiter()
login_abuse_limiter = SlidingWindowRateLimiter()


@dataclass
class LoginAbuseProtector:
    """
    Protect authentication surfaces from credential stuffing / brute force.

    Tracks failed auth attempts by client IP (and optional subject).
    """

    max_failures: int = 10
    window_seconds: float = 300.0
    lockout_seconds: float = 900.0
    _failures: dict[str, _Bucket] = field(default_factory=lambda: defaultdict(_Bucket))
    _lockouts: dict[str, float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def assert_allowed(self, client_key: str) -> None:
        now = time.monotonic()
        with self._lock:
            until = self._lockouts.get(client_key)
            if until and until > now:
                raise RateLimitExceeded(
                    "Too many failed authentication attempts; try again later",
                    retry_after=until - now,
                )
            if until and until <= now:
                self._lockouts.pop(client_key, None)

    def record_failure(self, client_key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._failures[client_key]
            cutoff = now - self.window_seconds
            while bucket.events and bucket.events[0] < cutoff:
                bucket.events.popleft()
            bucket.events.append(now)
            if len(bucket.events) >= self.max_failures:
                self._lockouts[client_key] = now + self.lockout_seconds

    def record_success(self, client_key: str) -> None:
        with self._lock:
            self._failures.pop(client_key, None)
            self._lockouts.pop(client_key, None)


login_abuse_protector = LoginAbuseProtector()
