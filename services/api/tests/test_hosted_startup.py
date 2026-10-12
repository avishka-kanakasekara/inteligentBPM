"""Startup and authorization behavior when hosted organization tables are absent."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from app.config import reset_settings_cache
from app.database.memory import EmployeeRecord, MemoryStore, get_memory_store, reset_memory_store
from app.database.models import EmployeeModel, TenantMembershipModel, TenantModel
from app.database.postgres_persistence import bootstrap_organization, hydrate_store
from app.repositories.memory_repos import EmployeeRepository
from tests.conftest import make_token


class _Orig(Exception):
    sqlstate = "42P01"


class _Rows:
    def __init__(self, value: object) -> None:
        self._value = value

    def all(self) -> object:
        return self._value

    def scalar_one(self) -> object:
        return self._value


class _Session:
    def __init__(self, action: object) -> None:
        self.action = action
        self.calls: list[str] = []

    def scalars(self, statement: object) -> object:
        self.calls.append(str(statement))
        if isinstance(self.action, Exception):
            raise self.action
        return self.action

    def execute(self, statement: object, params: dict[str, str] | None = None) -> object:
        sql = str(statement)
        self.calls.append(sql)
        if "to_regclass" in sql:
            name = (params or {})["qualified"].split(".", 1)[1]
            present = self.action if isinstance(self.action, set) else set()
            return _Rows(name if name in present else None)
        if isinstance(self.action, Exception):
            raise self.action
        return self.action if not isinstance(self.action, set) else _Rows(None)


def _missing(name: str) -> ProgrammingError:
    return ProgrammingError(
        f"select {name}",
        {},
        _Orig(f'relation "public.{name}" does not exist'),
    )


def _patch_sessions(monkeypatch: pytest.MonkeyPatch, sessions: list[_Session]) -> None:
    @contextmanager
    def _scope():
        try:
            yield sessions.pop(0)
        except Exception:
            raise

    monkeypatch.setattr("app.database.postgres_persistence.sync_session_scope", _scope)


def _employee_model(tenant_id):
    now = datetime.now(UTC)
    return EmployeeModel(
        id=uuid4(),
        organization_id=tenant_id,
        employee_code="E-001",
        full_name="Ada Lovelace",
        email="ada@example.com",
        phone=None,
        department_id=None,
        role_id=None,
        manager_employee_id=None,
        status="active",
        is_manager=False,
        employment_type="full_time",
        reporting_level=1,
        primary_skills=[],
        secondary_skills=[],
        skill_level="intermediate",
        availability_percent=100,
        weekly_capacity_hours=40,
        baseline_workload_percent=0,
        current_workload_percent=0,
        cost_per_hour=0,
        max_allocation_percent=100,
        approval_authority_limit=None,
        approval_tier="none",
        created_at=now,
        updated_at=now,
    )


def _employee_record(tenant_id, *, email: str = "ada@example.com") -> EmployeeRecord:
    now = datetime.now(UTC)
    return EmployeeRecord(
        id=uuid4(),
        organization_id=tenant_id,
        full_name="Ada Lovelace",
        email=email,
        title=None,
        department_id=None,
        is_manager=False,
        status="active",
        created_at=now,
        updated_at=now,
        employee_code="E-001",
    )


def test_bootstrap_does_not_insert_when_organization_tables_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session(set())
    _patch_sessions(monkeypatch, [session])
    bootstrap_organization(
        organization_id=uuid4(),
        user_id=uuid4(),
        name="Acme Corporation",
        slug="acme-corporation",
    )
    assert session.calls == ["select to_regclass(:qualified)"]
    assert all("INSERT" not in call.upper() for call in session.calls)


def test_bootstrap_inserts_when_organization_tables_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session({"organizations", "organization_memberships"})
    _patch_sessions(monkeypatch, [session])
    bootstrap_organization(
        organization_id=uuid4(),
        user_id=uuid4(),
        name="Acme Corporation",
        slug="acme-corporation",
    )
    assert sum("to_regclass" in call for call in session.calls) == 2
    assert sum("INSERT" in call.upper() for call in session.calls) == 2


def test_hydrate_loads_employees_when_catalog_tables_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    row = _employee_model(tenant_id)
    sessions = [
        _Session(_missing("organizations")),
        _Session(_missing("organization_memberships")),
        _Session(_missing("tenants")),
        _Session(_missing("tenant_memberships")),
        _Session(_Rows([(row, "analyst", tenant_id)])),
        _Session(_missing("departments")),
    ]
    _patch_sessions(monkeypatch, sessions)
    store = MemoryStore()
    hydrate_store(store)
    assert store.organizations == {}
    assert store.memberships == {}
    assert store.departments == {}
    loaded = EmployeeRepository(tenant_id, store).list_all()
    assert [employee.id for employee in loaded] == [row.id]
    assert loaded[0].role_code == "analyst"
    assert EmployeeRepository(uuid4(), store).list_all() == []


def test_unrelated_catalog_error_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    row = _employee_model(tenant_id)
    sessions = [
        _Session(_missing("organizations")),
        _Session(_missing("organization_memberships")),
        _Session(_missing("tenants")),
        _Session(_missing("tenant_memberships")),
        _Session(_Rows([(row, "analyst", tenant_id)])),
        _Session(RuntimeError("departments schema mismatch")),
    ]
    _patch_sessions(monkeypatch, sessions)
    store = MemoryStore()
    with pytest.raises(RuntimeError, match="departments schema mismatch"):
        hydrate_store(store)
    assert [employee.id for employee in store.employees.values()] == [row.id]


def test_local_startup_skips_demo_writes_without_organization_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("PERSISTENCE_MODE", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/bpm")
    monkeypatch.setenv("BPM_LOAD_DOTENV", "0")
    monkeypatch.setenv("SKIP_DEPENDENCY_CHECKS", "true")
    reset_settings_cache()
    reset_memory_store()
    calls: list[str] = []
    monkeypatch.setattr(
        "app.database.postgres_persistence.organization_directory_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.database.postgres_persistence.bootstrap_organization",
        lambda **_kwargs: calls.append("bootstrap"),
    )
    monkeypatch.setattr(
        "app.database.memory.initialize_postgres_persistence",
        lambda: calls.append("hydrate"),
    )
    monkeypatch.setattr(
        "app.database.seed_company.seed_sample_company",
        lambda *_args, **_kwargs: calls.append("seed"),
    )
    from app.main import create_app

    with TestClient(create_app()):
        pass
    assert calls == ["hydrate"]
    reset_memory_store()
    reset_settings_cache()


def _membership(
    tenant_id,
    user_id,
    *,
    role: str = "owner",
    status: str = "active",
) -> TenantMembershipModel:
    now = datetime.now(UTC)
    return TenantMembershipModel(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        status=status,
        created_at=now,
        updated_at=now,
    )


def _hydrate_hosted(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenants: list[TenantModel],
    memberships: list[TenantMembershipModel],
    employees: list[tuple[EmployeeModel, str, object]],
) -> None:
    _patch_sessions(
        monkeypatch,
        [
            _Session(_missing("organizations")),
            _Session(_missing("organization_memberships")),
            _Session(_Rows(tenants)),
            _Session(_Rows(memberships)),
            _Session(_Rows(employees)),
            _Session(_missing("departments")),
        ],
    )
    hydrate_store(get_memory_store())


def test_migration_creates_membership_without_backfill_or_rls() -> None:
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/20261009140000_tenant_memberships.sql"
    ).read_text(encoding="utf-8")
    lowered = sql.lower()
    assert "create table public.tenant_memberships" in lowered
    assert "references public.tenants (id) on delete restrict" in lowered
    assert "unique (tenant_id, user_id)" in lowered
    assert "on public.tenant_memberships (user_id, status)" in lowered
    assert "references public.users" not in lowered
    assert "references auth.users" not in lowered
    assert "insert into" not in lowered
    assert "enable row level security" not in lowered


def test_active_membership_permits_only_that_tenant(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    other_tenant = uuid4()
    user_id = uuid4()
    local = _employee_model(tenant_id)
    foreign = _employee_model(other_tenant)
    foreign.email = "foreign@example.com"
    _hydrate_hosted(
        monkeypatch,
        tenants=[TenantModel(id=tenant_id), TenantModel(id=other_tenant)],
        memberships=[_membership(tenant_id, user_id, role="employee")],
        employees=[(local, "analyst", tenant_id), (foreign, "analyst", other_tenant)],
    )
    response = client.get(
        "/v1/employees",
        headers={
            "Authorization": f"Bearer {make_token(user_id, email=local.email)}",
            "X-Organization-Id": str(tenant_id),
        },
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(local.id)]


def test_missing_membership_denies_matching_employee_email(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    employee = _employee_model(tenant_id)
    _hydrate_hosted(
        monkeypatch,
        tenants=[TenantModel(id=tenant_id)],
        memberships=[],
        employees=[(employee, "analyst", tenant_id)],
    )
    response = client.get(
        "/v1/employees",
        headers={
            "Authorization": f"Bearer {make_token(uuid4(), email=employee.email)}",
            "X-Organization-Id": str(tenant_id),
        },
    )
    assert response.status_code == 403


def test_membership_for_another_tenant_is_denied(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = uuid4()
    requested = uuid4()
    user_id = uuid4()
    _hydrate_hosted(
        monkeypatch,
        tenants=[TenantModel(id=home), TenantModel(id=requested)],
        memberships=[_membership(home, user_id)],
        employees=[],
    )
    response = client.get(
        "/v1/employees",
        headers={
            "Authorization": f"Bearer {make_token(user_id, email='ada@example.com')}",
            "X-Organization-Id": str(requested),
        },
    )
    assert response.status_code == 403


def test_inactive_membership_is_denied(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    _hydrate_hosted(
        monkeypatch,
        tenants=[TenantModel(id=tenant_id)],
        memberships=[_membership(tenant_id, user_id, status="suspended")],
        employees=[],
    )
    response = client.get(
        "/v1/employees",
        headers={
            "Authorization": f"Bearer {make_token(user_id)}",
            "X-Organization-Id": str(tenant_id),
        },
    )
    assert response.status_code == 403


def test_organization_list_returns_only_active_memberships_for_subject(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    active_tenant = uuid4()
    suspended_tenant = uuid4()
    someone_else = uuid4()
    other_user = uuid4()
    _hydrate_hosted(
        monkeypatch,
        tenants=[
            TenantModel(id=active_tenant),
            TenantModel(id=suspended_tenant),
            TenantModel(id=someone_else),
        ],
        memberships=[
            _membership(active_tenant, user_id, role="manager"),
            _membership(suspended_tenant, user_id, status="invited"),
            _membership(someone_else, other_user, role="owner"),
        ],
        employees=[],
    )
    response = client.get(
        "/v1/auth/organizations",
        headers={"Authorization": f"Bearer {make_token(user_id)}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [str(active_tenant)]
    assert body[0]["membership_role"] == "manager"
    assert body[0]["plan_code"] == ""
    assert body[0]["status"] == ""


def test_missing_membership_stays_forbidden(
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    record = _employee_record(tenant_id)
    get_memory_store().employees[record.id] = record
    response = client.get(
        "/v1/employees",
        headers={
            "Authorization": f"Bearer {make_token(uuid4(), email=record.email)}",
            "X-Organization-Id": str(tenant_id),
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Not a member of this organization"


def test_memory_mode_membership_still_filters_employees(
    client: TestClient,
    auth_headers_a: dict[str, str],
    org_a,
    org_b,
) -> None:
    store = get_memory_store()
    local = _employee_record(org_a, email="local@example.com")
    foreign = _employee_record(org_b, email="foreign@example.com")
    store.employees[local.id] = local
    store.employees[foreign.id] = foreign
    response = client.get("/v1/employees", headers=auth_headers_a)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(local.id)]
