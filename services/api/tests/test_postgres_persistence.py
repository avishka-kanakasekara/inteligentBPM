"""Postgres-backed persistence integration tests."""

from __future__ import annotations

import os
from uuid import UUID

import pytest

from app.config import reset_settings_cache
from app.database.memory import initialize_postgres_persistence, reset_memory_store
from app.database.postgres_persistence import bootstrap_organization
from app.database.sync_pg import init_sync_engine
from app.repositories.memory_repos import ProcessRepository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")
def test_processes_survive_memory_reset() -> None:
    reset_settings_cache()
    os.environ["PERSISTENCE_MODE"] = "postgres"
    os.environ["APP_ENV"] = "local"

    org_id = UUID("76ec608f-37a4-45fa-bb58-fb81c0710720")
    user_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    reset_memory_store()
    init_sync_engine()
    bootstrap_organization(
        organization_id=org_id,
        user_id=user_id,
        name="Acme Corporation",
        slug="acme-corporation",
    )
    initialize_postgres_persistence()

    created = ProcessRepository(org_id).create(
        name="Postgres persistence test",
        description="survives restart",
        created_by_user_id=user_id,
    )

    reset_memory_store()
    init_sync_engine()
    initialize_postgres_persistence()

    names = [p.name for p in ProcessRepository(org_id).list_all()]
    assert created.name in names
