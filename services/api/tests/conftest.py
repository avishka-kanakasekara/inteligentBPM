from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import reset_settings_cache
from app.contracts.common import utcnow
from app.database.memory import MembershipRecord, get_memory_store, reset_memory_store
from app.domain.enums import MembershipStatus, OrgRole
from app.repositories.memory_repos import OrganizationRepository

TEST_JWT_SECRET = "test-supabase-jwt-secret-not-for-production"


@pytest.fixture()
def user_a_id() -> UUID:
    return UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture()
def user_b_id() -> UUID:
    return UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def make_token(
    user_id: UUID,
    *,
    email: str = "user@example.com",
    secret: str = TEST_JWT_SECRET,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": "authenticated",
        "aud": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("BPM_LOAD_DOTENV", "0")
    monkeypatch.setenv("PERSISTENCE_MODE", "memory")
    monkeypatch.setenv("SKIP_DEPENDENCY_CHECKS", "true")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("ENABLE_RATE_LIMIT", "true")
    monkeypatch.setenv("ENABLE_CSRF", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    reset_settings_cache()
    reset_memory_store()

    from app.observability.metrics import metrics
    from app.security.rate_limit import api_rate_limiter, login_abuse_limiter, login_abuse_protector
    from app.workflows.engine import reset_mock_engine

    reset_mock_engine()
    api_rate_limiter.reset()
    login_abuse_limiter.reset()
    login_abuse_protector._failures.clear()
    login_abuse_protector._lockouts.clear()
    metrics.reset()

    from app.main import create_app

    application = create_app()
    with TestClient(application) as test_client:
        yield test_client

    reset_memory_store()
    reset_mock_engine()
    api_rate_limiter.reset()
    login_abuse_limiter.reset()
    login_abuse_protector._failures.clear()
    login_abuse_protector._lockouts.clear()
    metrics.reset()
    reset_settings_cache()


@pytest.fixture()
def org_a(client: TestClient, user_a_id: UUID) -> UUID:
    org = OrganizationRepository().create(
        name="Org A",
        plan_code="pro",
        owner_user_id=user_a_id,
    )
    return org.id


@pytest.fixture()
def org_b(client: TestClient, user_b_id: UUID) -> UUID:
    org = OrganizationRepository().create(
        name="Org B",
        plan_code="enterprise",
        owner_user_id=user_b_id,
    )
    return org.id


@pytest.fixture()
def auth_headers_a(user_a_id: UUID, org_a: UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {make_token(user_a_id, email='a@example.com')}",
        "X-Organization-Id": str(org_a),
    }


@pytest.fixture()
def auth_headers_b(user_b_id: UUID, org_b: UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {make_token(user_b_id, email='b@example.com')}",
        "X-Organization-Id": str(org_b),
    }


def add_membership(organization_id: UUID, user_id: UUID, role: OrgRole = OrgRole.EMPLOYEE) -> None:
    store = get_memory_store()
    now = utcnow()
    membership = MembershipRecord(
        id=uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        status=MembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    store.memberships[membership.id] = membership
