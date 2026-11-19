"""JSON views of day plans, shared by agent tools and the HTTP API."""

import datetime as dt
from typing import Any

from app.core.time_resolver import WEEKDAY_NAMES_TR
from app.services.schedule import DayPlan, PlanItem


def hhmm(value: dt.datetime | dt.time) -> str:
    return value.strftime("%H:%M")


def item_to_dict(item: PlanItem, day: dt.date) -> dict[str, Any]:
    data: dict[str, Any] = {
        "type": item.source,
        "id": item.source_id,
        "kind": item.kind,
        "title": item.title,
    }
    if item.all_day:
        data["all_day"] = True
    else:
        data["start"] = hhmm(item.start)
        if item.end is not None:
            data["end"] = hhmm(item.end)
    if item.start.date() != day:
        data["starts_on"] = item.start.date().isoformat()
    if item.end is not None and item.end.date() != day and not item.all_day:
        data["ends_on"] = item.end.date().isoformat()
    if item.location:
        data["location"] = item.location
    if item.moved_from:
        data["moved_from"] = item.moved_from.strftime("%Y-%m-%d %H:%M")
    if item.note:
        data["note"] = item.note
    return data


def plan_to_dict(plan: DayPlan) -> dict[str, Any]:
    data: dict[str, Any] = {
        "date": plan.day.isoformat(),
        "weekday": WEEKDAY_NAMES_TR[plan.day.weekday()],
        "items": [item_to_dict(item, plan.day) for item in plan.items],
    }
    if plan.cancelled:
        data["cancelled"] = [
            {"block_id": c.block_id, "title": c.title, "start": hhmm(c.start), "reason": c.reason}
            for c in plan.cancelled
        ]
    if plan.conflicts:
        data["conflicts"] = [[c.first.title, c.second.title] for c in plan.conflicts]
    if plan.holidays:
        data["holidays"] = plan.holidays
    if plan.tasks:
        data["tasks"] = [
            {"id": t.id, "title": t.title, "status": t.status.value} for t in plan.tasks
        ]
    if plan.week_tasks:
        data["week_tasks"] = [
            {"id": t.id, "title": t.title, "status": t.status.value} for t in plan.week_tasks
        ]
    return data
