"""Pagination, filtering, and sorting helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

from app.contracts.common import Page, PageMeta

T = TypeVar("T")


class ListParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    sort: str | None = None
    order: str = Field(default="asc", pattern="^(asc|desc)$")
    q: str | None = None
    status: str | None = None


def list_params(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str | None = Query(None),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    q: str | None = Query(None),
    status: str | None = Query(None),
) -> ListParams:
    return ListParams(limit=limit, offset=offset, sort=sort, order=order, q=q, status=status)


def apply_list(
    items: Sequence[T],
    params: ListParams,
    *,
    search_fields: Sequence[Callable[[T], str | None]] | None = None,
    status_getter: Callable[[T], str] | None = None,
    sort_fields: dict[str, Callable[[T], Any]] | None = None,
) -> Page[T]:
    filtered: list[T] = list(items)

    if params.status and status_getter is not None:
        filtered = [item for item in filtered if status_getter(item) == params.status]

    if params.q and search_fields:
        needle = params.q.lower()
        filtered = [
            item
            for item in filtered
            if any(
                (field(item) or "").lower().find(needle) >= 0 for field in search_fields
            )
        ]

    sort_fields = sort_fields or {}
    if params.sort and params.sort in sort_fields:
        reverse = params.order == "desc"
        filtered.sort(key=sort_fields[params.sort], reverse=reverse)

    total = len(filtered)
    page_items = filtered[params.offset : params.offset + params.limit]
    return Page(
        items=page_items,
        meta=PageMeta(
            total=total,
            limit=params.limit,
            offset=params.offset,
            sort=params.sort,
            order=params.order,
        ),
    )


def iter_values(mapping: dict[Any, T]) -> Iterable[T]:
    return mapping.values()
