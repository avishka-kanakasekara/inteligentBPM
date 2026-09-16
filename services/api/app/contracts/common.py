"""Shared API contracts and serialization helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class APIModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        use_enum_values=True,
        ser_json_timedelta="iso8601",
    )


class ORMModel(APIModel):
    """Base for response models with UUID/datetime fields."""

    id: UUID
    created_at: datetime
    updated_at: datetime | None = None


T = TypeVar("T")


class PageMeta(APIModel):
    total: int
    limit: int
    offset: int
    sort: str | None = None
    order: str = "asc"


class Page(APIModel, Generic[T]):
    items: list[T]
    meta: PageMeta


class MessageResponse(APIModel):
    message: str
    correlation_id: str | None = None


class ErrorBody(APIModel):
    code: str
    message: str
    details: dict[str, Any] | list[Any] | None = None
    correlation_id: str | None = None


class ErrorResponse(APIModel):
    error: ErrorBody = Field(..., description="Stable error envelope")
