"""In-process metrics registry for production hardening (no container sidecars required)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Histogram:
    count: int = 0
    total: float = 0.0
    max: float = 0.0
    buckets: dict[str, int] = field(
        default_factory=lambda: {
            "le_50ms": 0,
            "le_100ms": 0,
            "le_250ms": 0,
            "le_500ms": 0,
            "le_1000ms": 0,
            "le_5000ms": 0,
            "inf": 0,
        }
    )

    def observe(self, value_ms: float) -> None:
        self.count += 1
        self.total += value_ms
        self.max = max(self.max, value_ms)
        if value_ms <= 50:
            self.buckets["le_50ms"] += 1
        elif value_ms <= 100:
            self.buckets["le_100ms"] += 1
        elif value_ms <= 250:
            self.buckets["le_250ms"] += 1
        elif value_ms <= 500:
            self.buckets["le_500ms"] += 1
        elif value_ms <= 1000:
            self.buckets["le_1000ms"] += 1
        elif value_ms <= 5000:
            self.buckets["le_5000ms"] += 1
        else:
            self.buckets["inf"] += 1

    def snapshot(self) -> dict[str, Any]:
        avg = (self.total / self.count) if self.count else 0.0
        return {
            "count": self.count,
            "sum_ms": round(self.total, 3),
            "avg_ms": round(avg, 3),
            "max_ms": round(self.max, 3),
            "buckets": dict(self.buckets),
        }


class MetricsRegistry:
    """Process-local counters and histograms — exportable via /metrics JSON."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, _Histogram] = defaultdict(_Histogram)

    def incr(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self._counters[key] += value

    def set(self, name: str, value: float, **labels: str) -> None:
        """Set a gauge-like counter (e.g. backlog depth)."""
        key = _metric_key(name, labels)
        with self._lock:
            self._counters[key] = value

    def observe(self, name: str, value_ms: float, **labels: str) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self._histograms[key].observe(value_ms)

    def timer(self, name: str, **labels: str) -> "_Timer":
        return _Timer(self, name, labels)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "histograms": {k: v.snapshot() for k, v in self._histograms.items()},
                "generated_at": time.time(),
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()


def _metric_key(name: str, labels: dict[str, str]) -> str:
    if not labels:
        return name
    parts = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}{{{parts}}}"


class _Timer:
    def __init__(self, registry: MetricsRegistry, name: str, labels: dict[str, str]) -> None:
        self.registry = registry
        self.name = name
        self.labels = labels
        self._start = 0.0

    def __enter__(self) -> "_Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        self.registry.observe(self.name, elapsed_ms, **self.labels)


# Canonical metric names (match alert rules)
M_API_LATENCY = "api_latency_ms"
M_API_REQUESTS = "api_requests_total"
M_API_ERRORS = "api_errors_total"
M_AGENT_LATENCY = "agent_latency_ms"
M_GEMINI_REQUESTS = "gemini_requests_total"
M_GEMINI_FAILURES = "gemini_failures_total"
M_TOKEN_USAGE = "gemini_tokens_total"
M_PROCESS_RUNS = "process_runs_total"
M_PROCESS_FAILURES = "process_failures_total"
M_APPROVAL_WAIT = "approval_wait_ms"
M_TOOL_SUCCESS = "tool_success_total"
M_TOOL_FAILURE = "tool_failure_total"
M_EMAIL_FAILURES = "email_failures_total"
M_QUOTE_CONFIDENCE = "quote_extraction_confidence"
M_CROSS_TENANT = "cross_tenant_authz_failures_total"
M_PLAN_LIMIT = "plan_limit_violations_total"
M_WORKER_BACKLOG = "worker_backlog"
M_APPROVAL_BACKLOG = "approval_backlog"

metrics = MetricsRegistry()
