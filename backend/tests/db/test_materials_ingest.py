"""The materials folder -> database (app.materials.ingest) with a scripted model: syllabi
create their courses and weekly plans, a lab sheet is mapped to its week, a second run is a
no-op (same files), a file of no known course is reported, not guessed."""

import io
import shutil
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Course, CourseBook, CourseMaterial, MaterialSection, SyllabusWeek
from app.materials.ingest import parse_args, run
from tests.agent_fakes import REPO_CONFIG, ScriptedLLM, call
from tests.db.test_materials import fake_embeddings  # noqa: F401 - autouse fixture

EXAMPLES = REPO_CONFIG.parent / "examples" / "syllabus"


def docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    return buffer.getvalue()


def folder(tmp_path: Path) -> Path:
    root = tmp_path / "materials"
    (root / "ee211-extra").mkdir(parents=True)
    shutil.copy(EXAMPLES / "ee211_syllabus.pdf", root / "EE211 syllabus.pdf")
    shutil.copy(EXAMPLES / "ee211_hafta7_notlar.pdf", root / "ee211-extra" / "Lab 3 sheet.pdf")
    (root / "HUM 103 İzlence.docx").write_bytes(
        docx(
            "HUM 103 Uygarlık Tarihi izlencesi, 2026-27 Güz dönemi",
            "1. Hafta 28 Eylül: Giriş, uygarlık kavramı. Okuma: Bölüm 1 (s. 1-20)",
        )
    )
    (root / "random.docx").write_bytes(
        docx(
            "Bir yemek tarifi: makarna, domates, fesleğen, zeytinyağı ve biraz da parmesan;",
            "on dakika kaynat, süz ve sıcak servis et.",
        )
    )
    return root


EE211 = call(
    "syllabus",
    course_code="EE 211",
    course_name="Circuit Theory",
    books=[{"title": "Fundamentals of Electric Circuits", "required": True}],
    weeks=[
        {"week_no": 1, "dates": "28 Eylül", "topics": "Giriş, Ohm yasası"},
        {"week_no": 2, "dates": "12 Ekim", "topics": "Kirchhoff yasaları", "lab": "Lab 1"},
        {"week_no": 3, "topics": "Düğüm analizi", "lab": "Lab 3: düğüm gerilimleri"},
    ],
    exams=[{"kind": "midterm", "when": "10 Kasım 2026", "week_no": 7}],
)
HUM = call(
    "syllabus",
    course_code="HUM 103",
    course_name="Uygarlık Tarihi",
    weeks=[{"week_no": 1, "dates": "28 Eylül", "topics": "Giriş", "readings": "Bölüm 1"}],
)
LAB_WEEKS = call("map_weeks", entries=[{"index": 0, "weeks": [3]}])


async def test_a_folder_becomes_courses_weeks_and_mapped_sheets(
    session: AsyncSession, tmp_path: Path
) -> None:
    root = folder(tmp_path)
    args = parse_args(
        [str(root), "--term-start", "2026-09-28", "--create-courses", "--upload-dir", str(tmp_path)]
    )
    sessionmaker = async_sessionmaker(session.bind, expire_on_commit=False)
    llm = ScriptedLLM({"document_reader": [EE211, HUM, LAB_WEEKS]})

    report = await run(args, sessionmaker=sessionmaker, llm=llm)
    again = await run(args, sessionmaker=sessionmaker, llm=ScriptedLLM())

    llm.assert_done()
    by_path = {f.path: f for f in report.files}
    assert sorted(report.courses_created) == ["EE 211", "HUM 103"]
    assert by_path["EE211 syllabus.pdf"].weeks == 3
    assert "tarih kontrolü: 1 hafta tutuyor" in by_path["EE211 syllabus.pdf"].notes
    assert "tarih uyuşmuyor: hafta 2 '12 Ekim' -> dönemin 3. haftası" in (
        by_path["EE211 syllabus.pdf"].notes
    )
    assert by_path["ee211-extra/Lab 3 sheet.pdf"].week_nos == [3]
    assert by_path["random.docx"].status == "unclear"  # never a guess
    assert {f.status for f in again.files} == {"skipped", "unclear"}

    courses = {c.code: c for c in (await session.scalars(select(Course))).all()}
    weeks = (
        await session.scalars(
            select(SyllabusWeek)
            .where(SyllabusWeek.course_id == courses["EE 211"].id)
            .order_by(SyllabusWeek.week_no)
        )
    ).all()
    assert [(w.week_no, w.lab) for w in weeks] == [
        (1, None),
        (2, "Lab 1"),
        (3, "Lab 3: düğüm gerilimleri"),
    ]
    book = await session.scalar(select(CourseBook))
    assert book is not None
    assert (book.title, book.required) == ("Fundamentals of Electric Circuits", True)
    sheet = await session.scalar(
        select(CourseMaterial).where(CourseMaterial.title == "Lab 3 sheet.pdf")
    )
    assert sheet is not None
    assert (sheet.kind, sheet.week_no) == ("lab", 3)
    section = await session.scalar(
        select(MaterialSection).where(MaterialSection.material_id == sheet.id)
    )
    assert section is not None
    assert section.week_nos == [3]
    hum = await session.scalar(
        select(SyllabusWeek).where(SyllabusWeek.course_id == courses["HUM 103"].id)
    )
    assert hum is not None
    assert hum.readings == "Bölüm 1"
