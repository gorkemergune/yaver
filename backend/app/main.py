import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app import __version__
from app.api import (
    auth,
    calendar,
    chat,
    devices,
    employees,
    health,
    jobs,
    office,
    push,
    screen_time,
    study,
    uploads,
    usage,
    views,
    voice,
)
from app.api.auth import require_auth
from app.config import get_settings
from app.db.session import dispose_engine
from app.jobs.scheduler import catch_up, start_scheduler
from app.llm.check_models import log_startup_check
from app.llm.router import get_router
from app.llm.stt import get_stt
from app.office.state import get_office
from app.services.auth import auth_enabled, configured_password
from app.services.backup import backup_if_due

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not auth_enabled(settings):
        reason = (
            "placeholder"
            if settings.app_password and configured_password(settings) is None
            else "empty"
        )
        logger.warning("APP_PASSWORD is %s: login is off, keep the app off the internet", reason)
    background: list[asyncio.Task[object]] = []
    # Background tasks: a slow provider or a long pg_dump never delays startup.
    if settings.llm_check_models_on_startup:
        background.append(asyncio.create_task(log_startup_check()))
    if settings.backup_on_startup:
        background.append(asyncio.create_task(backup_if_due(settings)))
    # employees from agents.yaml; working / meeting left by a stopped process -> break
    background.append(asyncio.create_task(get_office().start()))
    scheduler = None
    if settings.scheduler_enabled:
        try:
            scheduler = start_scheduler(settings)
            background.append(asyncio.create_task(catch_up(settings)))
        except Exception:  # the chat must work even if the scheduler can't start
            logger.exception("Scheduler could not start")
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    for task in background:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    if get_router.cache_info().currsize:
        await get_router().aclose()
    if get_stt.cache_info().currsize:
        await get_stt().aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)

    # `/health` for container healthchecks, `/api/health` for the web app (proxied under /api).
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api", include_in_schema=False)
    app.include_router(auth.router, prefix="/api")
    # the phone's calendar can't log in: the feed checks its own secret token
    app.include_router(calendar.feed_router, prefix="/api")
    # Everything else needs a login when APP_PASSWORD is set.
    guarded = [Depends(require_auth)]
    for module in (
        usage,
        chat,
        views,
        uploads,
        jobs,
        voice,
        screen_time,
        push,
        study,
        calendar,
        office,
        employees,
        devices,
    ):
        app.include_router(module.router, prefix="/api", dependencies=guarded)
    return app


app = create_app()
