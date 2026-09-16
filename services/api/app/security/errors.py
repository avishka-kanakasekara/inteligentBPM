"""Application-level exceptions with stable error codes."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 400,
        details: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", *, code: str = "NOT_FOUND") -> None:
        super().__init__(message, code=code, status_code=404)


class ConflictError(AppError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "CONFLICT",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=409, details=details)


class ValidationAppError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | list[Any] | None = None) -> None:
        super().__init__(message, code="VALIDATION_ERROR", status_code=422, details=details)
