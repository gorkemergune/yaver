from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness: the API process is up."""
    return HealthResponse(status="ok", app=get_settings().app_name, version=__version__)
