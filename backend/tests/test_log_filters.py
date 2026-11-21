"""QA O3: the calendar token (in the URL) never reaches the api's access log."""

import logging

from app.core.log_filters import SecretQueryFilter, mask_url


def test_secret_query_values_are_masked() -> None:
    assert mask_url("/api/calendar.ics?token=QA-SECRET") == "/api/calendar.ics?token=***"
    assert mask_url("/x?a=1&key=abc&b=2") == "/x?a=1&key=***&b=2"
    assert mask_url("/api/plan/day?date=2026-11-23") == "/api/plan/day?date=2026-11-23"


def test_the_uvicorn_access_record_is_masked() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("172.18.0.4:5000", "GET", "/api/calendar.ics?token=QA-SECRET-TOKEN-PROBE", "1.1", 200),
        None,
    )

    SecretQueryFilter().filter(record)

    assert "QA-SECRET" not in record.getMessage()
    assert "token=***" in record.getMessage()


def test_the_app_installs_it() -> None:
    from app.main import create_app

    create_app()

    assert any(
        isinstance(f, SecretQueryFilter) for f in logging.getLogger("uvicorn.access").filters
    )
