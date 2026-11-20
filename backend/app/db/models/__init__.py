"""ORM models. Import every model module here so Alembic autogenerate sees it."""

from app.db.models.academic import Course, Holiday, Term
from app.db.models.audit import ChangeLog, LlmUsage
from app.db.models.auth import AuthSession
from app.db.models.conversation import Attachment, Conversation, Message
from app.db.models.jobs import JobRun
from app.db.models.materials import CourseMaterial, MaterialChunk, SyllabusWeek
from app.db.models.planning import Followup, Memory, Task
from app.db.models.proposals import Proposal
from app.db.models.push import PushSubscription
from app.db.models.schedule import (
    Attendance,
    AttendanceBaseline,
    BlockOverride,
    Event,
    RecurringBlock,
)
from app.db.models.screen import ScreenTimeDay
from app.db.models.weeks import WeekLabel

__all__ = [
    "Attachment",
    "Attendance",
    "AttendanceBaseline",
    "AuthSession",
    "BlockOverride",
    "ChangeLog",
    "Conversation",
    "Course",
    "CourseMaterial",
    "Event",
    "Followup",
    "Holiday",
    "JobRun",
    "LlmUsage",
    "MaterialChunk",
    "Memory",
    "Message",
    "Proposal",
    "PushSubscription",
    "RecurringBlock",
    "ScreenTimeDay",
    "SyllabusWeek",
    "Task",
    "Term",
    "WeekLabel",
]
