"""Demo process seed tests."""

from __future__ import annotations

from uuid import UUID

from app.database.memory import reset_memory_store
from app.database.seed_demo import DEFAULT_ORG_ID, DEFAULT_USER_ID, seed_demo_processes
from app.repositories.memory_repos import ProcessRepository


def test_seed_demo_processes_is_idempotent() -> None:
    reset_memory_store()
    seed_demo_processes()
    seed_demo_processes()

    repo = ProcessRepository(DEFAULT_ORG_ID)
    processes = repo.list_all()
    assert len(processes) == 1
    assert processes[0].name == "Laptop procurement"

    versions = repo.list_versions(processes[0].id)
    assert len(versions) == 1
    assert versions[0].status == "draft"
    assert versions[0].plan_snapshot.get("goal")


def test_seed_demo_processes_creates_discovery_chat() -> None:
    reset_memory_store()
    seed_demo_processes()

    from app.agents.discovery.service import DiscoveryService

    service = DiscoveryService(DEFAULT_ORG_ID)
    process_id = ProcessRepository(DEFAULT_ORG_ID).list_all()[0].id
    messages = service.list_messages(process_id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].created_by_user_id == DEFAULT_USER_ID
