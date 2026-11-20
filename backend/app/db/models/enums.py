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


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    DISCARDED = "discarded"


class ChangeOp(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
