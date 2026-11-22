"""Materials ingest helpers without a database: dates as written, week checks, .docx text,
printed tables of contents, kinds, section numbers in a week's readings."""

import datetime as dt
import io
import zipfile

from app.materials import mapping, toc
from app.materials.ingest import guess_kind
from app.materials.syllabus import WeekIn, check_weeks, day_month, week_of
from app.materials.text import docx_pages
from app.materials.weekly import compact

TERM = dt.date(2026, 9, 28)
D = chr(0x2013)  # en dash, as syllabi write ranges


def test_written_dates_are_read_in_code() -> None:
    assert day_month(f"28 Eylül{D}2 Ekim", TERM) == dt.date(2026, 9, 28)
    assert day_month(f"5{D}9 Ekim", TERM) == dt.date(2026, 10, 5)
    assert day_month("November 27, 2026, Friday, 16:00", TERM) == dt.date(2026, 11, 27)
    assert day_month("10/November/2026", TERM) == dt.date(2026, 11, 10)
    assert day_month("January 07, 2027", TERM) == dt.date(2027, 1, 7)
    assert day_month("4 Ocak", TERM) == dt.date(2027, 1, 4)  # autumn term: next January
    assert day_month("Week 9", TERM) is None
    assert week_of(dt.date(2026, 11, 27), TERM) == 9


def test_week_dates_are_checked_against_the_term() -> None:
    weeks = [
        WeekIn(week_no=1, dates=f"28 Eylül{D}2 Ekim", topics="Giriş"),
        WeekIn(week_no=2, dates=f"12{D}16 Ekim", topics="Kayık hafta"),
        WeekIn(week_no=3, topics="Tarihsiz"),
    ]
    check = check_weeks(weeks, TERM)
    assert check.ok == 1
    assert check.mismatches == [f"hafta 2 '12{D}16 Ekim' -> dönemin 3. haftası"]


def test_docx_text_is_read_from_its_xml() -> None:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for text in ("HUM 103 Uygarlık Tarihi", "Vize: 15 Kasım &amp; Final", "")
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    assert docx_pages(buffer.getvalue()) == ["HUM 103 Uygarlık Tarihi\nVize: 15 Kasım & Final"]


def test_a_printed_contents_page_becomes_sections_with_pdf_pages() -> None:
    pages = [
        "Lab Book",
        "Contents\n1 Laboratory Rules 2\n4 Experiments 5\n4.a Experiment #1\n"
        "Kirchoff's Voltage and Current Laws . . . . . 6\n4.b Experiment #2\n"
        "Voltage and Current Division . . . . 8",
        "",
        "Laboratory Rules\n...",
        "",
        "Experiments",
        "Kirchoff's Voltage and Current Laws and Power Balance",
        "",
        "Voltage and Current Division",
        "end",
    ]
    found = toc.sections(b"not a pdf", pages)
    titles = [(s.number, s.title, s.page_start, s.page_end) for s in found]
    assert titles == [  # printed page + 1 (the cover), as most titles agree
        ("1", "Laboratory Rules", 3, 5),
        ("4", "Experiments", 6, 10),
        ("4.a", "Experiment #1: Kirchoff's Voltage and Current Laws", 7, 8),
        ("4.b", "Experiment #2: Voltage and Current Division", 9, 10),
    ]


def test_kinds_and_codes() -> None:
    assert guess_kind("CSE221 - 2026 Fall - Homework 1.pdf", [], False) == "homework"
    assert guess_kind("cse221-extra/Labwork01 - Part I.pdf", [], False) == "lab"
    assert guess_kind("TKL 201 İzlence Güz 2026.pdf", [], False) == "syllabus"
    assert guess_kind("f26_221.pdf", ["Syllabus for Math 221"], False) == "syllabus"
    assert guess_kind("leon.pdf", ["x"] * 300, True) == "book"
    assert guess_kind("notes.pdf", ["x"] * 300, False) == "notes"
    assert compact("CSE 211") == compact("cse-211") == "cse211"


def test_book_sections_named_in_the_readings_need_no_model() -> None:
    plan = [
        mapping.PlanWeek(1, "Systems of Linear Equations", "1.1, 1.2"),
        mapping.PlanWeek(2, "Matrix Arithmetic", "1.3, 1.4"),
        mapping.PlanWeek(8, "Change of Basis", "3.5, 3.6"),
    ]
    entries = [
        mapping.Entry("1.1", "Systems"),
        mapping.Entry("1.4", "Matrix Algebra"),
        mapping.Entry("3.5", "Change of Basis"),
        mapping.Entry("1.10", "Not in the plan"),
        mapping.Entry(None, "Preface"),
    ]
    assert mapping.by_readings(entries, plan) == {0: [1], 1: [2], 2: [8]}
