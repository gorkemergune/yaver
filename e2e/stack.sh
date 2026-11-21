#!/usr/bin/env bash
# Isolated e2e stack (project yaver-e2e: web 8090, api 8001, db 5433). Usage:
#   e2e/stack.sh up      build, start, wait for /api/health/ready, migrate
#   e2e/stack.sh down    stop and remove containers (volumes kept)
#   e2e/stack.sh reset   stop and remove containers AND volumes (fresh DB next time)
#   e2e/stack.sh logs    api logs
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ARGS=()
[ -f "$ROOT/.env" ] && ENV_ARGS=(--env-file "$ROOT/.env")
dc() { docker compose -p yaver-e2e -f "$ROOT/e2e/docker-compose.e2e.yml" "${ENV_ARGS[@]}" "$@"; }

case "${1:-up}" in
  up)
    dc up -d --build
    dc exec -T api alembic upgrade head
    dc restart api   # employees are synced on startup: needs the migrated schema
    for _ in $(seq 1 60); do
      if curl -fsS http://127.0.0.1:8001/api/health/ready >/dev/null 2>&1; then
        echo "e2e stack ready: web http://127.0.0.1:8090  api http://127.0.0.1:8001"; exit 0
      fi
      sleep 2
    done
    echo "api not ready" >&2; dc logs --tail 80 api >&2; exit 1 ;;
  down) dc down ;;
  reset) dc down -v ;;
  logs) dc logs --tail "${2:-200}" api ;;
  *) echo "usage: $0 up|down|reset|logs" >&2; exit 2 ;;
esac
