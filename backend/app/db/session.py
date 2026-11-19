"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

# DB sessions always run in UTC; APP_TIMEZONE is applied in the service layer only.
CONNECT_ARGS = {"server_settings": {"timezone": "UTC"}}


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().database_url, pool_pre_ping=True, connect_args=CONNECT_ARGS
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with get_sessionmaker()() as session:
        yield session


async def ping_database() -> None:
    """Raise if the database is unreachable."""
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
