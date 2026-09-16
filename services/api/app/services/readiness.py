"""Migration and dependency readiness checks."""

from __future__ import annotations

from pathlib import Path

from bpm_contracts import ReadinessCheck, ReadinessResponse

from app.config import Settings


async def check_database(settings: Settings) -> ReadinessCheck:
    if settings.persistence_mode == "memory":
        return ReadinessCheck(
            name="database",
            ready=True,
            detail="memory persistence mode",
        )
    if not settings.database_url:
        return ReadinessCheck(
            name="database",
            ready=False,
            detail="DATABASE_URL is not configured",
        )
    try:
        from sqlalchemy import text

        from app.database import dispose_engine, init_engine

        engine = init_engine(settings)
        if engine is None:
            return ReadinessCheck(
                name="database",
                ready=False,
                detail="database engine not initialized",
            )
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await dispose_engine()
        return ReadinessCheck(name="database", ready=True, detail="reachable")
    except Exception as exc:  # noqa: BLE001
        return ReadinessCheck(
            name="database",
            ready=False,
            detail=f"unreachable: {exc.__class__.__name__}",
        )


async def check_redis(settings: Settings) -> ReadinessCheck:
    if not settings.redis_url:
        return ReadinessCheck(
            name="redis",
            ready=False,
            detail="REDIS_URL is not configured",
        )
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        try:
            pong = await client.ping()
        finally:
            await client.aclose()
        if pong:
            return ReadinessCheck(name="redis", ready=True, detail="reachable")
        return ReadinessCheck(name="redis", ready=False, detail="ping failed")
    except Exception as exc:  # noqa: BLE001
        if settings.app_env in {"local", "test"}:
            return ReadinessCheck(
                name="redis",
                ready=True,
                detail=f"unreachable in {settings.app_env}: {exc.__class__.__name__} (non-blocking)",
            )
        return ReadinessCheck(
            name="redis",
            ready=False,
            detail=f"unreachable: {exc.__class__.__name__}",
        )


def check_migrations(settings: Settings) -> ReadinessCheck:
    """
    Verify expected Supabase SQL migrations are present on disk.

    Does not require Docker — checks the managed migration directory that operators
    apply against Supabase/Postgres.
    """
    root = Path(__file__).resolve().parents[4]  # repo root from services/api/app/services
    migrations_dir = root / "supabase" / "migrations"
    if not migrations_dir.is_dir():
        # Fallback relative to CWD
        migrations_dir = Path("supabase/migrations")
    if not migrations_dir.is_dir():
        return ReadinessCheck(
            name="migrations",
            ready=settings.app_env in {"local", "test"},
            detail="supabase/migrations directory not found",
        )

    required_prefixes = (
        "20260915120000",
        "20260915120100",
        "20260915120200",
        "20260915200000",  # subscriptions/entitlements
    )
    files = {p.name for p in migrations_dir.glob("*.sql")}
    missing = [prefix for prefix in required_prefixes if not any(f.startswith(prefix) for f in files)]
    if missing:
        return ReadinessCheck(
            name="migrations",
            ready=False,
            detail="missing migration prefixes: " + ", ".join(missing),
        )
    return ReadinessCheck(
        name="migrations",
        ready=True,
        detail=f"{len(files)} migration files present",
    )


def check_secrets(settings: Settings) -> ReadinessCheck:
    if settings.app_env == "production":
        if not settings.app_signing_secret and not settings.integrations_secret_key:
            return ReadinessCheck(
                name="secrets",
                ready=False,
                detail="APP_SIGNING_SECRET or INTEGRATIONS_SECRET_KEY required in production",
            )
        if settings.app_signing_secret == "dev-only-integrations-secret-not-for-production":
            return ReadinessCheck(
                name="secrets",
                ready=False,
                detail="default development secret must not be used in production",
            )
    return ReadinessCheck(name="secrets", ready=True, detail="configured")


async def check_supabase_auth(settings: Settings) -> ReadinessCheck:
    if not settings.supabase_url:
        ready = settings.skip_dependency_checks or settings.app_env in {"local", "test"}
        return ReadinessCheck(
            name="supabase_auth",
            ready=ready,
            detail="SUPABASE_URL not configured",
        )
    if not settings.supabase_jwt_secret and not settings.supabase_anon_key:
        ready = settings.skip_dependency_checks or settings.app_env in {"local", "test"}
        return ReadinessCheck(
            name="supabase_auth",
            ready=ready,
            detail="SUPABASE_JWT_SECRET or SUPABASE_ANON_KEY required",
        )
    detail = "jwt secret present" if settings.supabase_jwt_secret else "auth API fallback (anon key)"
    return ReadinessCheck(name="supabase_auth", ready=True, detail=detail)


async def build_readiness(settings: Settings) -> ReadinessResponse:
    if settings.skip_dependency_checks:
        return ReadinessResponse(
            ready=True,
            service=settings.app_name,
            checks=[
                ReadinessCheck(
                    name="dependency_checks",
                    ready=True,
                    detail="skipped via SKIP_DEPENDENCY_CHECKS",
                ),
                check_migrations(settings),
            ],
        )

    checks = [
        await check_database(settings),
        await check_redis(settings),
        await check_supabase_auth(settings),
        check_migrations(settings),
        check_secrets(settings),
    ]
    missing = settings.missing_required_for_runtime()
    # Soften redis requirement for local/test when skipped above
    if settings.app_env in {"local", "test"}:
        missing = [m for m in missing if m != "REDIS_URL"]
    if missing:
        checks.append(
            ReadinessCheck(
                name="settings",
                ready=False,
                detail="missing: " + ", ".join(missing),
            )
        )
    else:
        checks.append(ReadinessCheck(name="settings", ready=True, detail="present"))

    ready = all(check.ready for check in checks)
    return ReadinessResponse(ready=ready, service=settings.app_name, checks=checks)
