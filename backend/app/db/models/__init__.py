"""ORM models. Import every model module here so Alembic autogenerate sees it."""

from app.db.models.academic import Course, Holiday, Term
from app.db.models.conversation import Conversation, Message
from app.db.models.planning import Followup, Memory, Task
from app.db.models.schedule import Attendance, BlockOverride, Event, RecurringBlock

__all__ = [
    "Attendance",
    "BlockOverride",
    "Conversation",
    "Course",
    "Event",
    "Followup",
    "Holiday",
    "Memory",
    "Message",
    "RecurringBlock",
    "Task",
    "Term",
]
