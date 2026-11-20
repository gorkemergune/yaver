"""ORM models. Import every model module here so Alembic autogenerate sees it."""

from app.db.models.academic import Course, Holiday, Term
from app.db.models.audit import ChangeLog, LlmUsage
from app.db.models.conversation import Attachment, Conversation, Message
from app.db.models.planning import Followup, Memory, Task
from app.db.models.proposals import Proposal
from app.db.models.schedule import (
    Attendance,
    AttendanceBaseline,
    BlockOverride,
    Event,
    RecurringBlock,
)

__all__ = [
    "Attachment",
    "Attendance",
    "AttendanceBaseline",
    "BlockOverride",
    "ChangeLog",
    "Conversation",
    "Course",
    "Event",
    "Followup",
    "Holiday",
    "LlmUsage",
    "Memory",
    "Message",
    "Proposal",
    "RecurringBlock",
    "Task",
    "Term",
]
