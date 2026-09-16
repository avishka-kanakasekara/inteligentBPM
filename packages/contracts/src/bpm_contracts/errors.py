"""Structured API error contracts."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | list[Any] | None = None
    correlation_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody = Field(..., description="Stable error envelope")
