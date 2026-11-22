import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.agent.tools.matching import require_course
from app.agent.tools.schedule import ISO_DATE
from app.db.models import Event
from app.db.models.enums import EventKind
from app.startup import meeting

EventKindName = Literal["exam", "quiz", "makeup", "meeting", "deadline", "hackathon", "other"]


def describe_event(event: Event, ctx: ToolContext) -> dict[str, Any]:
    start = event.start_at.astimezone(ctx.tz)
    data: dict[str, Any] = {
        "event_id": event.id,
        "kind": event.kind.value,
        "title": event.title,
        "date": start.date().isoformat(),
    }
    if event.all_day:
        data["all_day"] = True
        if event.end_at is not None:
            last = (event.end_at.astimezone(ctx.tz) - dt.timedelta(days=1)).date()
            if last != start.date():
                data["end_date"] = last.isoformat()
    else:
        data["start"] = start.strftime("%H:%M")
        if event.end_at is not None:
            end = event.end_at.astimezone(ctx.tz)
            data["end"] = end.strftime("%H:%M")
            if end.date() != start.date():
                data["end_date"] = end.date().isoformat()
    if event.location:
        data["location"] = event.location
    return data


def _times(
    ctx: ToolContext,
    date: dt.date,
    start_time: dt.time | None,
    end_time: dt.time | None,
    end_date: dt.date | None,
) -> tuple[dt.datetime, dt.datetime | None, bool]:
    """(start_at, end_at, all_day) as aware datetimes in APP_TIMEZONE."""
    if start_time is None:  # all-day, possibly several days
        last = end_date or date
        if last < date:
            raise ToolError("end_date is before date")
        return ctx.local(date, dt.time()), ctx.local(last + dt.timedelta(days=1), dt.time()), True
    start = ctx.local(date, start_time)
    if end_time is None:
        return start, None, False
    end = ctx.local(end_date or date, end_time)
    if end <= start and end_date is None:
        end += dt.timedelta(days=1)  # "23:00-02:00" ends the next day
    if end <= start:
        raise ToolError("end is not after start")
    return start, end, False


class AddEventArgs(BaseModel):
    kind: EventKindName
    title: str
    date: dt.date = Field(description=ISO_DATE)
    start_time: dt.time | None = Field(None, description="HH:MM; omit for an all-day event")
    end_time: dt.time | None = Field(None, description="HH:MM; omit for a point in time")
    end_date: dt.date | None = Field(None, description="last day of a multi-day event")
    location: str | None = None
    course: str | None = Field(None, description="course code/name for exams, quizzes")
    notes: str | None = None
    topics: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="exam / quiz topics the user named (linked list, stack...)",
    )


@tool(
    "add_event",
    "Add a one-off event: exam, quiz, make-up class, meeting, deadline, hackathon... "
    "Without start_time it is all-day.",
    AddEventArgs,
    mutates=True,
)
async def add_event(args: AddEventArgs, ctx: ToolContext) -> ToolResult:
    start, end, all_day = _times(ctx, args.date, args.start_time, args.end_time, args.end_date)
    course = await require_course(ctx, args.course) if args.course else None
    event = Event(
        kind=EventKind(args.kind),
        title=args.title,
        start_at=start,
        end_at=end,
        all_day=all_day,
        location=args.location,
        course_id=course.id if course else None,
        notes=with_topics(args.notes, args.topics),
        # a startup meeting is Venture's to prepare for (before the snapshot: undo knows it)
        owner_id=meeting.owner_for(args.kind, args.title, args.notes, args.location),
    )
    ctx.session.add(event)
    await ctx.recorder.created(event)
    result: dict[str, Any] = {"created": describe_event(event, ctx)}
    if event.owner_id is not None:
        result["linked_to"] = {
            "employee": event.owner_id,
            "prepares": "an hour before: the latest week's presentation draft per member "
            "and whose folder is empty, as a chat message",
            # live: the link was made but the reply didn't mention it
            "tell_user": f"{meeting.name_of(event.owner_id)} toplantıdan 1 saat önce haftanın "
            "sunum taslağını ve klasörü boş olanları yazacak",
        }
    if event.kind is EventKind.EXAM:
        from app.jobs import exam_prep

        days = (args.date - ctx.today).days
        if exam_prep.MIN_LEAD_DAYS <= days <= exam_prep.LEAD_DAYS:
            result["review_plan"] = "drafted now, it comes as a separate chat message in a moment"
        elif days > exam_prep.LEAD_DAYS:
            result["review_plan"] = "proposed in the chat a week before the exam"
    return result


TOPICS = "Konular: "


def with_topics(notes: str | None, topics: list[str]) -> str | None:
    """The topics go into the event's notes ("Konular: linked list, stack, queue"), where
    the review plan (app.jobs.exam_prep) reads them when there is no syllabus."""
    clean = [t.strip() for t in topics if t.strip()]
    if not clean:
        return notes
    line = TOPICS + ", ".join(clean)
    return f"{notes.strip()}\n{line}" if notes and notes.strip() else line


class UpdateEventArgs(BaseModel):
    event_id: int = Field(description="from get_day_plan (type=event, id)")
    title: str | None = None
    date: dt.date | None = None
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    location: str | None = None
    notes: str | None = None


async def _event(ctx: ToolContext, event_id: int) -> Event:
    event = await ctx.session.get(Event, event_id)
    if event is None:
        raise ToolError(f"no event with id {event_id}; look it up with get_day_plan")
    return event


@tool("update_event", "Change an event found with get_day_plan.", UpdateEventArgs, mutates=True)
async def update_event(args: UpdateEventArgs, ctx: ToolContext) -> ToolResult:
    event = await _event(ctx, args.event_id)
    before = ctx.recorder.before_update(event)
    if args.date or args.start_time or args.end_time:
        current = describe_event(event, ctx)
        date = args.date or dt.date.fromisoformat(current["date"])
        start_time = args.start_time or (
            None if event.all_day else event.start_at.astimezone(ctx.tz).time()
        )
        end_time = args.end_time
        if end_time is None and event.end_at is not None and not event.all_day:
            end_time = event.end_at.astimezone(ctx.tz).time()
        event.start_at, event.end_at, event.all_day = _times(ctx, date, start_time, end_time, None)
    if args.title is not None:
        event.title = args.title
    if args.location is not None:
        event.location = args.location
    if args.notes is not None:
        event.notes = args.notes
    await ctx.recorder.updated(event, before)
    return {"updated": describe_event(event, ctx)}


class DeleteEventArgs(BaseModel):
    event_id: int


@tool(
    "delete_event",
    "Delete one event (get its id from get_day_plan).",
    DeleteEventArgs,
    mutates=True,
)
async def delete_event(args: DeleteEventArgs, ctx: ToolContext) -> ToolResult:
    event = await _event(ctx, args.event_id)
    description = describe_event(event, ctx)
    await ctx.recorder.deleted(event)
    return {"deleted": description}
