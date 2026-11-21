"""Meta Ads Manager CSV exports parsed in code: both interface languages, both number
formats, the total row, computed metrics, written periods."""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from app.ads.parse import AdsParseError, looks_like_csv, parse_meta_csv, parse_period
from app.ads.report import (
    change,
    comparison_table,
    period_text,
    split_recommendations,
    totals,
    tr_number,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "meta-ads"

WEEK_1 = (
    "Reporting starts,Reporting ends,Campaign name,Results,Result indicator,Reach,"
    "Impressions,Cost per result,Amount spent (TRY),Link clicks,"
    "CPC (cost per link click) (TRY),CTR (link click-through rate)\n"
    "2026-11-02,2026-11-08,Kış Menüsü Tanıtım,42,Messaging conversations started,9800,"
    "15400,28.57,1200.00,231,5.19,1.50\n"
    "2026-11-02,2026-11-08,Hafta Sonu Brunch,18,Messaging conversations started,6100,"
    "9200,44.44,800.00,120,6.67,1.30\n"
    "2026-11-02,2026-11-08,Yeni Takipçi,95,Follows,12000,21000,5.26,500.00,310,1.61,1.48\n"
)
WEEK_2 = (
    "Raporlama başlangıcı;Raporlama bitişi;Kampanya adı;Sonuçlar;Sonuç göstergesi;Erişim;"
    "Gösterim;Sonuç başına maliyet (TRY);Harcanan tutar (TRY);Bağlantı tıklamaları;"
    "TBM (bağlantı tıklaması başına maliyet) (TRY);TO (bağlantı tıklama oranı)\n"
    ";;;;;;;;2.850,00;;;\n"
    "2026-11-09;2026-11-15;Kış Menüsü Tanıtım;61;Mesajlaşma sohbeti başlatıldı;12.400;"
    "19.800;24,59;1.500,00;342;4,39;1,73\n"
    "2026-11-09;2026-11-15;Hafta Sonu Brunch;9;Mesajlaşma sohbeti başlatıldı;5.200;8.100;"
    "83,33;750,00;72;10,42;0,89\n"
    "2026-11-09;2026-11-15;Yeni Takipçi;88;Takip;11.000;19.500;6,82;600,00;268;2,24;1,37\n"
)


def test_an_english_export() -> None:
    parsed = parse_meta_csv(("﻿" + WEEK_1).encode("utf-8"))

    assert (parsed.level, parsed.currency) == ("campaign", "TRY")
    assert (parsed.period_start, parsed.period_end) == (dt.date(2026, 11, 2), dt.date(2026, 11, 8))
    first = parsed.rows[0]
    assert first.name == "Kış Menüsü Tanıtım"
    assert (first.spend, first.impressions, first.reach, first.clicks) == (
        Decimal("1200.00"),
        15400,
        9800,
        231,
    )
    assert (first.ctr, first.cpc, first.results, first.cost_per_result) == (
        Decimal("1.50"),
        Decimal("5.19"),
        42,
        Decimal("28.57"),
    )
    assert first.result_type == "Messaging conversations started"


def test_a_turkish_excel_export_skips_the_total_row() -> None:
    parsed = parse_meta_csv(WEEK_2.encode("utf-8"))

    assert [r.name for r in parsed.rows] == [
        "Kış Menüsü Tanıtım",
        "Hafta Sonu Brunch",
        "Yeni Takipçi",
    ]
    first = parsed.rows[0]
    assert (first.spend, first.impressions, first.reach) == (Decimal("1500.00"), 19800, 12400)
    assert (first.ctr, first.cpc, first.cost_per_result) == (
        Decimal("1.73"),
        Decimal("4.39"),
        Decimal("24.59"),
    )
    assert parsed.period_end == dt.date(2026, 11, 15)


def test_a_windows_turkish_encoding_is_read_too() -> None:
    parsed = parse_meta_csv(WEEK_2.encode("cp1254"))

    assert parsed.rows[2].name == "Yeni Takipçi"


def test_missing_ratios_are_computed() -> None:
    raw = (
        "Ad name;Ad set name;Amount spent (USD);Impressions;Clicks (all);Results\n"
        "A;S;10,00;2000;40;4\n"
    )

    (row,) = parse_meta_csv(raw.encode()).rows

    assert (row.level, row.campaign) == ("ad", None)
    assert (row.ctr, row.cpc, row.cost_per_result) == (Decimal(2), Decimal("0.25"), Decimal("2.5"))


def test_ad_set_rows_keep_their_campaign() -> None:
    raw = "Campaign name,Ad set name,Amount spent (EUR)\nK1,Set A,5\n"

    parsed = parse_meta_csv(raw.encode())

    assert (parsed.level, parsed.currency) == ("adset", "EUR")
    assert (parsed.rows[0].name, parsed.rows[0].campaign) == ("Set A", "K1")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"", "boş"),
        (b"Name,Age,City,Country\nA,1,B,C\n", "Harcama sütunu yok"),
        (b"Amount spent (TRY),Impressions,Reach,Clicks\n1,2,3,4\n", "adı sütunu yok"),
        (b"Campaign name,Amount spent (TRY)\n,5\n", "kampanya satırı yok"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00", "Metin dosyası değil"),
    ],
)
def test_files_that_are_not_ad_exports_say_why(raw: bytes, message: str) -> None:
    with pytest.raises(AdsParseError, match=message):
        parse_meta_csv(raw)


def test_csv_uploads_are_recognised() -> None:
    assert looks_like_csv("rapor.CSV", b"x")
    assert looks_like_csv(None, WEEK_2.encode())
    assert not looks_like_csv("foto.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF")
    assert not looks_like_csv(None, b"merhaba")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("9 Kas 2026 - 15 Kas 2026", (dt.date(2026, 11, 9), dt.date(2026, 11, 15))),
        (f"9 Kasım {chr(0x2013)} 15 Kasım 2026", (dt.date(2026, 11, 9), dt.date(2026, 11, 15))),
        ("28 Ara - 3 Oca 2027", (dt.date(2026, 12, 28), dt.date(2027, 1, 3))),
        ("Nov 9, 2026 - Nov 15, 2026", (dt.date(2026, 11, 9), dt.date(2026, 11, 15))),
        ("09.11.2026 - 15.11.2026", (dt.date(2026, 11, 9), dt.date(2026, 11, 15))),
        ("Son 7 gün", None),
        ("9 Kas - 15 Kas", None),  # no year anywhere: not guessed
        ("15 Kas 2026 - 9 Kas 2026", None),
        (None, None),
    ],
)
def test_written_periods_are_parsed_in_code(
    text: str | None, expected: tuple[dt.date, dt.date] | None
) -> None:
    assert parse_period(text) == expected


def test_comparison_with_the_previous_period() -> None:
    before = parse_meta_csv(WEEK_1.encode()).rows
    now = parse_meta_csv(WEEK_2.encode()).rows

    table = comparison_table(now, before, "TRY")

    lines = table.splitlines()
    assert lines[2].startswith("| Kış Menüsü Tanıtım | 1.500,00 TRY (+%25,0) | 19.800 (+%28,6)")
    assert "61 Mesajlaşma sohbeti başlatıldı (+%45,2)" in lines[2]
    assert "| 24,59 (-%13,9) |" in lines[2]
    assert lines[5].startswith("| **Toplam** | 2.850,00 TRY (+%14,0)")
    assert totals(now).results == 158


def test_without_a_previous_period_there_are_no_changes() -> None:
    table = comparison_table(parse_meta_csv(WEEK_1.encode()).rows, None, None)

    assert "(+" not in table
    assert "(-" not in table


def test_number_and_period_formatting() -> None:
    assert tr_number(Decimal("1234.5")) == "1.234,50"
    assert tr_number(None) == "-"
    assert change(Decimal(0), Decimal(0)) == ""
    assert change(5, 0) == "yeni"
    assert period_text(dt.date(2026, 11, 9), dt.date(2026, 11, 15)) == "9-15 Kas 2026"
    assert period_text(dt.date(2026, 11, 30), dt.date(2026, 12, 6)) == "30 Kas - 6 Ara 2026"
    assert period_text(None, None) == "dönem bilinmiyor"


def test_the_examples_parse() -> None:
    if not EXAMPLES.is_dir():
        pytest.skip("examples/ not mounted")
    first, second = sorted(EXAMPLES.glob("*.csv"))

    assert parse_meta_csv(first.read_bytes()).rows == parse_meta_csv(WEEK_1.encode()).rows
    assert parse_meta_csv(second.read_bytes()).rows == parse_meta_csv(WEEK_2.encode()).rows


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            ["1. Bütçeyi kaydır. 2) Görseli yenile. 3. Sürdür."],
            ["Bütçeyi kaydır.", "Görseli yenile.", "Sürdür."],
        ),
        (
            ["- Bütçeyi kaydır\n- Görseli yenile\n- Sürdür"],
            ["Bütçeyi kaydır", "Görseli yenile", "Sürdür"],
        ),
        (["Tek bir öneri."], ["Tek bir öneri."]),  # left for the schema to reject
        (["a", "b", "c"], ["a", "b", "c"]),
        ("metin", "metin"),
    ],
)
def test_three_recommendations_in_one_string_are_split(value: object, expected: object) -> None:
    assert split_recommendations(value) == expected
