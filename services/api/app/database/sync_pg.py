"""Synchronous SQLAlchemy session for repository persistence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings

_sync_engine: Engine | None = None
_sync_session_factory: sessionmaker[Session] | None = None


def _normalize_sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop("sslmode", None)
    return urlunparse(parsed._replace(query=urlencode(query)))


def init_sync_engine(settings: Settings | None = None) -> Engine | None:
    global _sync_engine, _sync_session_factory
    settings = settings or get_settings()
    if settings.persistence_mode != "postgres" or not settings.database_url:
        return None
    _sync_engine = create_engine(
        _normalize_sync_url(settings.database_url),
        pool_pre_ping=True,
        future=True,
    )
    _sync_session_factory = sessionmaker(_sync_engine, expire_on_commit=False)
    return _sync_engine


def get_sync_session_factory() -> sessionmaker[Session] | None:
    return _sync_session_factory


@contextmanager
def sync_session_scope() -> Iterator[Session]:
    factory = get_sync_session_factory()
    if factory is None:
        raise RuntimeError("Sync Postgres session factory is not initialized")
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_sync_engine() -> None:
    global _sync_engine, _sync_session_factory
    if _sync_engine is not None:
        _sync_engine.dispose()
    _sync_engine = None
    _sync_session_factory = None
