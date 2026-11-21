import logging

from fastapi import APIRouter, Response
from fastapi import status as http_status
from pydantic import BaseModel

from app import __version__
from app.config import get_settings
from app.db import session as db_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness: the API process is up."""
    return HealthResponse(status="ok", app=get_settings().app_name, version=__version__)


@router.get("/health/ready")
async def ready(response: Response) -> ReadinessResponse:
    """Readiness: the API can reach the database."""
    try:
        await db_session.ping_database()
    except Exception:
        logger.warning("Database readiness check failed", exc_info=True)
        response.status_code = http_status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable", database="unreachable")
    return ReadinessResponse(status="ok", database="ok")
