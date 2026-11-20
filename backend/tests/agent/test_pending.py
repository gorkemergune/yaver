"""Open questions (app.agent.pending): what a tool result leaves open, and how a short
answer picks an option."""

import datetime as dt

from app.agent.coordinator import looks_english
from app.agent.pending import Option, PendingAction, bind, date_option, observe

WEDNESDAY = date_option(dt.date(2026, 11, 18))


def waiting(*options: Option, tool: str = "log_attendance", slot: str = "dates") -> PendingAction:
    return PendingAction(
        "academic", "Geçen salı EE211'e gitmedim", tool=tool, slot=slot, options=list(options)
    )


def picked(pending: PendingAction, text: str) -> str | None:
    binding = bind(pending, text)
    return binding.option.label if binding.option else binding.kind


def test_a_suggested_day_is_taken_by_yes_or_by_its_name() -> None:
    one = waiting(WEDNESDAY)
    for text in (
        "Evet, çarşamba",
        "evet",
        "Çarşamba",
        "çarşambaya kaydet",
        "evet o gün",
        "18 Kasım",
    ):
        assert picked(one, text) == "2026-11-18 Çarşamba", text


def test_another_day_no_or_a_new_message_is_not_an_option() -> None:
    one = waiting(WEDNESDAY)
    assert picked(one, "perşembe") == "reply"  # the yaver hears it with its question
    assert picked(one, "hayır, boşver") == "decline"
    assert picked(one, "yarın ne var?") == "other"
    long = "aslında o hafta hiç gitmedim, salı çarşamba perşembe hepsini kaçırdım sanırım"
    assert picked(one, long) == "other"


def test_pazartesi_is_not_pazar() -> None:
    sunday = waiting(date_option(dt.date(2026, 11, 22)))
    assert picked(sunday, "pazartesi") == "reply"
    assert picked(sunday, "pazar") == "2026-11-22 Pazar"


BLOCKS = [
    {"block_id": 4, "title": "EE 211", "kind": "class", "weekday": "Salı", "start": "14:00",
     "end": "16:00"},
    {"block_id": 6, "title": "EE 211 Lab", "kind": "lab", "weekday": "Salı", "start": "17:00",
     "end": "19:00"},
]  # fmt: skip


def two_blocks() -> PendingAction:
    result = {"error": "'ee211' matches several blocks", "candidates": BLOCKS}
    args = {"date": "2026-11-24", "block": "ee211", "on_weekday": None}
    pending = observe("academic", "yarın ee211 iptal", "cancel_block_on", args, result)
    assert pending is not None
    return pending


def test_candidates_become_options_that_name_the_block_by_id() -> None:
    pending = two_blocks()
    assert pending.slot == "block"
    assert [o.value for o in pending.options] == ["#4", "#6"]
    lab = bind(pending, "lab olan").option
    assert lab is not None
    assert pending.call(lab) == ("cancel_block_on", {"date": "2026-11-24", "block": "#6"})


def test_ordinals_and_hours_pick_one_of_several() -> None:
    pending = two_blocks()
    assert picked(pending, "2.si") == "EE 211 Lab Salı 17:00-19:00"
    assert picked(pending, "ikincisi") == "EE 211 Lab Salı 17:00-19:00"
    assert picked(pending, "ilki") == "EE 211 Salı 14:00-16:00"
    assert picked(pending, "sonuncu") == "EE 211 Lab Salı 17:00-19:00"
    assert picked(pending, "14'teki") == "reply"  # "14teki": not a key, the yaver decides
    assert picked(pending, "14") == "EE 211 Salı 14:00-16:00"
    assert picked(pending, "evet") == "reply"  # yes to which one?


def test_courses_tasks_and_attendance_suggestions() -> None:
    courses = observe(
        "academic",
        "linear",
        "set_absence_limit",
        {"course": "math", "hours": 6},
        {"error": "x", "candidates": [{"code": "MATH 221", "name": "Linear Algebra"},
                                      {"code": "MATH 231", "name": "Calculus"}]},
    )  # fmt: skip
    assert courses is not None
    option = bind(courses, "linear olan").option
    assert option is not None
    assert courses.call(option) == ("set_absence_limit", {"course": "MATH 221", "hours": 6})

    tasks = observe(
        "agenda",
        "raporu bitirdim",
        "complete_task",
        {"title": "rapor"},
        {"error": "x", "candidates": [{"task_id": 3, "title": "Staj raporu"},
                                      {"task_id": 5, "title": "Lab raporu"}]},
    )  # fmt: skip
    assert tasks is not None
    option = bind(tasks, "staj").option
    assert option is not None
    assert tasks.call(option) == ("complete_task", {"task_id": 3})

    attendance = observe(
        "academic",
        "geçen salı ee211",
        "log_attendance",
        {"course": "EE211", "dates": ["2026-11-17"]},
        {"logged": [], "not_logged": [{"date": "2026-11-17 Salı", "problem": "no class",
                                       "suggest": ["2026-11-18 Çarşamba"]}]},
    )  # fmt: skip
    assert attendance is not None
    assert [o.label for o in attendance.options] == ["2026-11-18 Çarşamba"]
    assert observe("academic", "x", "log_attendance", {}, {"logged": [{"date": "x"}]}) is None
    assert observe("academic", "x", "cancel_block_on", {}, {"error": "no block"}) is None


def test_stored_and_loaded_back() -> None:
    pending = two_blocks()
    pending.created_at = "2026-11-23T07:00:00+00:00"
    again = PendingAction.load(pending.dump())
    assert again == pending
    assert not again.expired(dt.datetime(2026, 11, 23, 12, tzinfo=dt.UTC))
    assert again.expired(dt.datetime(2026, 11, 24, 12, tzinfo=dt.UTC))
    assert PendingAction.load({"agent_id": "x", "unknown": 1}) is None
    assert PendingAction.load(None) is None


def test_english_answers_are_noticed() -> None:
    assert looks_english("Friday has recorded the class for you, and the total is 2 hours.")
    assert not looks_english("Friday: 18 Kasım Çarşamba EE211 Lab devamsızlığını kaydetti.")
    assert not looks_english("Yarın: Linear Algebra 09:00-11:00, Iceberg meeting 14:00.")
