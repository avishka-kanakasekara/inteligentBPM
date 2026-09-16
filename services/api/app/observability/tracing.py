"""Lightweight distributed tracing (W3C traceparent) without container agents."""

from __future__ import annotations

import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from app.security.log_filter import sanitize_for_log

_current_span: ContextVar["Span | None"] = ContextVar("bpm_span", default=None)


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    started_at: float = field(default_factory=time.perf_counter)
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None

    def end(self) -> dict[str, Any]:
        duration_ms = (time.perf_counter() - self.started_at) * 1000
        return sanitize_for_log(
            {
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_span_id": self.parent_span_id,
                "name": self.name,
                "duration_ms": round(duration_ms, 3),
                "status": self.status,
                "error": self.error,
                "attributes": self.attributes,
            }
        )


def _new_id(nbytes: int = 8) -> str:
    return secrets.token_hex(nbytes)


def parse_traceparent(header: str | None) -> tuple[str, str] | None:
    """Parse W3C traceparent: version-traceid-spanid-flags."""
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) != 4:
        return None
    _version, trace_id, parent_id, _flags = parts
    if len(trace_id) != 32 or len(parent_id) != 16:
        return None
    return trace_id, parent_id


def format_traceparent(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"


@contextmanager
def start_span(name: str, *, traceparent: str | None = None, **attributes: Any) -> Iterator[Span]:
    parent = _current_span.get()
    parsed = parse_traceparent(traceparent)
    if parent:
        trace_id = parent.trace_id
        parent_id = parent.span_id
    elif parsed:
        trace_id, parent_id = parsed
    else:
        trace_id = _new_id(16)
        parent_id = None
    span = Span(
        trace_id=trace_id,
        span_id=_new_id(8),
        parent_span_id=parent_id,
        name=name,
        attributes=dict(attributes),
    )
    token = _current_span.set(span)
    try:
        yield span
    except Exception as exc:  # noqa: BLE001
        span.status = "error"
        span.error = exc.__class__.__name__
        raise
    finally:
        _current_span.reset(token)


def current_trace_id() -> str | None:
    span = _current_span.get()
    return span.trace_id if span else None
