import pytest

from app.llm.retry import parse_retry_after
from app.llm.types import ProviderError
from tests.llm.fakes import FakeProvider, make_router, request


@pytest.mark.parametrize(
    ("headers", "message", "expected"),
    [
        ({"retry-after-ms": "750"}, "", 0.75),
        ({"Retry-After": "2"}, "", 2.0),
        ({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, "Please try again in 1.5s.", 1.5),
        (None, "Rate limit reached ... Please try again in 7.5ms. Need more tokens?", 0.0075),
        (None, "Please try again in 1.929999999s.", 1.929999999),
        ({}, "slow down", None),
        (None, "", None),
    ],
)
def test_parse_retry_after(
    headers: dict[str, str] | None, message: str, expected: float | None
) -> None:
    result = parse_retry_after(headers, message)

    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def rate_limited(seconds: float | None) -> ProviderError:
    return ProviderError(
        "groq", "rate limited", retryable=True, status_code=429, retry_after=seconds
    )


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


async def test_short_wait_retries_the_same_tier() -> None:
    sleeps = Sleeps()
    router, store = make_router({"groq": FakeProvider("groq", [rate_limited(1.5)])})
    router._sleep = sleeps

    response = await router.complete(request())

    assert response.tier == "fast"
    assert sleeps.calls == [1.5]
    assert [r.error is not None for r in store.records] == [True, False]


async def test_long_wait_fails_over_immediately() -> None:
    sleeps = Sleeps()
    router, _ = make_router({"groq": FakeProvider("groq", [rate_limited(7.0)])})
    router._sleep = sleeps

    response = await router.complete(request())

    assert response.tier == "fallback"
    assert sleeps.calls == []


async def test_unknown_wait_fails_over() -> None:
    router, _ = make_router({"groq": FakeProvider("groq", [rate_limited(None)])})
    router._sleep = Sleeps()

    assert (await router.complete(request())).tier == "fallback"


async def test_waits_are_limited_then_fail_over() -> None:
    sleeps = Sleeps()
    groq = FakeProvider("groq", [rate_limited(1.0), rate_limited(2.0), rate_limited(0.5)])
    router, _ = make_router({"groq": groq})
    router._sleep = sleeps

    response = await router.complete(request())

    assert sleeps.calls == [1.0, 2.0]  # rate_limit_max_waits = 2
    assert response.tier == "fallback"
    assert len(groq.calls) == 3


async def test_per_provider_wait_limit_and_wait_notification() -> None:
    sleeps = Sleeps()
    waits: list[tuple[float, str]] = []

    async def on_wait(seconds: float, provider: str) -> None:
        waits.append((seconds, provider))

    router, _ = make_router({"groq": FakeProvider("groq", [rate_limited(7.0)])})
    router._sleep = sleeps
    router.wait_limits = {"groq": 8.0}  # GROQ_MAX_RETRY_WAIT_SEC=8

    response = await router.complete(request(), on_wait=on_wait)

    assert response.tier == "fast"  # 7s <= 8s: waited instead of failing over
    assert sleeps.calls == [7.0]
    assert waits == [(7.0, "groq")]


async def test_wait_longer_than_the_provider_limit_fails_over() -> None:
    router, _ = make_router({"groq": FakeProvider("groq", [rate_limited(9.5)])})
    router._sleep = Sleeps()
    router.wait_limits = {"groq": 8.0}

    assert (await router.complete(request())).tier == "fallback"


def test_wait_limits_come_from_env_first() -> None:
    from app.config import Settings
    from app.llm.router import wait_limits
    from tests.llm.fakes import make_config

    config = make_config(
        providers={
            "groq": {
                "type": "openai_compat",
                "base_url": "http://g",
                "api_key_env": "X",
                "rate_limit_max_wait_env": "GROQ_MAX_RETRY_WAIT_SEC",
                "rate_limit_max_wait_seconds": 5,
            },
            "claude": {"type": "anthropic", "api_key_env": "Y", "rate_limit_max_wait_seconds": 2},
            "ollama": {"type": "openai_compat", "base_url": "http://o"},
        }
    )

    with_env = wait_limits(config, Settings(_env_file=None, groq_max_retry_wait_sec=8))
    without_env = wait_limits(config, Settings(_env_file=None))

    assert with_env == {"groq": 8.0, "claude": 2.0}
    assert without_env == {"groq": 5.0, "claude": 2.0}
