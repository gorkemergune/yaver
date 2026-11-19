#!/usr/bin/env bash
# Yaver database backups (Linux / macOS / Git Bash). Needs the `db` container running.
#
#   scripts/backup.sh                         new backup -> $BACKUP_DIR/yaver-YYYYMMDD-HHMMSS.sql.gz (UTC),
#                                             keeps the newest $BACKUP_KEEP (14)
#   scripts/backup.sh list                    backups, newest first
#   scripts/backup.sh restore FILE [DB]       restore into DB (default: yaver_restore, created if missing)
#   scripts/backup.sh restore FILE yaver --yes   restore over the live database (stop the api first:
#                                             docker compose stop api)
#
# BACKUP_DIR, BACKUP_KEEP, POSTGRES_USER, POSTGRES_DB come from the environment or .env.
set -euo pipefail
cd "$(dirname "$0")/.."

env_value() { [ -f .env ] && grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r"' || true; }
BACKUP_DIR="${BACKUP_DIR:-$(env_value BACKUP_DIR)}"; BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP="${BACKUP_KEEP:-$(env_value BACKUP_KEEP)}"; KEEP="${KEEP:-14}"
DB_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"; DB_USER="${DB_USER:-yaver}"
DB_NAME="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"; DB_NAME="${DB_NAME:-yaver}"
export MSYS_NO_PATHCONV=1  # Git Bash: keep /tmp/... container paths as they are

db() { docker compose exec -T db "$@"; }

backup() {
  mkdir -p "$BACKUP_DIR"
  local name file
  name="yaver-$(date -u +%Y%m%d-%H%M%S).sql.gz"
  file="$BACKUP_DIR/$name"
  # Dump and gzip inside the container, then copy the file out (no binary data through pipes).
  db sh -c "pg_dump -U '$DB_USER' -d '$DB_NAME' --clean --if-exists --no-owner --no-privileges | gzip > /tmp/$name"
  docker compose cp "db:/tmp/$name" "$file.part" >/dev/null
  db rm -f "/tmp/$name"
  gzip -t "$file.part"
  mv "$file.part" "$file"
  echo "backup: $file ($(wc -c < "$file") bytes)"
  # keep the newest $KEEP
  ls -1 "$BACKUP_DIR"/yaver-*.sql.gz 2>/dev/null | sort -r | tail -n +"$((KEEP + 1))" | while read -r old; do
    rm -f "$old"; echo "removed: $old"
  done
}

restore() {
  local file="${1:?usage: backup.sh restore FILE [DB] [--yes]}" target="${2:-yaver_restore}" confirm="${3:-}"
  [ -f "$file" ] || { echo "no such file: $file" >&2; exit 1; }
  if [ "$target" = "$DB_NAME" ] && [ "$confirm" != "--yes" ]; then
    echo "Refusing to overwrite the live database '$DB_NAME' without --yes (stop the api first)." >&2
    exit 1
  fi
  if [ "$(db psql -U "$DB_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$target'")" != "1" ]; then
    db createdb -U "$DB_USER" "$target"
    db psql -q -U "$DB_USER" -d "$target" -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null
  fi
  docker compose cp "$file" db:/tmp/yaver-restore.sql.gz >/dev/null
  db sh -c "gunzip -c /tmp/yaver-restore.sql.gz | psql -v ON_ERROR_STOP=1 -q -U '$DB_USER' -d '$target' >/dev/null"
  db rm -f /tmp/yaver-restore.sql.gz
  echo "restored $file into database '$target'"
}

case "${1:-backup}" in
  backup) backup ;;
  list) ls -1 "$BACKUP_DIR"/yaver-*.sql.gz 2>/dev/null | sort -r || echo "no backups in $BACKUP_DIR" ;;
  restore) shift; restore "$@" ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
