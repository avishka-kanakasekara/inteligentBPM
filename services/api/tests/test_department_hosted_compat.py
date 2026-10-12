"""Department columns: hosted tenant_id schema and repository organization_id schema."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from app.database.memory import DepartmentRecord, MemoryStore
from app.database.postgres_persistence import _load_departments, persist_department
from app.repositories.memory_repos import DepartmentRepository

HOSTED_COLUMNS = {
    "id",
    "tenant_id",
    "name",
    "code",
    "manager_employee_id",
    "status",
    "created_at",
    "updated_at",
}
ORIGINAL_COLUMNS = {
    "id",
    "organization_id",
    "name",
    "code",
    "parent_department_id",
    "manager_employee_id",
    "status",
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
    def __init__(self, columns: set[str]) -> None:
        self.columns = columns
        self.statements: list[str] = []
        self.params: list[dict[str, object]] = []

    def execute(self, statement: object, params: dict[str, object] | None = None) -> _Result:
        sql = str(statement)
        self.statements.append(sql)
        if params is not None:
            self.params.append(params)
        if "information_schema.columns" in sql:
            return _Result([{"column_name": name} for name in sorted(self.columns)])
        return _Result([])


def _record(organization_id, *, parent_department_id=None) -> DepartmentRecord:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    return DepartmentRecord(
        id=uuid4(),
        organization_id=organization_id,
        name="Finance",
        code="FIN",
        status="active",
        created_at=now,
        updated_at=now,
        parent_department_id=parent_department_id,
    )


def _patch(monkeypatch, session: _Session) -> None:
    @contextmanager
    def _scope():
        yield session

    monkeypatch.setattr("app.database.postgres_persistence.sync_session_scope", _scope)


def test_hosted_departments_skip_missing_parent_column(monkeypatch) -> None:
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    department_id = uuid4()
    manager_id = uuid4()
    now = datetime(2026, 10, 9, tzinfo=UTC)
    session = _Session(HOSTED_COLUMNS)
    store = MemoryStore()
    rows = [
        {
            "id": department_id,
            "organization_id": tenant_id,
            "name": "Finance",
            "code": "FIN",
            "manager_employee_id": manager_id,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": uuid4(),
            "organization_id": other_tenant_id,
            "name": "Other",
            "code": "OTH",
            "manager_employee_id": None,
            "status": "inactive",
            "created_at": now,
            "updated_at": now,
        },
    ]

    def execute(statement, params=None):
        sql = str(statement)
        session.statements.append(sql)
        if params is not None:
            session.params.append(params)
        if "information_schema.columns" in sql:
            return _Result([{"column_name": name} for name in sorted(HOSTED_COLUMNS)])
        return _Result(rows)

    session.execute = execute
    _load_departments(session, store)
    select_sql = session.statements[-1]
    assert "tenant_id as organization_id" in select_sql
    assert "parent_department_id" not in select_sql
    assert "row_version" not in select_sql
    visible = DepartmentRepository(tenant_id, store).list_all()
    assert [row.id for row in visible] == [department_id]
    assert visible[0].organization_id == tenant_id
    assert visible[0].parent_department_id is None
    assert visible[0].manager_employee_id == manager_id
    assert visible[0].status == "active"
    assert DepartmentRepository(other_tenant_id, store).list_all()[0].status == "inactive"

    record = _record(tenant_id, parent_department_id=uuid4())
    _patch(monkeypatch, session)
    persist_department(store, record)
    insert_sql = session.statements[-1]
    assert "insert into public.departments (id, tenant_id, name" in insert_sql
    assert "parent_department_id" not in insert_sql
    assert "row_version" not in insert_sql
    assert session.params[-1]["organization_id"] == tenant_id
    assert "parent_department_id" not in session.params[-1]
    assert session.params[-1]["status"] == "active"


def test_repository_departments_keep_original_columns(monkeypatch) -> None:
    organization_id = uuid4()
    department_id = uuid4()
    parent_id = uuid4()
    now = datetime(2026, 10, 9, tzinfo=UTC)
    session = _Session(ORIGINAL_COLUMNS)
    store = MemoryStore()

    def execute(statement, params=None):
        sql = str(statement)
        session.statements.append(sql)
        if params is not None:
            session.params.append(params)
        if "information_schema.columns" in sql:
            return _Result([{"column_name": name} for name in sorted(ORIGINAL_COLUMNS)])
        if sql.startswith("select"):
            return _Result(
                [
                    {
                        "id": department_id,
                        "organization_id": organization_id,
                        "name": "Operations",
                        "code": "OPS",
                        "parent_department_id": parent_id,
                        "manager_employee_id": None,
                        "status": "active",
                        "row_version": 1,
                        "created_at": now,
                        "updated_at": now,
                    }
                ]
            )
        return _Result([])

    session.execute = execute
    _load_departments(session, store)
    select_sql = session.statements[-1]
    assert "organization_id as organization_id" in select_sql
    assert "parent_department_id" in select_sql
    assert "tenant_id" not in select_sql
    loaded = DepartmentRepository(organization_id, store).list_all()[0]
    assert loaded.name == "Operations"
    assert loaded.parent_department_id == parent_id
    assert DepartmentRepository(uuid4(), store).list_all() == []

    record = _record(organization_id, parent_department_id=parent_id)
    _patch(monkeypatch, session)
    persist_department(store, record)
    insert_sql = session.statements[-1]
    assert "id, organization_id, name" in insert_sql
    assert "parent_department_id" in insert_sql
    assert "tenant_id" not in insert_sql
    assert session.params[-1]["parent_department_id"] == parent_id
    assert session.params[-1]["organization_id"] == organization_id
