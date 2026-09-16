"""Database session helpers for Postgres mode."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _normalize_url(url: str) -> str:
    """Normalize Postgres URLs for SQLAlchemy asyncpg (including Supabase pooler)."""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    # libpq uses sslmode=; asyncpg expects ssl=
    if "sslmode" in query and "ssl" not in query:
        mode = query.pop("sslmode")
        if mode in {"require", "verify-ca", "verify-full", "true", "1"}:
            query["ssl"] = "require"
        elif mode in {"disable", "allow", "prefer"}:
            query.pop("ssl", None)
    new_query = urlencode(query)
    return urlunparse(parsed._replace(query=new_query))


def init_engine(settings: Settings | None = None) -> AsyncEngine | None:
    global _engine, _session_factory
    settings = settings or get_settings()
    if settings.persistence_mode != "postgres" or not settings.database_url:
        return None
    _engine = create_async_engine(_normalize_url(settings.database_url), pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Postgres session factory is not initialized")
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
