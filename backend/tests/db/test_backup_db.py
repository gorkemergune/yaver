"""pg_dump of the test database (runs where pg_dump exists: the api container)."""

import asyncio
import gzip
import shutil
from pathlib import Path

import pytest

from app.config import Settings
from app.services.backup import backups, run_backup

pytestmark = pytest.mark.skipif(shutil.which("pg_dump") is None, reason="pg_dump not installed")


async def test_backup_of_the_test_database(database_url: str, tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None, database_url=database_url, backup_dir=tmp_path, backup_keep=2
    )

    first = await run_backup(settings)
    sql = gzip.decompress(first.read_bytes()).decode()

    assert first.name.startswith("yaver-")
    assert "CREATE TABLE public.recurring_blocks" in sql
    assert "DROP TABLE IF EXISTS public.recurring_blocks" in sql  # --clean: restorable in place
    leftovers = await asyncio.to_thread(lambda: [p.name for p in tmp_path.iterdir()])
    assert leftovers == [first.name]  # no *.part left behind
    assert backups(tmp_path) == [first]
