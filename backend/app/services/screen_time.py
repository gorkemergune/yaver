"""Screen time per day, all devices together (reads of `screen_time_days`)."""

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScreenTimeDay


def fmt_minutes(seconds: int) -> str:
    """`4320` -> `1 saat 12 dk`, `300` -> `5 dk`."""
    minutes = max(seconds, 0) // 60
    hours, rest = divmod(minutes, 60)
    if hours == 0:
        return f"{rest} dk"
    return f"{hours} saat" + (f" {rest} dk" if rest else "")


async def day_summary(
    session: AsyncSession, day: dt.date, top: int | None = None
) -> dict[str, Any] | None:
    """Total, apps (same exe on two devices added up) and limits of a day; None = no data."""
    rows = (await session.scalars(select(ScreenTimeDay).where(ScreenTimeDay.date == day))).all()
    if not rows:
        return None
    apps: dict[str, dict[str, Any]] = {}
    limits: dict[str, dict[str, Any]] = {}
    for row in rows:
        for app in row.apps:
            key = str(app["exe"]).lower()
            entry = apps.setdefault(key, {"exe": app["exe"], "name": app["name"], "seconds": 0})
            entry["seconds"] += int(app["seconds"])
        for limit in row.limits:
            entry = limits.setdefault(
                limit["name"], {"name": limit["name"], "used_seconds": 0, "limit_seconds": 0}
            )
            entry["used_seconds"] += int(limit["used_seconds"])
            entry["limit_seconds"] = max(entry["limit_seconds"], int(limit["limit_seconds"]))
    ordered = sorted(apps.values(), key=lambda a: (-a["seconds"], a["name"]))
    return {
        "date": day.isoformat(),
        "total_seconds": sum(r.total_seconds for r in rows),
        "apps": ordered[:top] if top else ordered,
        "limits": list(limits.values()),
        "devices": sorted(r.device for r in rows),
        "updated_at": max(r.updated_at for r in rows),
    }


def checkin_line(summary: dict[str, Any]) -> str | None:
    """`bugün 5 saat 12 dk ekran, 1 saat 10 dk VALORANT (sınır 1 saat 30 dk)`.

    Apps with a limit are named; without limits, the app used most."""
    total = int(summary["total_seconds"])
    if total < 60:
        return None
    parts = [f"bugün {fmt_minutes(total)} ekran"]
    limited = [lim for lim in summary["limits"] if lim["used_seconds"] >= 60]
    if limited:
        for lim in limited:
            over = ", aşıldı" if lim["used_seconds"] > lim["limit_seconds"] else ""
            parts.append(
                f"{fmt_minutes(lim['used_seconds'])} {lim['name']} "
                f"(sınır {fmt_minutes(lim['limit_seconds'])}{over})"
            )
    elif summary["apps"] and summary["apps"][0]["seconds"] >= 60:
        top = summary["apps"][0]
        parts.append(f"en çok {top['name']} ({fmt_minutes(top['seconds'])})")
    return ", ".join(parts)
