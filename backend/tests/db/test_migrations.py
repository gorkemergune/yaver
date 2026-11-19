import asyncio

from alembic import command
from sqlalchemy import inspect, pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base
from tests.db.conftest import alembic_config


async def _table_names(url: str) -> set[str]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            return set(await conn.run_sync(lambda sync: inspect(sync).get_table_names()))
    finally:
        await engine.dispose()


def test_migrations_downgrade_to_base_and_back(database_url: str) -> None:
    config = alembic_config(database_url)
    model_tables = {table.name for table in Base.metadata.sorted_tables}

    command.downgrade(config, "base")
    assert asyncio.run(_table_names(database_url)) == {"alembic_version"}

    command.upgrade(config, "head")
    assert asyncio.run(_table_names(database_url)) == model_tables | {"alembic_version"}


def test_models_and_migrations_are_in_sync(database_url: str) -> None:
    # Raises if autogenerate would produce a new migration.
    command.check(alembic_config(database_url))
