"""Database backups: pg_dump -> BACKUP_DIR/yaver-YYYYMMDD-HHMMSS.sql.gz, the newest
BACKUP_KEEP kept. The API takes one on startup when the newest is older than
BACKUP_MAX_AGE_HOURS; scripts/backup.sh / backup.ps1 take and restore them by hand.

The dump is plain SQL with --clean --if-exists, so restoring into an existing database
replaces its tables (restore into a scratch database first if unsure).
"""

import asyncio
import datetime as dt
import gzip
import logging
import os
from pathlib import Path

from sqlalchemy import make_url

from app.config import Settings

logger = logging.getLogger(__name__)

PREFIX = "yaver-"
SUFFIX = ".sql.gz"
DUMP_OPTIONS = ("--clean", "--if-exists", "--no-owner", "--no-privileges")


class BackupError(RuntimeError):
    pass


def backups(directory: Path) -> list[Path]:
    """Backups in the directory, newest first (by the timestamp in the name)."""
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: p.name, reverse=True)


def backup_time(path: Path) -> dt.datetime | None:
    stamp = path.name.removeprefix(PREFIX).removesuffix(SUFFIX)
    try:
        return dt.datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def needs_backup(directory: Path, now: dt.datetime, max_age: dt.timedelta) -> bool:
    for path in backups(directory):
        taken = backup_time(path)
        if taken is not None:
            return now - taken >= max_age
    return True


def prune(directory: Path, keep: int) -> list[Path]:
    """Deletes all but the newest `keep` backups; returns what was deleted."""
    removed = backups(directory)[max(keep, 1) :]
    for path in removed:
        path.unlink(missing_ok=True)
    return removed


async def run_backup(settings: Settings, now: dt.datetime | None = None) -> Path:
    """pg_dump of DATABASE_URL into a new gzip file (written to *.part, then renamed)."""
    url = make_url(settings.database_url)
    now = now or dt.datetime.now(dt.UTC)
    directory = settings.backup_dir
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{PREFIX}{now:%Y%m%d-%H%M%S}{SUFFIX}"
    partial = target.with_name(target.name + ".part")
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    process = await asyncio.create_subprocess_exec(
        "pg_dump",
        "-h",
        url.host or "localhost",
        "-p",
        str(url.port or 5432),
        "-U",
        url.username or "postgres",
        "-d",
        url.database or "postgres",
        *DUMP_OPTIONS,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        # compressing is CPU work: in a thread, so the chat is not paused during a backup;
        # stderr is read at the same time (a full stderr pipe would block pg_dump) (QA D2)
        stderr_read = asyncio.create_task(process.stderr.read())
        with gzip.open(partial, "wb") as out:
            while chunk := await process.stdout.read(1 << 16):
                await asyncio.to_thread(out.write, chunk)
        errors = await stderr_read
        code = await process.wait()
        if code != 0:
            raise BackupError(errors.decode(errors="replace").strip() or f"pg_dump exit {code}")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    prune(directory, settings.backup_keep)
    return target


async def backup_if_due(settings: Settings) -> Path | None:
    """Startup hook: a backup when the newest one is too old. Never raises."""
    max_age = dt.timedelta(hours=settings.backup_max_age_hours)
    if not needs_backup(settings.backup_dir, dt.datetime.now(dt.UTC), max_age):
        return None
    try:
        path = await run_backup(settings)
    except (OSError, BackupError) as exc:  # no pg_dump, unwritable dir, db down...
        logger.warning("Automatic backup failed: %s", exc)
        return None
    logger.info("Automatic backup: %s (%d bytes)", path.name, path.stat().st_size)
    return path
