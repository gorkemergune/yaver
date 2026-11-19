"""ORM models. Import every model module here so Alembic autogenerate sees it."""

from app.db.models.academic import Course, Holiday, Term
from app.db.models.schedule import Attendance, BlockOverride, Event, RecurringBlock

__all__ = [
    "Attendance",
    "BlockOverride",
    "Course",
    "Event",
    "Holiday",
    "RecurringBlock",
    "Term",
]
