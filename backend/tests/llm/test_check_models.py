from app.llm.check_models import CheckStatus, check_models, format_report
from app.llm.types import ProviderError
from tests.llm.fakes import FakeProvider, make_config


def _providers(**overrides: FakeProvider) -> dict[str, FakeProvider]:
    providers = {
        "groq": FakeProvider("groq", models=["fast-model", "other"]),
        "claude": FakeProvider("claude", models=["haiku", "sonnet"]),
        "ollama": FakeProvider("ollama", models=["local-model"]),
    }
    providers.update(overrides)
    return providers


async def test_all_models_present() -> None:
    results = await check_models(make_config(), _providers())

    assert [(r.target, r.status) for r in results] == [
        ("fast", CheckStatus.OK),
        ("fallback", CheckStatus.OK),
        ("smart", CheckStatus.OK),
        ("local", CheckStatus.OK),
    ]
    assert not any(r.failed for r in results)


async def test_missing_model_fails_with_a_clear_message() -> None:
    results = await check_models(make_config(), _providers(groq=FakeProvider("groq", models=["x"])))

    fast = results[0]
    assert fast.status is CheckStatus.MISSING
    assert fast.failed
    assert "'fast-model' not found at groq" in fast.detail
    assert "config/providers.yaml" in fast.detail
    assert "MISSING  fast" in format_report(results)


async def test_provider_without_key_is_skipped_not_failed() -> None:
    results = await check_models(
        make_config(), _providers(claude=FakeProvider("claude", configured=False))
    )

    claude = [r for r in results if r.provider == "claude"]
    assert {r.status for r in claude} == {CheckStatus.SKIPPED}
    assert not any(r.failed for r in results)
    assert "Y not set" in claude[0].detail


async def test_unreachable_optional_provider_only_warns() -> None:
    ollama = FakeProvider("ollama")
    ollama.list_error = ProviderError("ollama", "connection refused", retryable=True)

    results = await check_models(make_config(), _providers(ollama=ollama))

    local = results[-1]
    assert local.status is CheckStatus.ERROR
    assert local.optional
    assert not local.failed


async def test_missing_model_at_optional_provider_only_warns() -> None:
    results = await check_models(
        make_config(), _providers(ollama=FakeProvider("ollama", models=["llama3"]))
    )

    local = results[-1]
    assert local.status is CheckStatus.MISSING
    assert not local.failed
    assert "[optional]" in format_report(results)


async def test_unreachable_required_provider_fails() -> None:
    groq = FakeProvider("groq")
    groq.list_error = ProviderError("groq", "401 invalid key", retryable=False)

    results = await check_models(make_config(), _providers(groq=groq))

    assert results[0].status is CheckStatus.ERROR
    assert results[0].failed


async def test_default_model_of_an_unused_provider_is_checked() -> None:
    config = make_config(
        providers={
            "groq": {"type": "openai_compat", "base_url": "http://groq", "api_key_env": "X"},
            "claude": {"type": "anthropic", "api_key_env": "Y"},
            "ollama": {"type": "openai_compat", "base_url": "http://ollama", "optional": True},
            "openrouter": {
                "type": "openai_compat",
                "base_url": "http://or",
                "api_key_env": "Z",
                "default_model": "openai/gpt-oss-120b",
            },
        }
    )
    providers = _providers(openrouter=FakeProvider("openrouter", models=["openai/gpt-oss-120b"]))

    results = await check_models(config, providers)

    assert results[-1].target == "openrouter default_model"
    assert results[-1].status is CheckStatus.OK


async def test_per_yaver_models_are_checked_too() -> None:
    results = await check_models(
        make_config(),
        _providers(),
        extra_targets=[("academic model", "groq", "small"), ("dupe", "groq", "fast-model")],
    )

    extra = [r for r in results if r.target == "academic model"]
    assert extra[0].status is CheckStatus.MISSING  # groq only lists fast-model and other
    assert not any(r.target == "dupe" for r in results)  # already covered by the fast tier
