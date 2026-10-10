from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.core.database import build_engine
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _configure(connection: Connection | None = None) -> None:
    settings = get_settings()
    context.configure(
        connection=connection,
        url=None if connection else settings.database_url,
        target_metadata=target_metadata,
        render_as_batch=settings.is_sqlite,  # SQLite needs batch mode for ALTER TABLE
        compare_type=True,
    )


def run_migrations_offline() -> None:
    _configure()
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    settings = get_settings()
    engine = build_engine(settings)
    async with engine.connect() as connection:
        if settings.is_sqlite:
            # Batch migrations rebuild tables (create copy, DROP old, rename). With FK
            # enforcement on, the DROP fires ON DELETE actions on referencing rows (e.g.
            # SET NULL on documents.current_version_id). Must be set outside a transaction.
            await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            await connection.commit()
        await connection.run_sync(_run_sync)
        if settings.is_sqlite:
            await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
