"""Database security tests against a hosted Supabase development project.

Requires DATABASE_URL (Postgres connection string). Skips when unset.
Does not use Docker or local database containers.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"
USER_OWNER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_EMPLOYEE_A = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_OWNER_B = "cccccccc-cccc-cccc-cccc-cccccccccccc"
EMPLOYEE_A = "e1111111-1111-1111-1111-111111111111"
EMPLOYEE_B = "e2222222-2222-2222-2222-222222222221"
DOCUMENT_A = "doc11111-1111-1111-1111-111111111111"
DOCUMENT_B = "doc22222-2222-2222-2222-222222222221"


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")


pytestmark = pytest.mark.skipif(
    not _database_url(),
    reason="DATABASE_URL not set; configure a hosted Supabase development project",
)


@pytest.fixture(scope="module")
def pg() -> Iterator[object]:
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(_database_url(), autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


def _as_user(conn: object, user_id: str) -> None:
    conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (user_id,))
    conn.execute("select set_config('request.jwt.claim.role', 'authenticated', true)")
    conn.execute("set local role authenticated")


def _reset(conn: object) -> None:
    conn.rollback()


def test_cross_organization_employee_access_denied(pg: object) -> None:
    _reset(pg)
    with pg.transaction():
        _as_user(pg, USER_OWNER_A)
        rows = pg.execute(
            "select id from public.employees where id = %s",
            (EMPLOYEE_B,),
        ).fetchall()
        assert rows == []


def test_cross_organization_document_access_denied(pg: object) -> None:
    _reset(pg)
    with pg.transaction():
        _as_user(pg, USER_OWNER_A)
        rows = pg.execute(
            "select id from public.documents where id = %s",
            (DOCUMENT_B,),
        ).fetchall()
        assert rows == []
        own = pg.execute(
            "select id from public.documents where id = %s",
            (DOCUMENT_A,),
        ).fetchall()
        assert len(own) == 1


def test_unauthorized_organization_insert_denied(pg: object) -> None:
    _reset(pg)
    with pg.transaction():
        _as_user(pg, USER_EMPLOYEE_A)
        with pytest.raises(Exception):
            pg.execute(
                """
                insert into public.employees (
                  organization_id, full_name, email, status
                ) values (%s, 'Intruder', 'intruder@other.example', 'active')
                """,
                (ORG_B,),
            )


def test_unauthorized_approvals_denied(pg: object) -> None:
    _reset(pg)
    process_def_id = str(uuid.uuid4())
    process_version_id = str(uuid.uuid4())
    process_run_id = str(uuid.uuid4())
    approval_id = str(uuid.uuid4())

    with pg.transaction():
        pg.execute(
            """
            insert into public.process_definitions (
              id, organization_id, name, status, created_by_user_id
            ) values (%s, %s, %s, 'draft', %s)
            """,
            (process_def_id, ORG_A, f"approval-test-{process_def_id[:8]}", USER_OWNER_A),
        )
        pg.execute(
            """
            insert into public.process_versions (
              id, organization_id, process_definition_id, version_number,
              plan_snapshot, plan_snapshot_hash, status, is_immutable, created_by_user_id
            ) values (%s, %s, %s, 1, '{}'::jsonb, 'hash', 'ready', true, %s)
            """,
            (process_version_id, ORG_A, process_def_id, USER_OWNER_A),
        )
        pg.execute(
            """
            insert into public.process_runs (
              id, organization_id, process_definition_id, process_version_id, status,
              initiated_by_user_id
            ) values (%s, %s, %s, %s, 'awaiting_approval', %s)
            """,
            (process_run_id, ORG_A, process_def_id, process_version_id, USER_OWNER_A),
        )
        pg.execute(
            """
            insert into public.approvals (
              id, organization_id, process_run_id, process_version_id, status,
              required_roles, snapshot_plan_hash, snapshot_payload, snapshot_hash
            ) values (
              %s, %s, %s, %s, 'pending', array['owner'], 'hash', '{}'::jsonb, 'snap-hash'
            )
            """,
            (approval_id, ORG_A, process_run_id, process_version_id),
        )

    _reset(pg)
    with pg.transaction():
        _as_user(pg, USER_EMPLOYEE_A)
        result = pg.execute(
            """
            update public.approvals
            set status = 'approved', decided_by_user_id = %s, row_version = row_version + 1
            where id = %s
            """,
            (USER_EMPLOYEE_A, approval_id),
        )
        assert result.rowcount == 0
        status = pg.execute(
            "select status from public.approvals where id = %s",
            (approval_id,),
        ).fetchone()[0]
        assert status == "pending"


def test_audit_log_modification_denied(pg: object) -> None:
    _reset(pg)
    with pg.transaction():
        _as_user(pg, USER_OWNER_A)
        audit_id = pg.execute(
            """
            insert into public.audit_logs (
              organization_id, actor_user_id, actor_type, action, resource_type, payload
            ) values (%s, %s, 'user', 'test.action', 'test', '{}'::jsonb)
            returning id
            """,
            (ORG_A, USER_OWNER_A),
        ).fetchone()[0]

        with pytest.raises(Exception):
            pg.execute(
                "update public.audit_logs set action = 'tampered' where id = %s",
                (audit_id,),
            )

        with pytest.raises(Exception):
            pg.execute("delete from public.audit_logs where id = %s", (audit_id,))


def test_storage_access_is_organization_scoped(pg: object) -> None:
    _reset(pg)
    path_a = f"{ORG_A}/tests/{uuid.uuid4()}.txt"
    path_b = f"{ORG_B}/tests/{uuid.uuid4()}.txt"

    # Seed storage objects with elevated privileges.
    with pg.transaction():
        for path in (path_a, path_b):
            pg.execute(
                """
                insert into storage.objects (id, bucket_id, name, owner, metadata)
                values (%s::uuid, 'documents', %s, %s::uuid, '{}'::jsonb)
                on conflict do nothing
                """,
                (str(uuid.uuid4()), path, USER_OWNER_A if path == path_a else USER_OWNER_B),
            )

    _reset(pg)
    with pg.transaction():
        _as_user(pg, USER_OWNER_A)
        visible = pg.execute(
            "select name from storage.objects where bucket_id = 'documents' and name = %s",
            (path_a,),
        ).fetchall()
        hidden = pg.execute(
            "select name from storage.objects where bucket_id = 'documents' and name = %s",
            (path_b,),
        ).fetchall()
        assert len(visible) == 1
        assert hidden == []

        with pytest.raises(Exception):
            pg.execute(
                """
                insert into storage.objects (id, bucket_id, name, owner, metadata)
                values (%s::uuid, 'documents', %s, %s::uuid, '{}'::jsonb)
                """,
                (str(uuid.uuid4()), path_b, USER_OWNER_A),
            )


def test_anonymous_cannot_read_tenant_data(pg: object) -> None:
    _reset(pg)
    with pg.transaction():
        pg.execute("select set_config('request.jwt.claim.sub', '', true)")
        pg.execute("select set_config('request.jwt.claim.role', 'anon', true)")
        pg.execute("set local role anon")
        rows = pg.execute("select id from public.employees limit 5").fetchall()
        assert rows == []
