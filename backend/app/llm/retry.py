"""How long a provider asks us to wait after a 429 (headers first, then the message)."""

import re
from collections.abc import Mapping

_IN_MESSAGE = re.compile(r"try again in\s+([\d.]+)\s*(ms|s)\b", re.IGNORECASE)


def parse_retry_after(headers: Mapping[str, str] | None, message: str = "") -> float | None:
    """Seconds to wait, or None if the provider didn't say."""
    if headers:
        lowered = {key.lower(): value for key, value in headers.items()}
        for key, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
            value = lowered.get(key)
            if value is None:
                continue
            try:
                return max(float(value) * scale, 0.0)
            except ValueError:
                pass  # an HTTP date: fall back to the message
    match = _IN_MESSAGE.search(message or "")
    if match:
        amount = float(match.group(1))
        return amount / 1000 if match.group(2).lower() == "ms" else amount
    return None
