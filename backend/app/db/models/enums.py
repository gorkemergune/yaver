from enum import StrEnum


class BlockKind(StrEnum):
    CLASS = "class"
    LAB = "lab"
    SPORT = "sport"
    WORK = "work"
    OTHER = "other"


# Kinds that follow the academic calendar: hidden outside the term and on holidays.
ACADEMIC_BLOCK_KINDS = frozenset({BlockKind.CLASS, BlockKind.LAB})


class OverrideAction(StrEnum):
    CANCEL = "cancel"
    MOVE = "move"


class EventKind(StrEnum):
    EXAM = "exam"
    QUIZ = "quiz"
    MAKEUP = "makeup"
    MEETING = "meeting"
    DEADLINE = "deadline"
    HACKATHON = "hackathon"
    OTHER = "other"


class AttendanceStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    EXCUSED = "excused"


class TaskScope(StrEnum):
    DAY = "day"
    WEEK = "week"


class TaskStatus(StrEnum):
    TODO = "todo"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskSource(StrEnum):
    USER = "user"
    AGENT = "agent"
    WEEKLY_PLAN = "weekly_plan"


class FollowupStatus(StrEnum):
    WAITING = "waiting"
    POSITIVE = "positive"
    NEGATIVE = "negative"
    DONE = "done"


class FollowupCheckRule(StrEnum):
    DAILY = "daily"
    EVERY_N_DAYS = "every_n_days"
    ON_DATE = "on_date"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class ConversationMode(StrEnum):
    CHAT = "chat"
    ONBOARDING = "onboarding"


class ProposalKind(StrEnum):
    SCHEDULE = "schedule"  # weekly blocks
    EVENTS = "events"  # one-off events (exam notice, poster)
    TASKS = "tasks"  # the Sunday weekly plan draft
    SYLLABUS = "syllabus"  # weekly topics read from a syllabus PDF


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    DISCARDED = "discarded"


class ChangeOp(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class Activity(StrEnum):
    """What an employee is doing (docs/OFFICE.md). Idle variations such as walking around
    are chosen by the web app from BREAK; the backend never writes them."""

    WORKING = "working"  # running an LLM / tool call, or has work queued
    MEETING = "meeting"  # handing work over (delegation) or a standup
    BREAK = "break"  # idle, empty inbox
    OFF = "off"  # outside working hours (O5)


class DeskRow(StrEnum):
    OFFICE = "office"  # the coordinator's own room
    BACK = "back"
    FRONT = "front"


class TaskOrigin(StrEnum):
    USER = "user"  # the user asked this employee (chat, direct chat)
    YAVER = "yaver"  # delegated by the coordinator
    SHIFT = "shift"  # a scheduled job of the employee


class EmployeeTaskStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
