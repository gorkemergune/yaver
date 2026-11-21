"""Intents and their owners, fixed in code (no imports: app.agent.tools.routing and
app.agent.intents both read it)."""

from typing import Literal

Intent = Literal[
    "event",  # a one-off thing on the calendar: meeting, breakfast, appointment, trip, deadline
    "exam",  # exam / quiz / midterm / final, its topics
    "class",  # the weekly class schedule; one class cancelled / moved / make-up
    "attendance",  # missed classes, absence limits and totals
    "course_note",  # lecture notes, syllabus, course content questions, study sheets
    "task",  # to-dos ("görev", "yapılacak", "bitirdim")
    "followup",  # waiting for an answer, "her gün sor", news on such a thing
    "sport",  # sport, workouts, gym, screen time, games
    "content",  # social media posts, content ideas, content calendar
    "ads",  # ad reports, campaigns, ad performance
    "startup",  # the startup, its repo, competitors, its week hand-ins
    "career",  # internships, jobs, CV, applications
    "social",  # friends, birthdays, social plans and gifts
    "memory",  # a lasting fact about the user ("cuma günleri Medipol'deyim")
    "question",  # what is on the plan, what was done; any question to the coordinator
    "undo",  # "geri al"
    "answer",  # the reply to the open question shown below (only when one is open)
    "other",  # chit-chat, thanks, anything else
]

# intent -> employee id (agents.yaml). None: the coordinator itself.
OWNERS: dict[str, str | None] = {
    "event": "agenda",
    "task": "agenda",
    "followup": "agenda",
    "exam": "academic",
    "class": "academic",
    "attendance": "academic",
    "course_note": "academic",
    "sport": "discipline",
    "content": "content",
    "ads": "ads",
    "startup": "startup",
    "career": "career",
    "social": "social",
    "memory": None,
    "question": None,
    "undo": None,
    "answer": None,  # the employee that asked (the coordinator knows who)
    "other": None,
}
# Areas a specialist may hand a message back with (handoff): every owned intent.
AREAS = tuple(intent for intent, owner in OWNERS.items() if owner is not None)


def followup_owner(owner_id: str | None) -> str:
    """Whose a follow-up is: its owner (Mentor for applications), else the agenda's."""
    return owner_id or str(OWNERS["followup"])
