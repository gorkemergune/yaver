"""Run a scheduled job now (to try a briefing or the weekly plan without waiting)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.team import Team, get_team
from app.api.chat import get_session_factory
from app.jobs.runner import JOB_IDS, JobId, run_job

router = APIRouter(tags=["jobs"])


@router.post("/jobs/{job_id}/run")
async def run_now(
    job_id: str,
    force: bool = False,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    team: Team = Depends(get_team),
) -> dict[str, Any]:
    """`force=true` runs it even if it already ran today (a second message)."""
    if job_id not in JOB_IDS:
        raise HTTPException(404, detail={"code": "unknown_job", "jobs": list(JOB_IDS)})
    known: JobId = job_id
    message_id = await run_job(known, sessionmaker=session_factory, team=team, force=force)
    return {"job": job_id, "message_id": message_id}
