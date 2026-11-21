"""ORM models. Import every model module here so Alembic autogenerate sees it."""

from app.db.models.academic import Course, Holiday, Term
from app.db.models.ads import AdMetric, AdReport
from app.db.models.audit import ChangeLog, LlmUsage
from app.db.models.auth import AuthSession, DeviceKey
from app.db.models.conversation import Attachment, Conversation, Message
from app.db.models.jobs import JobRun
from app.db.models.materials import CourseMaterial, MaterialChunk, SyllabusWeek
from app.db.models.office import Employee, EmployeeNote, EmployeeState, EmployeeTask
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
from app.db.models.secrets import AppSecret
from app.db.models.study import StudySheet
from app.db.models.weeks import WeekLabel

__all__ = [
    "AdMetric",
    "AdReport",
    "AppSecret",
    "Attachment",
    "Attendance",
    "AttendanceBaseline",
    "AuthSession",
    "BlockOverride",
    "ChangeLog",
    "Conversation",
    "Course",
    "CourseMaterial",
    "DeviceKey",
    "Employee",
    "EmployeeNote",
    "EmployeeState",
    "EmployeeTask",
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
    "StudySheet",
    "SyllabusWeek",
    "Task",
    "Term",
    "WeekLabel",
]
