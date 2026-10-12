"""Organization creation against hosted tenants and the original organizations table."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database.memory import MemoryStore, OrganizationRecord, get_memory_store
from app.database.postgres_persistence import persist_organization
from app.repositories.memory_repos import OrganizationRepository
from app.security.errors import AppError
from tests.conftest import make_token


_HOSTED_TENANT_COLUMNS = (
    "id",
    "code",
    "name",
    "is_active",
    "created_at",
    "updated_at",
)
_HOSTED_MEMBERSHIP_COLUMNS = (
    "id",
    "tenant_id",
    "user_id",
    "role",
    "status",
    "created_at",
    "updated_at",
)


class _Rows:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value

    def all(self) -> list[object]:
        if isinstance(self._value, list):
            return self._value
        return []


class _Nested:
    def __enter__(self) -> _Nested:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class _Session:
    def __init__(
        self,
        *,
        organizations: bool,
        hosted: bool = False,
        fail_membership: bool = False,
    ) -> None:
        self.organizations = organizations
        self.hosted = hosted
        self.fail_membership = fail_membership
        self.statements: list[str] = []
        self.params: list[dict[str, object]] = []
        self.events: list[str] = []
        self.merged: list[object] = []

    def execute(self, statement: object, params: dict[str, object] | None = None) -> _Rows:
        sql = str(statement)
        self.statements.append(sql)
        self.events.append(sql)
        if params is not None:
            self.params.append(params)
        if self.fail_membership and "insert into public.tenant_memberships" in sql:
            raise RuntimeError("membership failed")
        if "to_regclass" in sql:
            name = str((params or {}).get("qualified", "")).split(".", 1)[-1]
            present = name == "organizations" and self.organizations
            present = present or (self.hosted and name in {"tenants", "tenant_memberships"})
            return _Rows(name if present else None)
        if "information_schema.columns" in sql and self.hosted:
            table_name = str((params or {}).get("table_name", ""))
            columns = {
                "tenants": _HOSTED_TENANT_COLUMNS,
                "tenant_memberships": _HOSTED_MEMBERSHIP_COLUMNS,
            }.get(table_name, ())
            return _Rows([{"column_name": column} for column in columns])
        return _Rows(None)

    def begin_nested(self) -> _Nested:
        return _Nested()

    def merge(self, record: object) -> None:
        self.merged.append(record)

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


def _patch_session(monkeypatch, session: _Session) -> None:
    @contextmanager
    def _scope():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    monkeypatch.setattr("app.database.postgres_persistence.sync_session_scope", _scope)


def _enable_postgres(monkeypatch) -> None:
    monkeypatch.setattr("app.database.memory._POSTGRES_PERSISTENCE_ENABLED", True)


def _record() -> OrganizationRecord:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    return OrganizationRecord(
        id=uuid4(),
        name="Finance Workspace",
        slug="finance-workspace",
        plan_code="pro",
        status="active",
        row_version=1,
        created_at=now,
        updated_at=now,
    )


def test_hosted_create_returns_error_without_writes(
    client: TestClient,
    monkeypatch,
    user_a_id,
) -> None:
    _enable_postgres(monkeypatch)
    session = _Session(organizations=False)
    _patch_session(monkeypatch, session)
    store = get_memory_store()
    organizations = set(store.organizations)
    memberships = set(store.memberships)

    response = client.post(
        "/v1/organizations",
        headers={"Authorization": f"Bearer {make_token(user_a_id)}"},
        json={"name": "New Workspace", "plan_code": "pro"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ORGANIZATION_CREATE_UNSUPPORTED"
    assert "No workspace or membership was written." in response.json()["error"]["message"]
    assert set(store.organizations) == organizations
    assert set(store.memberships) == memberships
    assert session.merged == []
    assert not any("insert into" in sql.lower() for sql in session.statements)
    listed = client.get(
        "/v1/auth/organizations",
        headers={"Authorization": f"Bearer {make_token(user_a_id)}"},
    )
    assert listed.status_code == 200
    assert listed.json() == []
    assert listed.headers["x-organization-create-supported"] == "false"


def test_hosted_persist_organization_does_not_touch_organizations(monkeypatch) -> None:
    session = _Session(organizations=False)
    _patch_session(monkeypatch, session)
    try:
        persist_organization(get_memory_store(), _record())
    except AppError as exc:
        assert exc.code == "ORGANIZATION_CREATE_UNSUPPORTED"
        assert exc.status_code == 422
    else:
        raise AssertionError("hosted organization persist should fail closed")
    assert session.merged == []
    assert all("insert" not in sql.lower() for sql in session.statements)


def test_original_schema_persist_organization_still_merges(monkeypatch) -> None:
    session = _Session(organizations=True)
    _patch_session(monkeypatch, session)
    record = _record()
    persist_organization(get_memory_store(), record)
    assert len(session.merged) == 1
    merged = session.merged[0]
    assert merged.id == record.id
    assert merged.name == "Finance Workspace"
    assert merged.plan_code == "pro"


def test_original_schema_organization_list_allows_creation(
    client: TestClient,
    monkeypatch,
    user_a_id,
) -> None:
    _enable_postgres(monkeypatch)
    session = _Session(organizations=True)
    _patch_session(monkeypatch, session)
    listed = client.get(
        "/v1/auth/organizations",
        headers={"Authorization": f"Bearer {make_token(user_a_id)}"},
    )
    assert listed.status_code == 200
    assert listed.headers["x-organization-create-supported"] == "true"


def test_hosted_workspace_create_adds_owner_membership(
    client: TestClient,
    monkeypatch,
    user_a_id,
) -> None:
    _enable_postgres(monkeypatch)
    session = _Session(organizations=False, hosted=True)
    _patch_session(monkeypatch, session)
    store = get_memory_store()
    existing_id = uuid4()
    now = datetime(2026, 10, 9, tzinfo=UTC)
    store.organizations[existing_id] = OrganizationRecord(
        id=existing_id,
        name="Existing",
        slug="existing",
        plan_code="",
        status="active",
        row_version=1,
        created_at=now,
        updated_at=now,
    )

    response = client.post(
        "/v1/organizations",
        headers={"Authorization": f"Bearer {make_token(user_a_id, email='owner@example.com')}"},
        json={"name": "Northwind", "plan_code": "pro"},
    )

    assert response.status_code == 201
    created_id = response.json()["id"]
    assert created_id != str(existing_id)
    tenant_sql = next(sql for sql in session.statements if "insert into public.tenants" in sql)
    membership_sql = next(
        sql for sql in session.statements if "insert into public.tenant_memberships" in sql
    )
    assert "plan" not in tenant_sql
    assert "email" not in tenant_sql.lower()
    assert "email" not in membership_sql.lower()
    tenant_params = next(params for params in session.params if params.get("name") == "Northwind")
    assert tenant_params["code"] == "northwind"
    assert tenant_params["is_active"] is True
    membership_params = next(params for params in session.params if params.get("user_id") == user_a_id)
    assert membership_params["tenant_id"] != existing_id
    assert str(membership_params["tenant_id"]) == created_id
    assert membership_params["role"] == "owner"
    assert membership_params["status"] == "active"
    assert session.events.index(tenant_sql) < session.events.index(membership_sql)
    assert session.events.index(membership_sql) < session.events.index(
        "commit",
        session.events.index(membership_sql),
    )
    listed = client.get(
        "/v1/auth/organizations",
        headers={"Authorization": f"Bearer {make_token(user_a_id)}"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [created_id]
    assert listed.headers["x-organization-create-supported"] == "true"
    assert all(item.organization_id != existing_id for item in store.memberships.values())


def test_hosted_workspace_create_rolls_back_when_membership_fails(monkeypatch) -> None:
    _enable_postgres(monkeypatch)
    session = _Session(organizations=False, hosted=True, fail_membership=True)
    _patch_session(monkeypatch, session)
    store = MemoryStore()
    try:
        OrganizationRepository(store).create(
            name="Northwind",
            plan_code="pro",
            owner_user_id=uuid4(),
        )
    except RuntimeError as exc:
        assert str(exc) == "membership failed"
    else:
        raise AssertionError("membership failure should abort workspace creation")
    assert store.organizations == {}
    assert store.memberships == {}
    membership_sql = next(
        sql for sql in session.statements if "insert into public.tenant_memberships" in sql
    )
    assert any("insert into public.tenants" in event for event in session.events)
    assert "commit" not in session.events[session.events.index(membership_sql) :]
    assert "rollback" in session.events[session.events.index(membership_sql) :]


def test_organization_create_requires_authentication(
    client: TestClient,
    monkeypatch,
) -> None:
    _enable_postgres(monkeypatch)
    session = _Session(organizations=False, hosted=True)
    _patch_session(monkeypatch, session)
    response = client.post(
        "/v1/organizations",
        headers={"Authorization": "Bearer not-a-token"},
        json={"name": "Northwind", "plan_code": "pro"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"
    assert not any("insert into" in sql.lower() for sql in session.statements)


def test_original_schema_create_does_not_write_tenants(
    client: TestClient,
    monkeypatch,
    user_a_id,
) -> None:
    _enable_postgres(monkeypatch)
    session = _Session(organizations=True)
    _patch_session(monkeypatch, session)
    response = client.post(
        "/v1/organizations",
        headers={"Authorization": f"Bearer {make_token(user_a_id)}"},
        json={"name": "Acme Books", "plan_code": "enterprise"},
    )
    assert response.status_code == 201
    assert response.json()["plan_code"] == "enterprise"
    assert not any("public.tenants" in sql for sql in session.statements)
    assert session.merged == []


def test_memory_organization_list_allows_creation(client: TestClient, user_a_id) -> None:
    listed = client.get(
        "/v1/auth/organizations",
        headers={"Authorization": f"Bearer {make_token(user_a_id)}"},
    )
    assert listed.status_code == 200
    assert listed.json() == []
    assert listed.headers["x-organization-create-supported"] == "true"


def test_memory_mode_organization_create_unchanged(monkeypatch) -> None:
    monkeypatch.setattr("app.database.memory._POSTGRES_PERSISTENCE_ENABLED", False)
    store = MemoryStore()
    owner_id = uuid4()
    created = OrganizationRepository(store).create(
        name="Memory Org",
        plan_code="enterprise",
        owner_user_id=owner_id,
    )
    assert store.organizations[created.id].plan_code == "enterprise"
    assert any(
        membership.organization_id == created.id and membership.user_id == owner_id
        for membership in store.memberships.values()
    )
