"""Discovery chat storage for hosted tenants and the original organization schema."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.agents.discovery.service import DiscoveryService
from app.database.memory import (
    DiscoveryMessageRecord,
    DiscoverySessionRecord,
    MemoryStore,
    ProcessDefinitionRecord,
)
from app.database.postgres_persistence import (
    _load_discovery,
    _load_processes,
    persist_discovery_message,
    persist_discovery_session,
    persist_process,
)
from app.llm.client import FakeGeminiClient
from app.security.errors import AppError, NotFoundError

HOSTED_MESSAGE_COLUMNS = {
    "id",
    "tenant_id",
    "process_id",
    "session_id",
    "role",
    "content",
    "document_ids",
    "clarifying_questions",
    "intent",
    "plan_draft",
    "source_refs",
    "suspicious_flags",
    "created_by_user_id",
    "created_at",
}
HOSTED_SESSION_COLUMNS = {
    "id",
    "tenant_id",
    "process_id",
    "status",
    "created_by_user_id",
    "document_ids",
    "created_at",
    "updated_at",
}
HOSTED_PROCESS_COLUMNS = {
    "id",
    "tenant_id",
    "name",
    "description",
    "process_type",
    "status",
    "created_at",
    "updated_at",
}
ORIGINAL_MESSAGE_COLUMNS = {
    "id",
    "organization_id",
    "process_definition_id",
    "session_id",
    "role",
    "content",
    "document_ids",
    "clarifying_questions",
    "intent",
    "plan_draft",
    "source_refs",
    "suspicious_flags",
    "created_by_user_id",
    "created_at",
    "row_version",
}
ORIGINAL_SESSION_COLUMNS = {
    "id",
    "organization_id",
    "process_definition_id",
    "status",
    "created_by_user_id",
    "document_ids",
    "row_version",
    "created_at",
    "updated_at",
}


class _Result:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, object]]:
        return self._rows

    def mappings(self) -> _Result:
        return self


class _Session:
    def __init__(self, tables: dict[str, set[str]]) -> None:
        self.tables = tables
        self.statements: list[str] = []
        self.params: list[dict[str, object]] = []
        self.rows: list[dict[str, object]] = []

    def execute(self, statement: object, params: dict[str, object] | None = None) -> _Result:
        sql = str(statement)
        self.statements.append(sql)
        if params is not None:
            self.params.append(params)
        if "information_schema.columns" in sql:
            table_name = str((params or {}).get("table_name", ""))
            columns = self.tables.get(table_name, set())
            return _Result([{"column_name": name} for name in sorted(columns)])
        return _Result(self.rows)

    def merge(self, instance: object) -> None:
        self.statements.append(f"merge {type(instance).__name__}")


def _patch(monkeypatch: pytest.MonkeyPatch, session: _Session) -> None:
    @contextmanager
    def _scope():
        yield session

    monkeypatch.setattr("app.database.postgres_persistence.sync_session_scope", _scope)


def _message(
    organization_id: UUID,
    process_id: UUID,
    session_id: UUID,
    *,
    content: str,
    created_at: datetime,
) -> DiscoveryMessageRecord:
    return DiscoveryMessageRecord(
        id=uuid4(),
        organization_id=organization_id,
        process_id=process_id,
        session_id=session_id,
        role="user",
        content=content,
        document_ids=[],
        clarifying_questions=[],
        intent=None,
        plan_draft=None,
        source_refs=[],
        suspicious_flags=[],
        created_by_user_id=uuid4(),
        created_at=created_at,
    )


def _session_record(organization_id: UUID, process_id: UUID) -> DiscoverySessionRecord:
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    return DiscoverySessionRecord(
        id=uuid4(),
        organization_id=organization_id,
        process_id=process_id,
        status="active",
        created_by_user_id=uuid4(),
        document_ids=[],
        created_at=now,
        updated_at=now,
    )


def test_hosted_message_write_uses_tenant_and_process(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    process_id = uuid4()
    session = _Session(
        {
            "discovery_messages": HOSTED_MESSAGE_COLUMNS,
            "discovery_sessions": HOSTED_SESSION_COLUMNS,
        }
    )
    _patch(monkeypatch, session)
    record = _session_record(tenant_id, process_id)
    persist_discovery_session(MemoryStore(), record)
    message = _message(
        tenant_id,
        process_id,
        record.id,
        content="first",
        created_at=record.created_at,
    )
    persist_discovery_message(MemoryStore(), message)

    message_sql = next(
        sql for sql in session.statements if "insert into public.discovery_messages" in sql
    )
    assert "tenant_id" in message_sql
    assert "process_id" in message_sql
    assert "organization_id" not in message_sql
    assert "process_definition_id" not in message_sql
    message_params = session.params[-1]
    assert message_params["tenant_id"] == tenant_id
    assert message_params["process_id"] == process_id
    assert "organization_id" not in message_params


def test_original_schema_message_write_keeps_organization_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid4()
    process_id = uuid4()
    session = _Session({"discovery_messages": ORIGINAL_MESSAGE_COLUMNS})
    _patch(monkeypatch, session)
    message = _message(
        organization_id,
        process_id,
        uuid4(),
        content="original",
        created_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    persist_discovery_message(MemoryStore(), message)
    sql = next(
        item for item in session.statements if "insert into public.discovery_messages" in item
    )
    assert "organization_id" in sql
    assert "process_definition_id" in sql
    assert "tenant_id" not in sql
    assert session.params[-1]["organization_id"] == organization_id
    assert session.params[-1]["process_definition_id"] == process_id


def test_missing_discovery_table_does_not_report_a_saved_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session({})
    _patch(monkeypatch, session)
    message = _message(
        uuid4(),
        uuid4(),
        uuid4(),
        content="unsaved",
        created_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    with pytest.raises(AppError) as caught:
        persist_discovery_message(MemoryStore(), message)
    assert caught.value.code == "DISCOVERY_STORAGE_UNAVAILABLE"
    assert all("insert into public.discovery_messages" not in sql for sql in session.statements)


def test_hosted_processes_keep_tenant_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    owned_id = uuid4()
    foreign_id = uuid4()
    now = datetime(2026, 10, 9, tzinfo=UTC)
    session = _Session({"processes": HOSTED_PROCESS_COLUMNS})
    session.rows = [
        {
            "id": owned_id,
            "organization_id": tenant_id,
            "name": "Owned",
            "description": None,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": foreign_id,
            "organization_id": other_tenant_id,
            "name": "Foreign",
            "description": None,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        },
    ]
    _patch(monkeypatch, session)
    store = MemoryStore()
    _load_processes(session, store)
    assert set(store.processes) == {owned_id, foreign_id}
    assert store.processes[owned_id].organization_id == tenant_id
    assert store.processes[foreign_id].organization_id == other_tenant_id
    select_sql = next(sql for sql in session.statements if "from public.processes" in sql)
    assert "tenant_id is not null" in select_sql

    record = ProcessDefinitionRecord(
        id=uuid4(),
        organization_id=tenant_id,
        name="New discovery",
        description=None,
        status="draft",
        created_by_user_id=uuid4(),
        created_at=now,
        updated_at=now,
    )
    persist_process(store, record)
    insert_sql = next(sql for sql in session.statements if "insert into public.processes" in sql)
    assert "tenant_id" in insert_sql
    assert "organization_id" not in insert_sql
    assert session.params[-1]["tenant_id"] == tenant_id
    assert session.params[-1]["process_type"] == "discovered"
    assert "created_by" not in session.params[-1]


def test_loaded_messages_stay_in_order_inside_one_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    process_id = uuid4()
    other_process_id = uuid4()
    session_id = uuid4()
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    store = MemoryStore()
    monkeypatch.setattr("app.agents.discovery.service.get_memory_store", lambda: store)
    monkeypatch.setattr("app.repositories.memory_repos.get_memory_store", lambda: store)
    store.processes[process_id] = ProcessDefinitionRecord(
        id=process_id,
        organization_id=tenant_id,
        name="Owned",
        description=None,
        status="draft",
        created_by_user_id=None,
        created_at=now,
        updated_at=now,
    )
    store.processes[other_process_id] = ProcessDefinitionRecord(
        id=other_process_id,
        organization_id=other_tenant_id,
        name="Other",
        description=None,
        status="draft",
        created_by_user_id=None,
        created_at=now,
        updated_at=now,
    )
    later = _message(
        tenant_id,
        process_id,
        session_id,
        content="second",
        created_at=now + timedelta(minutes=5),
    )
    earlier = _message(
        tenant_id,
        process_id,
        session_id,
        content="first",
        created_at=now,
    )
    foreign = _message(
        other_tenant_id,
        other_process_id,
        uuid4(),
        content="other tenant",
        created_at=now + timedelta(minutes=1),
    )
    store.discovery_messages[later.id] = later
    store.discovery_messages[earlier.id] = earlier
    store.discovery_messages[foreign.id] = foreign

    service = DiscoveryService(tenant_id, client=FakeGeminiClient())
    messages = service.list_messages(process_id)
    assert [message.content for message in messages] == ["first", "second"]

    other = DiscoveryService(other_tenant_id, client=FakeGeminiClient())
    with pytest.raises(NotFoundError):
        other.list_messages(process_id)


def test_hosted_load_aliases_tenant_columns_and_orders_by_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    process_id = uuid4()
    session_id = uuid4()
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    first_id = uuid4()
    second_id = uuid4()
    session = _Session(
        {
            "discovery_sessions": HOSTED_SESSION_COLUMNS,
            "discovery_messages": HOSTED_MESSAGE_COLUMNS,
        }
    )
    session.rows = [
        {
            "id": second_id,
            "organization_id": tenant_id,
            "process_id": process_id,
            "session_id": session_id,
            "role": "assistant",
            "content": "second",
            "document_ids": [],
            "clarifying_questions": [],
            "intent": None,
            "plan_draft": None,
            "source_refs": [],
            "suspicious_flags": [],
            "created_by_user_id": None,
            "created_at": now + timedelta(minutes=1),
            "status": "active",
            "updated_at": now,
        },
        {
            "id": first_id,
            "organization_id": tenant_id,
            "process_id": process_id,
            "session_id": session_id,
            "role": "user",
            "content": "first",
            "document_ids": [],
            "clarifying_questions": [],
            "intent": None,
            "plan_draft": None,
            "source_refs": [],
            "suspicious_flags": [],
            "created_by_user_id": None,
            "created_at": now,
            "status": "active",
            "updated_at": now,
        },
    ]
    store = MemoryStore()
    _load_discovery(session, store)
    loaded = sorted(store.discovery_messages.values(), key=lambda item: (item.created_at, item.id))
    assert [item.content for item in loaded] == ["first", "second"]
    assert loaded[0].organization_id == tenant_id
    assert any("order by created_at asc, id asc" in sql for sql in session.statements)
    assert any("tenant_id as organization_id" in sql for sql in session.statements)


def test_original_process_table_still_uses_organization_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    session = _Session(
        {
            "process_definitions": {
                "id",
                "organization_id",
                "name",
                "status",
                "created_at",
                "updated_at",
            }
        }
    )
    _patch(monkeypatch, session)
    persist_process(
        MemoryStore(),
        ProcessDefinitionRecord(
            id=uuid4(),
            organization_id=uuid4(),
            name="Original",
            description=None,
            status="draft",
            created_by_user_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    assert any(sql == "merge ProcessDefinitionModel" for sql in session.statements)
    assert all("insert into public.processes" not in sql for sql in session.statements)


def test_hosted_discovery_migration_matches_process_ownership() -> None:
    sql = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/20261009160000_hosted_discovery_messages.sql"
    ).read_text(encoding="utf-8")
    lowered = sql.lower()
    assert "references public.organizations" not in lowered
    assert "process_definition_id" not in lowered
    assert (
        "foreign key (tenant_id, process_id) references public.processes (tenant_id, id)"
        in lowered
    )
    assert "references public.tenants (id)" in lowered
    assert "references public.processes (id) on delete cascade" in lowered
    assert "discovery_messages_tenant_process_created_idx" in lowered
    assert "insert into public.discovery" not in lowered
    assert "enable row level security" not in lowered
    assert "to_regclass('public.discovery_messages')" in lowered
