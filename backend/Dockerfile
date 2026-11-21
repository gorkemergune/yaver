# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# pg_dump for the automatic backup: the client must match the server (PostgreSQL 16),
# Debian ships a different major, so it comes from the PostgreSQL apt repository.
RUN apt-get update  && apt-get install -y --no-install-recommends ca-certificates curl  && install -d /usr/share/postgresql-common/pgdg  && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc  && . /etc/os-release  && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list  && apt-get update  && apt-get install -y --no-install-recommends postgresql-client-16  && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- dev: dependencies incl. dev tools; source is bind-mounted by docker-compose.override.yml
FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY . .
# an open stream (office SSE) must not hold a reload / stop forever: 5 s, then it is cut
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--timeout-graceful-shutdown", "5"]

# --- prod: runtime dependencies only, non-root user
FROM base AS prod
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
RUN useradd --create-home --uid 1000 yaver
USER yaver
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "5"]
