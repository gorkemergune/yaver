"""Effective day plan: recurring blocks + overrides + events + tasks (Europe/Istanbul)."""

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from app.db.models.enums import BlockKind, EventKind, TaskStatus
from app.services.schedule import DayPlan, PlanItem, PlanSources, compute_day_plan
from tests.factories import (
    IST,
    all_day_event,
    block,
    cancel,
    course,
    event,
    holiday,
    local,
    move,
    task,
    term,
)

# Week of Monday 16 November 2026
MON = dt.date(2026, 11, 16)
TUE = MON + dt.timedelta(days=1)
WED = MON + dt.timedelta(days=2)
FRI = MON + dt.timedelta(days=4)
SAT = MON + dt.timedelta(days=5)
SUN = MON + dt.timedelta(days=6)
NEXT_MON = MON + dt.timedelta(days=7)

MONDAY, WEDNESDAY, FRIDAY = 0, 2, 4


def plan(day: dt.date, tz: ZoneInfo = IST, **sources: Any) -> DayPlan:
    return compute_day_plan(day, tz, PlanSources(**sources))


def titles(day_plan: DayPlan) -> list[str]:
    return [item.title for item in day_plan.items]


def only(day_plan: DayPlan, title: str) -> PlanItem:
    matches = [item for item in day_plan.items if item.title == title]
    assert len(matches) == 1, f"expected one {title!r}, got {titles(day_plan)}"
    return matches[0]


def test_sanity_week_layout() -> None:
    assert MON.weekday() == MONDAY
    assert FRI.weekday() == FRIDAY


# --- recurring blocks ------------------------------------------------------------------


class TestRecurringBlocks:
    def test_block_appears_only_on_its_weekday(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")

        assert titles(plan(MON, blocks=[linear])) == ["Linear Algebra"]
        assert titles(plan(TUE, blocks=[linear])) == []
        assert titles(plan(NEXT_MON, blocks=[linear])) == ["Linear Algebra"]

    def test_block_times_are_local_wall_clock(self) -> None:
        item = only(plan(MON, blocks=[block(MONDAY, "09:00", "11:00")]), "Linear Algebra")

        assert item.start == local(MON, "09:00")
        assert item.end == local(MON, "11:00")
        assert item.start.astimezone(dt.UTC).hour == 6  # Istanbul is UTC+3
        assert item.start.tzinfo == IST

    def test_valid_from_and_valid_to_bound_the_block(self) -> None:
        sport = block(
            WEDNESDAY,
            "18:00",
            "19:30",
            title="Spor",
            kind=BlockKind.SPORT,
            valid_from=WED,
            valid_to=WED,
        )

        assert titles(plan(WED, blocks=[sport])) == ["Spor"]
        assert titles(plan(WED - dt.timedelta(days=7), blocks=[sport])) == []
        assert titles(plan(WED + dt.timedelta(days=7), blocks=[sport])) == []

    def test_wall_clock_survives_dst_change(self) -> None:
        berlin = ZoneInfo("Europe/Berlin")  # DST ends Sunday 25 Oct 2026
        before, after = dt.date(2026, 10, 19), dt.date(2026, 10, 26)
        weekly = block(MONDAY, "09:00", "10:00")

        first = only(plan(before, berlin, blocks=[weekly]), "Linear Algebra")
        second = only(plan(after, berlin, blocks=[weekly]), "Linear Algebra")

        assert first.start.time() == second.start.time() == dt.time(9, 0)
        assert first.start.utcoffset() != second.start.utcoffset()


# --- cancelled blocks ------------------------------------------------------------------


class TestCancelledBlock:
    def test_cancelled_block_is_hidden_and_reported(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        lab = block(MONDAY, "13:00", "15:00", title="EE211 Lab", kind=BlockKind.LAB)

        day_plan = plan(MON, blocks=[linear, lab], overrides=[cancel(linear, MON, "Hoca hasta")])

        assert titles(day_plan) == ["EE211 Lab"]
        assert len(day_plan.cancelled) == 1
        cancelled = day_plan.cancelled[0]
        assert cancelled.block_id == linear.id
        assert cancelled.reason == "Hoca hasta"
        assert cancelled.start == local(MON, "09:00")

    def test_cancel_only_affects_that_date(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        overrides = [cancel(linear, MON)]

        assert titles(plan(NEXT_MON, blocks=[linear], overrides=overrides)) == ["Linear Algebra"]
        assert plan(NEXT_MON, blocks=[linear], overrides=overrides).cancelled == []

    def test_cancelling_an_occurrence_that_does_not_happen_is_not_reported(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")

        day_plan = plan(
            MON, blocks=[linear], holidays=[holiday(MON)], overrides=[cancel(linear, MON)]
        )

        assert day_plan.items == []
        assert day_plan.cancelled == []


# --- moved blocks ----------------------------------------------------------------------


class TestMovedBlock:
    def test_moved_block_shows_at_new_time_same_day(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        moved = move(linear, MON, local(MON, "14:00"), local(MON, "16:00"), "Salon değişti")

        item = only(plan(MON, blocks=[linear], overrides=[moved]), "Linear Algebra")

        assert (item.start, item.end) == (local(MON, "14:00"), local(MON, "16:00"))
        assert item.moved_from == local(MON, "09:00")
        assert item.note == "Salon değişti"

    def test_block_moved_to_another_day(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        moved = move(linear, MON, local(SAT, "10:00"), local(SAT, "12:00"), "Telafi")
        sources: dict[str, Any] = {"blocks": [linear], "overrides": [moved]}

        monday = plan(MON, **sources)
        saturday = plan(SAT, **sources)

        assert monday.items == []
        assert monday.cancelled == []
        item = only(saturday, "Linear Algebra")
        assert item.start == local(SAT, "10:00")
        assert item.moved_from == local(MON, "09:00")
        assert titles(plan(NEXT_MON, **sources)) == ["Linear Algebra"]

    def test_move_is_honoured_even_if_original_day_was_a_holiday(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        moved = move(linear, MON, local(SAT, "10:00"), local(SAT, "12:00"), "Tatil telafisi")

        saturday = plan(SAT, blocks=[linear], overrides=[moved], holidays=[holiday(MON)])

        assert titles(saturday) == ["Linear Algebra"]


# --- term boundaries -------------------------------------------------------------------


class TestTermBoundaries:
    fall = term(dt.date(2026, 9, 28), dt.date(2027, 1, 8))

    def test_class_outside_term_is_hidden(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        before_term = dt.date(2026, 9, 21)
        after_term = dt.date(2027, 1, 11)

        assert titles(plan(before_term, terms=[self.fall], blocks=[linear])) == []
        assert titles(plan(after_term, terms=[self.fall], blocks=[linear])) == []
        assert titles(plan(MON, terms=[self.fall], blocks=[linear])) == ["Linear Algebra"]

    def test_term_dates_are_inclusive(self) -> None:
        first_day = block(MONDAY, "09:00", "11:00")  # 28 Sep 2026 is a Monday
        last_day = block(FRIDAY, "09:00", "11:00", title="Son ders")  # 8 Jan 2027 is a Friday

        assert titles(plan(self.fall.start_date, terms=[self.fall], blocks=[first_day])) == [
            "Linear Algebra"
        ]
        assert titles(plan(self.fall.end_date, terms=[self.fall], blocks=[last_day])) == [
            "Son ders"
        ]

    def test_non_academic_blocks_ignore_the_term(self) -> None:
        sport = block(MONDAY, "18:00", "19:30", title="Spor", kind=BlockKind.SPORT)
        summer = dt.date(2026, 7, 6)

        assert titles(plan(summer, terms=[self.fall], blocks=[sport])) == ["Spor"]

    def test_class_follows_its_course_term(self) -> None:
        spring = term(dt.date(2027, 2, 15), dt.date(2027, 6, 4), name="2026-2027 Bahar")
        fall_course = course("MATH221", term_id=self.fall.id)
        linear = block(MONDAY, "09:00", "11:00", course_id=fall_course.id)
        spring_monday = dt.date(2027, 3, 1)
        sources: dict[str, Any] = {
            "terms": [self.fall, spring],
            "courses": [fall_course],
            "blocks": [linear],
        }

        assert titles(plan(MON, **sources)) == ["Linear Algebra"]
        assert titles(plan(spring_monday, **sources)) == []

    def test_without_any_term_the_calendar_is_not_enforced(self) -> None:
        assert titles(plan(MON, blocks=[block(MONDAY, "09:00", "11:00")])) == ["Linear Algebra"]


# --- holidays --------------------------------------------------------------------------


class TestHoliday:
    def test_holiday_hides_classes_but_not_other_blocks(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        lab = block(MONDAY, "13:00", "15:00", title="EE211 Lab", kind=BlockKind.LAB)
        sport = block(MONDAY, "18:00", "19:30", title="Spor", kind=BlockKind.SPORT)
        work = block(MONDAY, "16:00", "17:00", title="Medipol", kind=BlockKind.WORK)

        day_plan = plan(
            MON, blocks=[linear, lab, sport, work], holidays=[holiday(MON, name="Ara tatil")]
        )

        assert titles(day_plan) == ["Medipol", "Spor"]
        assert day_plan.holidays == ["Ara tatil"]
        assert day_plan.cancelled == []

    def test_multi_day_holiday_covers_every_day(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        wednesday = block(WEDNESDAY, "09:00", "11:00", title="EE211")
        week_off = holiday(MON, FRI, name="Ara tatil")

        assert titles(plan(MON, blocks=[linear, wednesday], holidays=[week_off])) == []
        assert titles(plan(WED, blocks=[linear, wednesday], holidays=[week_off])) == []
        assert titles(plan(NEXT_MON, blocks=[linear, wednesday], holidays=[week_off])) == [
            "Linear Algebra"
        ]

    def test_term_specific_holiday_only_affects_that_term(self) -> None:
        fall = term(dt.date(2026, 9, 28), dt.date(2027, 1, 8))
        other = term(dt.date(2026, 10, 5), dt.date(2026, 12, 18), name="Medipol yan dal")
        fall_course = course("MATH221", term_id=fall.id)
        other_course = course("BIO101", term_id=other.id)
        linear = block(MONDAY, "09:00", "11:00", course_id=fall_course.id)
        bio = block(MONDAY, "13:00", "15:00", title="Biyoloji", course_id=other_course.id)

        day_plan = plan(
            MON,
            terms=[fall, other],
            courses=[fall_course, other_course],
            blocks=[linear, bio],
            holidays=[holiday(MON, term_id=other.id)],
        )

        assert titles(day_plan) == ["Linear Algebra"]

    def test_holiday_does_not_hide_events(self) -> None:
        meeting = event(local(MON, "14:00"), local(MON, "15:00"))

        assert titles(plan(MON, events=[meeting], holidays=[holiday(MON)])) == ["Toplantı"]


# --- events and conflicts --------------------------------------------------------------


class TestEventsAndConflicts:
    def test_event_overlapping_a_block_is_reported_as_conflict(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        exam = event(
            local(MON, "10:00"), local(MON, "12:00"), title="EE211 Vize", kind=EventKind.EXAM
        )

        day_plan = plan(MON, blocks=[linear], events=[exam])

        assert titles(day_plan) == ["Linear Algebra", "EE211 Vize"]
        assert len(day_plan.conflicts) == 1
        conflict = day_plan.conflicts[0]
        assert {conflict.first.title, conflict.second.title} == {"Linear Algebra", "EE211 Vize"}

    def test_back_to_back_items_do_not_conflict(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        meeting = event(local(MON, "11:00"), local(MON, "12:00"))

        assert plan(MON, blocks=[linear], events=[meeting]).conflicts == []

    def test_all_day_and_point_events_never_conflict(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        hackathon = all_day_event(MON, MON)
        deadline = event(local(MON, "10:00"), title="Ödev teslimi", kind=EventKind.DEADLINE)

        day_plan = plan(MON, blocks=[linear], events=[hackathon, deadline])

        assert titles(day_plan) == ["Hackathon", "Linear Algebra", "Ödev teslimi"]
        assert day_plan.conflicts == []

    def test_moved_block_conflicts_at_its_new_time(self) -> None:
        linear = block(MONDAY, "09:00", "11:00")
        moved = move(linear, MON, local(TUE, "14:00"), local(TUE, "16:00"))
        meeting = event(local(TUE, "15:00"), local(TUE, "16:00"))

        day_plan = plan(TUE, blocks=[linear], overrides=[moved], events=[meeting])

        assert len(day_plan.conflicts) == 1

    def test_three_overlapping_items_give_three_conflicts(self) -> None:
        linear = block(MONDAY, "09:00", "12:00")
        a = event(local(MON, "10:00"), local(MON, "11:00"), title="A")
        b = event(local(MON, "10:30"), local(MON, "11:30"), title="B")

        assert len(plan(MON, blocks=[linear], events=[a, b]).conflicts) == 3

    def test_items_are_sorted_all_day_first_then_by_start(self) -> None:
        day_plan = plan(
            MON,
            blocks=[block(MONDAY, "13:00", "15:00", title="Öğleden sonra")],
            events=[
                event(local(MON, "08:00"), local(MON, "09:00"), title="Sabah"),
                all_day_event(MON, MON, title="Tüm gün"),
            ],
        )

        assert titles(day_plan) == ["Tüm gün", "Sabah", "Öğleden sonra"]

    def test_point_event_belongs_to_the_day_it_happens(self) -> None:
        deadline = event(local(SUN, "23:59"), title="Proje teslimi", kind=EventKind.DEADLINE)

        assert titles(plan(SUN, events=[deadline])) == ["Proje teslimi"]
        assert titles(plan(NEXT_MON, events=[deadline])) == []


# --- midnight and time zones -----------------------------------------------------------


class TestMidnight:
    def test_event_crossing_midnight_appears_on_both_days(self) -> None:
        party = event(local(FRI, "23:00"), local(SAT, "02:00"), title="Doğum günü")

        friday = only(plan(FRI, events=[party]), "Doğum günü")
        saturday = only(plan(SAT, events=[party]), "Doğum günü")

        assert friday.continues_to_next_day
        assert not friday.continues_from_previous_day
        assert saturday.continues_from_previous_day
        assert not saturday.continues_to_next_day
        assert titles(plan(SUN, events=[party])) == []

    def test_event_ending_exactly_at_midnight_stays_on_its_day(self) -> None:
        late = event(local(FRI, "22:00"), local(SAT, "00:00"), title="Gece dersi")

        assert titles(plan(FRI, events=[late])) == ["Gece dersi"]
        assert titles(plan(SAT, events=[late])) == []
        assert not only(plan(FRI, events=[late]), "Gece dersi").continues_to_next_day

    def test_overnight_recurring_block_spills_into_next_day(self) -> None:
        shift = block(FRIDAY, "22:00", "02:00", title="Gece vardiyası", kind=BlockKind.WORK)

        friday = only(plan(FRI, blocks=[shift]), "Gece vardiyası")
        saturday = only(plan(SAT, blocks=[shift]), "Gece vardiyası")

        assert friday.end == local(SAT, "02:00")
        assert friday.continues_to_next_day
        assert saturday.start == local(FRI, "22:00")
        assert saturday.continues_from_previous_day
        assert titles(plan(SUN, blocks=[shift])) == []

    def test_overnight_block_cancelled_on_its_start_date_is_gone_next_day_too(self) -> None:
        shift = block(FRIDAY, "22:00", "02:00", title="Gece vardiyası", kind=BlockKind.WORK)
        overrides = [cancel(shift, FRI)]

        assert titles(plan(SAT, blocks=[shift], overrides=overrides)) == []
        assert [c.title for c in plan(SAT, blocks=[shift], overrides=overrides).cancelled] == [
            "Gece vardiyası"
        ]

    def test_overnight_event_conflicts_with_early_block_next_day(self) -> None:
        hackathon_night = event(local(FRI, "20:00"), local(SAT, "10:00"), title="Hackathon gecesi")
        sport = block(5, "08:00", "09:00", title="Spor", kind=BlockKind.SPORT)

        saturday = plan(SAT, blocks=[sport], events=[hackathon_night])

        assert titles(saturday) == ["Hackathon gecesi", "Spor"]
        assert len(saturday.conflicts) == 1

    def test_utc_instant_is_placed_on_the_local_day(self) -> None:
        # 20 Nov 22:30 UTC == 21 Nov 01:30 in Istanbul
        quiz = event(
            dt.datetime(2026, 11, 20, 22, 30, tzinfo=dt.UTC),
            dt.datetime(2026, 11, 20, 23, 30, tzinfo=dt.UTC),
            title="Online quiz",
            kind=EventKind.QUIZ,
        )

        assert titles(plan(FRI, events=[quiz])) == []
        item = only(plan(SAT, events=[quiz]), "Online quiz")
        assert item.start == local(SAT, "01:30")

    def test_multi_day_all_day_event(self) -> None:
        hackathon = all_day_event(dt.date(2026, 11, 28), dt.date(2026, 11, 29))

        for day in (dt.date(2026, 11, 28), dt.date(2026, 11, 29)):
            item = only(plan(day, events=[hackathon]), "Hackathon")
            assert item.all_day
        assert titles(plan(dt.date(2026, 11, 27), events=[hackathon])) == []
        assert titles(plan(dt.date(2026, 11, 30), events=[hackathon])) == []


# --- tasks and calendar info -----------------------------------------------------------


class TestTasksAndInfo:
    def test_day_and_week_tasks(self) -> None:
        tasks = [
            task("Ödev 3", on=WED),
            task("Market", on=TUE),
            task("Haftalık okuma", week_of=MON),
            task("Gelecek hafta", week_of=NEXT_MON),
            task("İptal", on=WED, status=TaskStatus.CANCELLED),
            task("Bitti", on=WED, status=TaskStatus.DONE),
        ]

        day_plan = plan(WED, tasks=tasks)

        assert [t.title for t in day_plan.tasks] == ["Ödev 3", "Bitti"]
        assert [t.title for t in day_plan.week_tasks] == ["Haftalık okuma"]

    def test_sunday_belongs_to_the_week_starting_monday(self) -> None:
        assert [t.title for t in plan(SUN, tasks=[task("Okuma", week_of=MON)]).week_tasks] == [
            "Okuma"
        ]

    def test_plan_reports_term_and_timezone(self) -> None:
        fall = term(dt.date(2026, 9, 28), dt.date(2027, 1, 8))

        day_plan = plan(MON, terms=[fall])

        assert day_plan.terms == ["2026-2027 Güz"]
        assert day_plan.timezone == "Europe/Istanbul"
        assert day_plan.day == MON
