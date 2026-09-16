"""Billing package — import concrete modules directly to avoid circular imports."""

from __future__ import annotations

from typing import Any

__all__ = [
    "BillingService",
    "EntitlementDenied",
    "EntitlementService",
    "LimitExceeded",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from app.billing import service as _service

        return getattr(_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
