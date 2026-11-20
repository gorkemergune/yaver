import asyncio

from alembic import command
from sqlalchemy import inspect, pool, text
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


async def _run(url: str, *statements: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as conn:
            rows: list[tuple[object, ...]] = []
            for statement in statements:
                result = await conn.execute(text(statement))
                if result.returns_rows:
                    rows = [tuple(row) for row in result.all()]
            return rows
    finally:
        await engine.dispose()


def test_day_based_attendance_becomes_one_row_per_block(database_url: str) -> None:
    config = alembic_config(database_url)
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    asyncio.run(_run(database_url, f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    command.downgrade(config, "d5aa7d7dd829")  # attendance was (course, date)
    asyncio.run(
        _run(
            database_url,
            "INSERT INTO courses (id, code, name) VALUES (1, 'MATH 221', 'MATH 221')",
            # Thursday 09:00-11:00 and 13:00-14:00, Tuesday 11:00-13:00
            "INSERT INTO recurring_blocks (id, kind, title, weekday, start_time, end_time, "
            "course_id) VALUES (1, 'class', 'MATH 221', 3, '09:00', '11:00', 1), "
            "(2, 'class', 'MATH 221 PS', 3, '13:00', '14:00', 1), "
            "(3, 'class', 'MATH 221', 1, '11:00', '13:00', 1)",
            # Thu 19 Nov (two blocks), Tue 17 Nov (one), Sun 22 Nov (no block)
            "INSERT INTO attendance (course_id, date, status) VALUES "
            "(1, '2026-11-19', 'absent'), (1, '2026-11-17', 'absent'), (1, '2026-11-22', 'absent')",
        )
    )

    command.upgrade(config, "head")
    rows = asyncio.run(
        _run(
            database_url,
            "SELECT date::text, recurring_block_id, hours FROM attendance "
            "ORDER BY date, recurring_block_id",
        )
    )
    command.downgrade(config, "d5aa7d7dd829")
    back = asyncio.run(_run(database_url, "SELECT date::text FROM attendance ORDER BY date"))
    command.upgrade(config, "head")

    assert rows == [
        ("2026-11-17", 3, 2),
        ("2026-11-19", 1, 2),
        ("2026-11-19", 2, 1),
        ("2026-11-22", None, 1),  # no class that day: kept, 1 hour, no block
    ]
    assert back == [("2026-11-17",), ("2026-11-19",), ("2026-11-22",)]  # one row per day again
