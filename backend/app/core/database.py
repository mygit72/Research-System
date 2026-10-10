"""Async SQLAlchemy engine and session management."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _configure_sqlite(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL lets background jobs write progress while the API reads.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()


def build_engine(settings: Settings) -> AsyncEngine:
    kwargs: dict[str, object] = {"echo": settings.database_echo}
    if settings.is_sqlite:
        kwargs["connect_args"] = {"timeout": 15}
        # A request cancelled mid-query (a page reloaded while loading) can leave its pooled
        # connection closed; check before reuse so the next request doesn't fail with
        # "no active connection".
        kwargs["pool_pre_ping"] = True
        db_path = settings.database_url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)
    engine = create_async_engine(settings.database_url, **kwargs)
    if settings.is_sqlite:
        event.listen(engine.sync_engine, "connect", _configure_sqlite)
    return engine


def init_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine, _session_factory
    settings = settings or get_settings()
    _engine = build_engine(settings)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine, _session_factory = None, None


_AFTER_COMMIT_KEY = "after_commit_callbacks"


def after_commit(session: AsyncSession, callback: Callable[[], None]) -> None:
    """Run `callback` only once the request transaction has committed successfully."""
    session.info.setdefault(_AFTER_COMMIT_KEY, []).append(callback)


def run_after_commit(session: AsyncSession) -> None:
    """Run the callbacks registered with `after_commit` (call right after a commit)."""
    for callback in session.info.pop(_AFTER_COMMIT_KEY, []):
        callback()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed on success."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        run_after_commit(session)


async def ping_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
