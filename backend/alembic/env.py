import asyncio
from logging.config import fileConfig
from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app import db  # noqa: F401  (imports app.db.models so all tables register on Base.metadata)
from app.config import get_settings
from app.db.base import Base
from app.db.session import CONNECT_ARGS
from app.db.types import UTCDateTime

config = context.config

# Programmatic callers (tests) pass their own logging setup and database URL.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = config.attributes.get("database_url")
    return str(url) if url else get_settings().database_url


def _render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    # Migrations shouldn't import app code: render UTCDateTime as a plain timestamptz.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        render_item=_render_item,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running against a database (`alembic upgrade --sql`)."""
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(
        _database_url(), poolclass=pool.NullPool, connect_args=CONNECT_ARGS
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
