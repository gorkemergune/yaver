"""Ad report files in the chat go to Metrics: saved, compared with the previous period in
code, analysed once on the deep tier (summary + 3 recommendations in the notebook), undoable."""

import datetime as dt
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2
import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ads.intake import CSV_MIME
from app.agent.coordinator import Coordinator
from app.agent.team import TeamConfig
from app.agent.tools import run_tool
from app.api.auth import require_auth
from app.api.uploads import store_pdf
from app.config import Settings, get_settings
from app.core.change_log import undo_change_set
from app.db.models import AdMetric, AdReport, Attachment, EmployeeNote
from app.db.session import get_session
from app.llm.types import LLMRequest, LLMResponse
from app.main import create_app
from app.office.sync import sync_employees
from tests.ads.test_parse import WEEK_1, WEEK_2
from tests.agent_fakes import NOW, REPO_CONFIG, ScriptedLLM, call, example_team, say
from tests.db.test_agent_tools import context
from tests.db.test_vision import stored_image

ANALYSIS: dict[str, Any] = {
    "summary": "Bu hafta 2.850,00 TRY harcandı; Kış Menüsü sonuç başı maliyeti %13,9 düştü.",
    "recommendations": [
        "Hafta Sonu Brunch'tan 250 TRY'yi Kış Menüsü'ne kaydır.",
        "Brunch görselini yenile: CTR %0,89'a indi.",
        "Yeni Takipçi'yi aynı bütçeyle sürdür.",
    ],
}


async def stored_csv(session: AsyncSession, upload_dir: Path, text: str, name: str) -> Attachment:
    raw = text.encode("utf-8")
    attachment = Attachment(
        path=store_pdf(raw, upload_dir, NOW, "csv"),
        mime=CSV_MIME,
        width=0,
        height=0,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        filename=name,
    )
    session.add(attachment)
    await session.flush()
    return attachment


async def team_in_office(session: AsyncSession) -> None:
    with (REPO_CONFIG / "agents.example.yaml").open(encoding="utf-8") as fh:
        await sync_employees(session, TeamConfig.model_validate(yaml.safe_load(fh)), NOW)


def yaver(llm: ScriptedLLM, upload_dir: Path) -> Coordinator:
    return Coordinator(llm, example_team(), Settings(_env_file=None, upload_dir=upload_dir))


class Seen:
    """Metrics' reply step: remembers what it was given."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def __call__(self, request: LLMRequest) -> LLMResponse:
        self.texts.append(next(m.content for m in reversed(request.messages) if m.role == "user"))
        return say("Bu haftanın özeti ve 3 öneri hazır.")


async def count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_a_csv_goes_to_metrics_saved_analysed_and_noted(
    session: AsyncSession, tmp_path: Path
) -> None:
    await team_in_office(session)
    llm, seen = ScriptedLLM(), Seen()
    llm.add("ads", call("ad_analysis", **ANALYSIS), seen)
    first = await stored_csv(session, tmp_path, WEEK_1, "hafta1.csv")

    reply = await yaver(llm, tmp_path).handle(session, "", now=NOW, attachment_ids=[first.id])

    llm.assert_done()
    assert reply.speaker == "ads"  # routed in code, no coordinator turn
    assert llm.purposes[0] == "ads_weekly_report"  # deep tier
    text = seen.texts[0]
    assert (
        "[Reklam raporu 1 (hafta1.csv): Meta, 2-8 Kas 2026, 3 kampanya -> rapor #1 "
        "kaydedildi; karşılaştırılacak önceki dönem yok]" in text
    )
    assert "| Kış Menüsü Tanıtım | 1.200,00 TRY | 15.400 | 231 | %1,50 | 5,19 |" in text
    assert "Analiz (Metrics'in defterine yazıldı):" in text
    assert "1. Hafta Sonu Brunch'tan 250 TRY'yi" in text

    report = await session.get(AdReport, 1)
    assert report is not None
    assert (report.source, report.period_start, report.currency) == (
        "csv",
        dt.date(2026, 11, 2),
        "TRY",
    )
    assert report.recommendations == ANALYSIS["recommendations"]
    assert await count(session, AdMetric) == 3
    note = await session.scalar(select(EmployeeNote).where(EmployeeNote.employee_id == "ads"))
    assert note is not None
    assert note.content.startswith("Reklam analizi, 2-8 Kas 2026 (rapor #1): Bu hafta")
    assert note.content.endswith("3. Yeni Takipçi'yi aynı bütçeyle sürdür.")
    assert reply.change_set_id is not None


async def test_the_next_week_is_compared_and_undo_removes_only_it(
    session: AsyncSession, tmp_path: Path
) -> None:
    await team_in_office(session)
    llm, seen = ScriptedLLM(), Seen()
    llm.add("ads", call("ad_analysis", **ANALYSIS), seen, call("ad_analysis", **ANALYSIS), seen)
    coordinator = yaver(llm, tmp_path)
    week1 = await stored_csv(session, tmp_path, WEEK_1, "hafta1.csv")
    first = await coordinator.handle(session, "", now=NOW, attachment_ids=[week1.id])
    week2 = await stored_csv(session, tmp_path, WEEK_2, "hafta2.csv")

    second = await coordinator.handle(
        session,
        "geçen haftaya göre nasıl?",
        conversation_id=first.conversation_id,
        now=NOW + dt.timedelta(days=7),
        attachment_ids=[week2.id],
    )

    text = seen.texts[1]
    assert text.startswith("geçen haftaya göre nasıl?")
    assert "-> rapor #2 kaydedildi; önceki dönem: rapor #1 (2-8 Kas 2026)]" in text
    assert "| Kış Menüsü Tanıtım | 1.500,00 TRY (+%25,0) |" in text
    assert "| **Toplam** | 2.850,00 TRY (+%14,0) |" in text

    assert second.change_set_id is not None
    await undo_change_set(session, second.change_set_id, NOW + dt.timedelta(days=7))
    assert [r.id for r in (await session.scalars(select(AdReport))).all()] == [1]
    assert await count(session, AdMetric) == 3
    notes = (await session.scalars(select(EmployeeNote.content))).all()
    assert len(notes) == 1
    assert "(rapor #1)" in notes[0]


async def test_the_same_file_twice_is_not_saved_or_analysed_again(
    session: AsyncSession, tmp_path: Path
) -> None:
    await team_in_office(session)
    llm, seen = ScriptedLLM(), Seen()
    llm.add("ads", call("ad_analysis", **ANALYSIS), seen, seen)  # one analysis only
    coordinator = yaver(llm, tmp_path)
    once = await stored_csv(session, tmp_path, WEEK_1, "hafta1.csv")
    first = await coordinator.handle(session, "", now=NOW, attachment_ids=[once.id])
    again = await stored_csv(session, tmp_path, WEEK_1, "hafta1 (1).csv")

    await coordinator.handle(
        session, "", conversation_id=first.conversation_id, now=NOW, attachment_ids=[again.id]
    )

    llm.assert_done()
    assert "rapor #1 bu dosya daha önce kaydedilmişti" in seen.texts[1]
    assert "Analiz (Metrics'in defterine yazıldı)" in seen.texts[1]
    assert (await count(session, AdReport), await count(session, AdMetric)) == (1, 3)


async def test_a_failed_analysis_keeps_the_table(session: AsyncSession, tmp_path: Path) -> None:
    await team_in_office(session)
    llm, seen = ScriptedLLM(), Seen()
    llm.add("ads", say("Analiz yerine düz metin."), say("Yine düz metin."), seen)  # one retry
    attachment = await stored_csv(session, tmp_path, WEEK_1, "hafta1.csv")

    await yaver(llm, tmp_path).handle(session, "", now=NOW, attachment_ids=[attachment.id])

    assert "Analiz şu an yapılamadı (model yanıt vermedi); tablo kaydedildi." in seen.texts[0]
    report = await session.get(AdReport, 1)
    assert report is not None
    assert report.summary is None
    assert await count(session, EmployeeNote) == 0


async def test_a_csv_that_is_not_an_ad_export_goes_to_the_coordinator(
    session: AsyncSession, tmp_path: Path
) -> None:
    llm = ScriptedLLM()
    seen: list[str] = []

    def answer(request: LLMRequest) -> LLMResponse:
        seen.append(next(m.content for m in reversed(request.messages) if m.role == "user"))
        return say("Bu bir reklam raporu değil.")

    llm.add("yaver", answer)
    attachment = await stored_csv(session, tmp_path, "Ad,Yaş,Şehir,Ülke\nA,1,B,C\n", "liste.csv")

    reply = await yaver(llm, tmp_path).handle(session, "", now=NOW, attachment_ids=[attachment.id])

    assert reply.speaker == "yaver"
    assert "[Dosya 1: liste.csv: okunamadı. Harcama sütunu yok" in seen[0]
    assert await count(session, AdReport) == 0


async def test_a_screenshot_of_the_table_is_read_by_sonnet(
    session: AsyncSession, tmp_path: Path
) -> None:
    await team_in_office(session)
    llm, seen = ScriptedLLM(), Seen()
    llm.add(
        "image_reader",
        call("image_contents", kind="ad_report", summary="Ads Manager kampanya tablosu"),
        call(
            "ads_table",
            level="campaign",
            period_text="9 Kas 2026 - 15 Kas 2026",
            currency="try",
            rows=[
                {
                    "name": "Kış Menüsü Tanıtım",
                    "spend": 1500.0,
                    "impressions": 19800,
                    "clicks": 342,
                    "results": 61,
                    "result_type": "Mesajlaşma",
                },
                {"name": "Hafta Sonu Brunch", "spend": 750.0, "impressions": 8100, "clicks": 72},
            ],
            unclear=["Brunch sonuç sayısı silik"],
        ),
    )
    llm.add("ads", call("ad_analysis", **ANALYSIS), seen)
    image = await stored_image(session, tmp_path)

    await yaver(llm, tmp_path).handle(session, "", now=NOW, attachment_ids=[image.id])

    assert llm.purposes[:3] == ["image_read", "ads_image", "ads_weekly_report"]
    report = await session.get(AdReport, 1)
    assert report is not None
    assert (report.source, report.period_start, report.period_end, report.currency) == (
        "image",
        dt.date(2026, 11, 9),
        dt.date(2026, 11, 15),
        "TRY",
    )
    assert "[Reklam raporu 1 (ekran görüntüsü): Meta, 9-15 Kas 2026, 2 kampanya" in seen.texts[0]
    assert "Belirsiz (tahmin edilmedi): Brunch sonuç sayısı silik" in seen.texts[0]
    metrics = (await session.scalars(select(AdMetric).order_by(AdMetric.id))).all()
    assert str(metrics[0].cpc) == "4.3860"  # computed in code: 1500 / 342


async def test_get_ad_report_reads_saved_reports(session: AsyncSession, tmp_path: Path) -> None:
    ctx = context(session, agent_id="ads")
    assert (await run_tool("get_ad_report", {}, ctx))["status"] == "no_reports"

    await team_in_office(session)
    llm = ScriptedLLM()
    llm.add("ads", call("ad_analysis", **ANALYSIS), say("tamam"))
    week1 = await stored_csv(session, tmp_path, WEEK_1, "hafta1.csv")
    await yaver(llm, tmp_path).handle(session, "", now=NOW, attachment_ids=[week1.id])
    llm.add("ads", call("ad_analysis", **ANALYSIS), say("tamam"))
    week2 = await stored_csv(session, tmp_path, WEEK_2, "hafta2.csv")
    await yaver(llm, tmp_path).handle(session, "", now=NOW, attachment_ids=[week2.id])

    latest = await run_tool("get_ad_report", {}, ctx)
    older = await run_tool("get_ad_report", {"report_id": 1}, ctx)

    assert latest["report_id"] == 2
    assert "-> rapor #2 kayıtlı; önceki dönem: rapor #1" in latest["report"]
    assert "Analiz (Metrics'in defterine yazıldı)" in latest["report"]
    assert latest["other_reports"] == [{"report_id": 1, "period": "2-8 Kas 2026"}]
    assert "karşılaştırılacak önceki dönem yok" in older["report"]
    assert "error" in await run_tool("get_ad_report", {"report_id": 99}, ctx)


async def test_csv_uploads_are_kept_as_they_are(session: AsyncSession, tmp_path: Path) -> None:
    app = create_app()
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, upload_dir=tmp_path)

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    raw = WEEK_2.encode("utf-8")
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/uploads", files={"files": ("Kampanyalar.csv", raw, "text/csv")}
        )

    assert response.status_code == 200, response.text
    (view,) = response.json()["attachments"]
    attachment = await session.get(Attachment, view["id"])
    assert attachment is not None
    assert (attachment.mime, attachment.filename) == (CSV_MIME, "Kampanyalar.csv")
    assert attachment.path.endswith(".csv")
    assert (tmp_path / attachment.path).read_bytes() == raw


async def test_recommendations_in_one_string_are_split_and_a_bad_call_is_retried(
    session: AsyncSession, tmp_path: Path
) -> None:
    await team_in_office(session)
    llm, seen = ScriptedLLM(), Seen()
    two = {**ANALYSIS, "recommendations": ANALYSIS["recommendations"][:2]}
    joined = {
        **ANALYSIS,
        "recommendations": [
            " ".join(f"{i}. {r}" for i, r in enumerate(ANALYSIS["recommendations"], start=1))
        ],
    }
    llm.add("ads", call("ad_analysis", **two), call("ad_analysis", **joined), seen)
    attachment = await stored_csv(session, tmp_path, WEEK_1, "hafta1.csv")

    await yaver(llm, tmp_path).handle(session, "", now=NOW, attachment_ids=[attachment.id])

    llm.assert_done()
    assert llm.purposes[:2] == ["ads_weekly_report", "ads_weekly_report"]
    retry = llm.requests[1][1]
    assert retry.system is not None
    assert "exactly 3 separate strings" in retry.system
    report = await session.get(AdReport, 1)
    assert report is not None
    assert report.recommendations == ANALYSIS["recommendations"]
