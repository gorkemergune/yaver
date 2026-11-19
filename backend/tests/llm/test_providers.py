"""Provider request building and response parsing with the real SDK types (no network)."""

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import anthropic
import httpx2
import openai
import pytest
from anthropic.types import Message
from openai.types.chat import ChatCompletion

from app.llm.providers.anthropic import (
    AnthropicProvider,
    build_request_kwargs,
    parse_message,
    to_anthropic_messages,
)
from app.llm.providers.openai_compat import OpenAICompatProvider, to_openai_messages
from app.llm.types import (
    ChatMessage,
    LLMRequest,
    ProviderError,
    ProviderNotConfiguredError,
    ToolCall,
)
from tests.llm.fakes import GET_DAY_PLAN

# --- helpers ---------------------------------------------------------------------------


def _response(status: int, url: str) -> httpx2.Response:
    return httpx2.Response(status, request=httpx2.Request("POST", url))


class _Recorder:
    """Stands in for `client.messages` / `client.chat.completions` / `client.models`."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.kwargs: dict[str, Any] = {}
        self.result = result
        self.error = error

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result

    async def retrieve(self, model: str) -> Any:
        if self.error:
            raise self.error
        return {"id": model}

    def list(self) -> AsyncIterator[Any]:
        async def items() -> AsyncIterator[Any]:
            for model_id in self.result:
                yield type("Model", (), {"id": model_id})()

        return items()


class _FakeAnthropicClient:
    def __init__(self, messages: _Recorder, models: _Recorder | None = None) -> None:
        self.messages = messages
        self.models = models or _Recorder()


class _FakeOpenAIClient:
    def __init__(self, completions: _Recorder, models: _Recorder | None = None) -> None:
        self.chat = type("Chat", (), {"completions": completions})()
        self.models = models or _Recorder()


CONVERSATION = [
    ChatMessage("user", "Yarın ne var?"),
    ChatMessage(
        "assistant",
        "Bakıyorum.",
        tool_calls=[
            ToolCall("t1", "get_day_plan", {"date": "2026-11-20"}),
            ToolCall("t2", "get_day_plan", {"date": "2026-11-21"}),
        ],
    ),
    ChatMessage("tool", '{"items": []}', tool_call_id="t1"),
    ChatMessage("tool", "hata", tool_call_id="t2", is_error=True),
    ChatMessage("assistant", "Yarın boşsun."),
    ChatMessage("user", "Teşekkürler"),
]


def _request(**kwargs: Any) -> LLMRequest:
    return LLMRequest(
        messages=list(CONVERSATION), system="Sen Yaver'sin.", tools=[GET_DAY_PLAN], **kwargs
    )


# --- Anthropic: request ----------------------------------------------------------------


def test_anthropic_caches_tools_plus_system_and_the_conversation_tail() -> None:
    kwargs = build_request_kwargs(_request(), "claude-haiku-5-5", {})

    assert kwargs["system"] == [
        {"type": "text", "text": "Sen Yaver'sin.", "cache_control": {"type": "ephemeral"}}
    ]
    assert kwargs["cache_control"] == {"type": "ephemeral"}
    assert kwargs["tools"] == [
        {
            "name": "get_day_plan",
            "description": "Plan for one day",
            "input_schema": GET_DAY_PLAN.parameters,
        }
    ]


def test_anthropic_dynamic_system_part_goes_after_the_cache_breakpoint() -> None:
    kwargs = build_request_kwargs(_request(system_suffix="Bugün: 2026-11-23"), "m", {})

    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"][1] == {"type": "text", "text": "Bugün: 2026-11-23"}


def test_openai_system_suffix_is_appended() -> None:
    messages = to_openai_messages(_request(system_suffix="Bugün: 2026-11-23"))

    assert messages[0] == {"role": "system", "content": "Sen Yaver'sin.\n\nBugün: 2026-11-23"}


def test_anthropic_without_cache() -> None:
    kwargs = build_request_kwargs(_request(cache=False), "m", {})

    assert "cache_control" not in kwargs
    assert "cache_control" not in kwargs["system"][0]


def test_anthropic_never_sends_sampling_parameters() -> None:
    kwargs = build_request_kwargs(_request(), "m", {"thinking": {"type": "disabled"}})

    assert not {"temperature", "top_p", "top_k"} & kwargs.keys()
    assert kwargs["thinking"] == {"type": "disabled"}


def test_anthropic_effort_goes_into_output_config() -> None:
    kwargs = build_request_kwargs(_request(), "m", {"effort": "medium"})

    assert kwargs["output_config"] == {"effort": "medium"}
    assert "effort" not in kwargs


@pytest.mark.parametrize(
    ("choice", "options", "expected"),
    [
        ("auto", {}, {"type": "auto"}),
        ("none", {}, {"type": "none"}),
        ("required", {}, {"type": "auto"}),  # 5.5 models reject forced tool use
        ("required", {"forced_tool_choice": True}, {"type": "any"}),
    ],
)
def test_anthropic_tool_choice(
    choice: str, options: dict[str, Any], expected: dict[str, Any]
) -> None:
    kwargs = build_request_kwargs(_request(tool_choice=choice), "m", options)

    assert kwargs["tool_choice"] == expected
    assert "forced_tool_choice" not in kwargs


def test_anthropic_tool_results_of_one_turn_go_back_in_one_user_message() -> None:
    messages = to_anthropic_messages(CONVERSATION)

    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant", "user"]
    assistant = messages[1]["content"]
    assert assistant[0] == {"type": "text", "text": "Bakıyorum."}
    assert [b["id"] for b in assistant[1:]] == ["t1", "t2"]
    results = messages[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert "is_error" not in results[0]
    assert results[1]["is_error"] is True


def test_anthropic_replays_its_own_blocks_verbatim() -> None:
    raw = [
        {"type": "thinking", "thinking": "", "signature": "sig=="},
        {"type": "tool_use", "id": "t1", "name": "get_day_plan", "input": {"date": "x"}},
    ]
    message = ChatMessage(
        "assistant",
        tool_calls=[ToolCall("t1", "get_day_plan", {"date": "x"})],
        provider_state={"provider": "anthropic", "content": raw},
    )

    assert to_anthropic_messages([message])[0]["content"] == raw


def test_anthropic_ignores_state_from_other_providers() -> None:
    message = ChatMessage("assistant", "merhaba", provider_state={"provider": "groq", "x": 1})

    assert to_anthropic_messages([message])[0]["content"] == "merhaba"


# --- Anthropic: response ---------------------------------------------------------------

MESSAGE = Message.model_validate(
    {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "abc"},
            {"type": "text", "text": "Bakıyorum."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "get_day_plan",
                "input": {"date": "2026-11-20"},
            },
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 12,
            "output_tokens": 30,
            "cache_read_input_tokens": 2048,
            "cache_creation_input_tokens": 0,
        },
    }
)


def test_anthropic_parses_text_tool_calls_usage_and_state() -> None:
    response = parse_message(MESSAGE, "anthropic", "claude-haiku-5-5")

    assert response.text == "Bakıyorum."
    assert response.stop_reason == "tool_use"
    assert response.tool_calls == [ToolCall("toolu_1", "get_day_plan", {"date": "2026-11-20"})]
    assert (response.usage.input_tokens, response.usage.cached_input_tokens) == (12, 2048)
    assert response.usage.output_tokens == 30
    state = response.provider_state or {}
    assert state["content"][0] == {"type": "thinking", "thinking": "", "signature": "abc"}
    # The replayed state round-trips into the next request unchanged.
    assert to_anthropic_messages([response.to_message()])[0]["content"] == state["content"]


async def test_anthropic_complete_uses_the_client() -> None:
    messages = _Recorder(MESSAGE)
    provider = AnthropicProvider(api_key=None, client=_FakeAnthropicClient(messages))

    response = await provider.complete(_request(), "claude-haiku-5-5", {})

    assert messages.kwargs["model"] == "claude-haiku-5-5"
    assert response.provider == "anthropic"


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (
            anthropic.RateLimitError("slow down", response=_response(429, "https://a"), body=None),
            True,
        ),
        (
            anthropic.InternalServerError("boom", response=_response(529, "https://a"), body=None),
            True,
        ),
        (anthropic.BadRequestError("bad", response=_response(400, "https://a"), body=None), False),
        (
            anthropic.AuthenticationError("key", response=_response(401, "https://a"), body=None),
            False,
        ),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://a")), True),
    ],
)
async def test_anthropic_error_mapping(error: Exception, retryable: bool) -> None:
    provider = AnthropicProvider(api_key=None, client=_FakeAnthropicClient(_Recorder(error=error)))

    with pytest.raises(ProviderError) as info:
        await provider.complete(_request(), "m", {})

    assert info.value.retryable is retryable


async def test_anthropic_without_key_is_not_configured() -> None:
    provider = AnthropicProvider(api_key=None)

    assert not provider.configured
    with pytest.raises(ProviderNotConfiguredError):
        await provider.complete(_request(), "m", {})


async def test_anthropic_has_model() -> None:
    found = AnthropicProvider(api_key=None, client=_FakeAnthropicClient(_Recorder()))
    not_found = AnthropicProvider(
        api_key=None,
        client=_FakeAnthropicClient(
            _Recorder(),
            _Recorder(
                error=anthropic.NotFoundError("no", response=_response(404, "https://a"), body=None)
            ),
        ),
    )

    assert await found.has_model("claude-haiku-5-5")
    assert not await not_found.has_model("claude-haiku-9")


# --- OpenAI-compatible -----------------------------------------------------------------


def test_openai_messages() -> None:
    messages = to_openai_messages(_request())

    assert messages[0] == {"role": "system", "content": "Sen Yaver'sin."}
    assistant = messages[2]
    assert assistant["tool_calls"][0] == {
        "id": "t1",
        "type": "function",
        "function": {"name": "get_day_plan", "arguments": '{"date": "2026-11-20"}'},
    }
    assert messages[3] == {"role": "tool", "tool_call_id": "t1", "content": '{"items": []}'}
    assert messages[-1] == {"role": "user", "content": "Teşekkürler"}


def _completion(tool_arguments: str, *, cost: float | None = None) -> ChatCompletion:
    usage: dict[str, Any] = {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "total_tokens": 1050,
        "prompt_tokens_details": {"cached_tokens": 800},
    }
    if cost is not None:
        usage["cost"] = cost
    return ChatCompletion.model_validate(
        {
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "openai/gpt-oss-120b",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "get_day_plan", "arguments": tool_arguments},
                            }
                        ],
                    },
                }
            ],
            "usage": usage,
        }
    )


def _openai(completions: _Recorder, **kwargs: Any) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        "groq", base_url="http://x", api_key="k", client=_FakeOpenAIClient(completions), **kwargs
    )


async def test_openai_complete_request_and_parsing() -> None:
    completions = _Recorder(_completion('{"date": "2026-11-20"}'))

    response = await _openai(completions).complete(
        _request(tool_choice="required"), "openai/gpt-oss-120b", {"reasoning_effort": "low"}
    )

    sent = completions.kwargs
    assert sent["tool_choice"] == "required"
    assert sent["tools"][0]["function"]["name"] == "get_day_plan"
    assert sent["extra_body"] == {"reasoning_effort": "low"}
    assert response.stop_reason == "tool_use"
    assert response.tool_calls[0].arguments == {"date": "2026-11-20"}
    assert (response.usage.input_tokens, response.usage.cached_input_tokens) == (200, 800)
    assert response.usage.reported_cost_usd is None  # groq doesn't report cost


async def test_openai_invalid_tool_json_is_kept_for_validation() -> None:
    response = await _openai(_Recorder(_completion('{"date": '))).complete(_request(), "m", {})

    call = response.tool_calls[0]
    assert call.arguments is None
    assert call.raw_arguments == '{"date": '
    assert "invalid JSON" in (call.parse_error or "")


async def test_openrouter_reported_cost() -> None:
    provider = _openai(_Recorder(_completion("{}", cost=0.00042)), reports_cost=True)

    response = await provider.complete(_request(), "m", {})

    assert response.usage.reported_cost_usd == Decimal("0.00042")


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (openai.RateLimitError("slow", response=_response(429, "http://x"), body=None), True),
        (openai.InternalServerError("boom", response=_response(503, "http://x"), body=None), True),
        (openai.BadRequestError("bad", response=_response(400, "http://x"), body=None), False),
        (openai.APITimeoutError(request=httpx2.Request("POST", "http://x")), True),
    ],
)
async def test_openai_error_mapping(error: Exception, retryable: bool) -> None:
    with pytest.raises(ProviderError) as info:
        await _openai(_Recorder(error=error)).complete(_request(), "m", {})

    assert info.value.retryable is retryable


@pytest.mark.parametrize(
    ("message", "body", "expected"),
    [
        ("Tool call validation failed: parameters did not match schema", None, True),
        ("Failed to call a function. Please adjust your prompt.", None, True),
        ("bad", {"error": {"code": "tool_use_failed", "message": "bad"}}, True),
        ("model not found", {"error": {"code": "model_not_found"}}, False),
    ],
)
async def test_groq_tool_call_rejections_are_flagged(
    message: str, body: dict[str, Any] | None, expected: bool
) -> None:
    error = openai.BadRequestError(message, response=_response(400, "http://x"), body=body)

    with pytest.raises(ProviderError) as info:
        await _openai(_Recorder(error=error)).complete(_request(), "m", {})

    assert info.value.invalid_tool_call is expected
    assert info.value.retryable is False


async def test_openai_has_model_uses_the_model_list() -> None:
    provider = OpenAICompatProvider(
        "groq",
        base_url="http://x",
        api_key="k",
        client=_FakeOpenAIClient(_Recorder(), _Recorder(["openai/gpt-oss-120b", "llama"])),
    )

    assert await provider.has_model("openai/gpt-oss-120b")
    assert not await provider.has_model("openai/gpt-oss-999b")


def test_openai_configuration() -> None:
    assert not OpenAICompatProvider("groq", base_url="http://x", api_key=None).configured
    assert OpenAICompatProvider(
        "ollama", base_url="http://x", api_key=None, api_key_required=False
    ).configured
    assert not OpenAICompatProvider(
        "ollama", base_url=None, api_key=None, api_key_required=False
    ).configured


def test_tool_call_arguments_json_is_stable() -> None:
    call = ToolCall("1", "t", {"b": 1, "a": "ç"})

    assert call.arguments_json() == json.dumps({"a": "ç", "b": 1}, ensure_ascii=False)
