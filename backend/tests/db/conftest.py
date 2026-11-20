"""Fixtures for tests against a real PostgreSQL.

Uses TEST_DATABASE_URL, or DATABASE_URL with the database name suffixed by `_test`
(yaver -> yaver_test). The test database is created if missing and migrated to head.
Tests are skipped when PostgreSQL is unreachable.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.base import Base
from app.db.session import CONNECT_ARGS

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    url = make_url(explicit or get_settings().database_url)
    if not explicit:
        url = url.set(database=f"{url.database}_test")
    if not (url.database or "").endswith("_test"):
        raise RuntimeError(f"Refusing to run DB tests against non-test database {url.database!r}")
    return url.render_as_string(hide_password=False)


async def _ensure_database(url: str) -> None:
    target = make_url(url)
    admin = create_async_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=pool.NullPool
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        await admin.dispose()


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    try:
        asyncio.run(_ensure_database(url))
    except (OSError, ConnectionError) as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    command.upgrade(alembic_config(url), "head")
    return url


# Empty every table and restart the ids, in one round trip. DELETE (children first) on
# the near-empty test tables is much faster than TRUNCATE, which takes an exclusive lock and
# rewrites files for each table; ids restart because tests rely on them ("öneri #1").
RESET_SQL = (
    "DO $$ DECLARE s record; BEGIN "
    + " ".join(f"DELETE FROM {table.name};" for table in reversed(Base.metadata.sorted_tables))
    + " FOR s IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' LOOP"
    " EXECUTE format('ALTER SEQUENCE %I RESTART', s.sequencename); END LOOP; END $$"
)


@pytest.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url, poolclass=pool.NullPool, connect_args=CONNECT_ARGS)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(RESET_SQL)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db_session:
        yield db_session
    await engine.dispose()
