"""Small helpers to persist in-place record mutations when using Postgres mode."""

from __future__ import annotations

from uuid import UUID

from app.config import get_settings
from app.database.memory import MemoryStore
from app.database.postgres_persistence import persist_mutation


def persist_if_postgres(store: MemoryStore, collection: str, record_id: UUID) -> None:
    if get_settings().persistence_mode == "postgres":
        persist_mutation(store, collection, record_id)
