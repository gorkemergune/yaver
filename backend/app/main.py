from fastapi import FastAPI

from app import __version__
from app.api import health
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__)

    # `/health` for container healthchecks, `/api/health` for the web app (proxied under /api).
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api", include_in_schema=False)
    return app


app = create_app()
