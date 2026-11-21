"""Secrets that travel in a URL never reach the logs (QA O3): the calendar subscription
token (GET /api/calendar.ics?token=..., the phone's calendar can't send a header) is
masked in uvicorn's access log. nginx has its own config (web/nginx.conf)."""

import logging
import re

_SECRET_PARAMS = re.compile(r"((?:^|[?&])(?:token|key|password)=)[^&\s]+", re.IGNORECASE)
MASK = "***"


def mask_url(text: str) -> str:
    return _SECRET_PARAMS.sub(rf"\g<1>{MASK}", text)


class SecretQueryFilter(logging.Filter):
    """uvicorn.access records: args = (client, method, full path, http version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(mask_url(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = mask_url(record.msg)
        return True


def install() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, SecretQueryFilter) for f in access.filters):
        access.addFilter(SecretQueryFilter())
