import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import chat, health, usage
from app.config import get_settings
from app.db.session import dispose_engine
from app.llm.check_models import log_startup_check
from app.llm.router import get_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    check: asyncio.Task[None] | None = None
    if get_settings().llm_check_models_on_startup:
        # Runs in the background: a slow or missing provider never delays startup.
        check = asyncio.create_task(log_startup_check())
    yield
    if check is not None and not check.done():
        check.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await check
    if get_router.cache_info().currsize:
        await get_router().aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)

    # `/health` for container healthchecks, `/api/health` for the web app (proxied under /api).
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api", include_in_schema=False)
    app.include_router(usage.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    return app


app = create_app()
