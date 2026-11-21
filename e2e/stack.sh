#!/usr/bin/env bash
# Isolated e2e stack (project yaver-e2e: web 8090, api 8001, db 5433). Another copy side by side:
#   E2E_PROJECT=yaver-e2e-mine E2E_WEB_PORT=8091 E2E_API_PORT=8002 E2E_DB_PORT=5434 e2e/stack.sh up
# (the name must start with yaver-e2e; images are tagged <project>-api / <project>-web). Usage:
#   e2e/stack.sh up      build, start, wait for /api/health/ready, migrate
#   e2e/stack.sh down    stop and remove containers (volumes kept)
#   e2e/stack.sh reset   stop and remove containers AND volumes (fresh DB next time)
#   e2e/stack.sh logs    api logs
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ARGS=()
[ -f "$ROOT/.env" ] && ENV_ARGS=(--env-file "$ROOT/.env")
PROJECT="${E2E_PROJECT:-yaver-e2e}"
case "$PROJECT" in yaver-e2e*) ;; *) echo "E2E_PROJECT must start with yaver-e2e" >&2; exit 2 ;; esac
API_PORT="${E2E_API_PORT:-8001}"
WEB_PORT="${E2E_WEB_PORT:-8090}"
export E2E_API_IMAGE="${E2E_API_IMAGE:-$PROJECT-api}" E2E_WEB_IMAGE="${E2E_WEB_IMAGE:-$PROJECT-web}"
dc() { docker compose -p "$PROJECT" -f "$ROOT/e2e/docker-compose.e2e.yml" "${ENV_ARGS[@]}" "$@"; }

case "${1:-up}" in
  up)
    dc up -d --build
    dc exec -T api alembic upgrade head
    dc restart api   # employees are synced on startup: needs the migrated schema
    for _ in $(seq 1 60); do
      if curl -fsS http://127.0.0.1:$API_PORT/api/health/ready >/dev/null 2>&1; then
        echo "e2e stack $PROJECT ready: web http://127.0.0.1:$WEB_PORT  api http://127.0.0.1:$API_PORT"; exit 0
      fi
      sleep 2
    done
    echo "api not ready" >&2; dc logs --tail 80 api >&2; exit 1 ;;
  down) dc down ;;
  reset) dc down -v ;;
  logs) dc logs --tail "${2:-200}" api ;;
  *) echo "usage: $0 up|down|reset|logs" >&2; exit 2 ;;
esac
