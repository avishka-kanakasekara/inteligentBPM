"""Error tracking sink — captures sanitized exceptions for operators."""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.security.log_filter import sanitize_for_log


@dataclass
class TrackedError:
    id: str
    at: float
    error_type: str
    message: str
    path: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    organization_id: str | None = None
    stack: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class ErrorTracker:
    def __init__(self, *, capacity: int = 500) -> None:
        self._events: deque[TrackedError] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def capture(
        self,
        exc: BaseException,
        *,
        path: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
        organization_id: str | None = None,
        extras: dict[str, Any] | None = None,
    ) -> TrackedError:
        with self._lock:
            self._seq += 1
            event = TrackedError(
                id=f"err-{self._seq}",
                at=time.time(),
                error_type=exc.__class__.__name__,
                message=str(exc)[:500],
                path=path,
                correlation_id=correlation_id,
                trace_id=trace_id,
                organization_id=organization_id,
                stack="".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[
                    :4000
                ],
                extras=sanitize_for_log(extras or {}),
            )
            self._events.append(event)
            return event

    def recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._events)[-limit:]
        return [
            {
                "id": e.id,
                "at": e.at,
                "error_type": e.error_type,
                "message": e.message,
                "path": e.path,
                "correlation_id": e.correlation_id,
                "trace_id": e.trace_id,
                "organization_id": e.organization_id,
            }
            for e in reversed(items)
        ]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


error_tracker = ErrorTracker()
