"""Backup bookkeeping: when a backup is due, which ones are kept."""

import datetime as dt
from pathlib import Path

from app.services.backup import backup_time, backups, needs_backup, prune

NOW = dt.datetime(2026, 11, 20, 3, 0, tzinfo=dt.UTC)


def touch(directory: Path, stamp: str) -> Path:
    path = directory / f"yaver-{stamp}.sql.gz"
    path.write_bytes(b"x")
    return path


def test_due_when_none_or_older_than_max_age(tmp_path: Path) -> None:
    day = dt.timedelta(hours=24)
    assert needs_backup(tmp_path / "missing", NOW, day)
    assert needs_backup(tmp_path, NOW, day)

    touch(tmp_path, "20261119-020000")  # 25 h ago
    assert needs_backup(tmp_path, NOW, day)

    touch(tmp_path, "20261119-120000")  # 15 h ago
    assert not needs_backup(tmp_path, NOW, day)


def test_names_that_are_not_backups_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x")
    touch(tmp_path, "garbage")

    assert backup_time(tmp_path / "yaver-garbage.sql.gz") is None
    assert needs_backup(tmp_path, NOW, dt.timedelta(hours=24))


def test_prune_keeps_the_newest(tmp_path: Path) -> None:
    for day in range(1, 18):
        touch(tmp_path, f"202611{day:02d}-030000")

    removed = prune(tmp_path, keep=14)

    assert len(removed) == 3
    kept = [p.name for p in backups(tmp_path)]
    assert kept[0] == "yaver-20261117-030000.sql.gz"
    assert kept[-1] == "yaver-20261104-030000.sql.gz"
    assert len(kept) == 14
