"""Claude via the official Anthropic SDK, with prompt caching.

Caching: tools render before system, so one breakpoint on the (stable) system prompt caches
tools + system; top-level automatic caching covers the growing conversation tail. Keep the
system prompt free of per-request values (dates go into messages) or nothing is reused.
"""

from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from app.llm.retry import parse_retry_after
from app.llm.types import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    ProviderError,
    ProviderNotConfiguredError,
    StopReason,
    TextCallback,
    TokenUsage,
    ToolCall,
)

PROVIDER_STATE_KEY = "anthropic"
EPHEMERAL = {"type": "ephemeral"}

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end",
    "stop_sequence": "end",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}

# Router-level options that are not Messages API parameters.
_LOCAL_OPTIONS = {"forced_tool_choice", "effort"}


class AnthropicProvider:
    def __init__(
        self,
        name: str = "anthropic",
        *,
        api_key: str | None,
        timeout_seconds: float = 60.0,
        max_retries: int = 1,
        client: Any = None,
    ) -> None:
        self.name = name
        self.reports_cost = False
        self._api_key = api_key
        self._client = client
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    @property
    def configured(self) -> bool:
        return self._client is not None or bool(self._api_key)

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ProviderNotConfiguredError(self.name, "ANTHROPIC_API_KEY not set")
            self._client = AsyncAnthropic(
                api_key=self._api_key, timeout=self._timeout, max_retries=self._max_retries
            )
        return self._client

    async def complete(
        self,
        request: LLMRequest,
        model: str,
        options: dict[str, Any],
        on_text: TextCallback | None = None,
    ) -> LLMResponse:
        kwargs = build_request_kwargs(request, model, options)
        try:
            if on_text is not None:
                async with self._get_client().messages.stream(**kwargs) as stream:
                    async for event in stream:
                        if event.type == "text" and event.text:
                            await on_text(event.text)
                    message = await stream.get_final_message()
            else:
                message = await self._get_client().messages.create(**kwargs)
        except ProviderError:
            raise
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                self.name,
                exc.message,
                retryable=exc.status_code == 429 or exc.status_code >= 500,
                status_code=exc.status_code,
                retry_after=_retry_after(exc),
            ) from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise ProviderError(self.name, str(exc), retryable=True) from exc
        return parse_message(message, self.name, model)

    async def list_models(self) -> list[str]:
        client = self._get_client()
        try:
            return [item.id async for item in client.models.list()]
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                self.name, exc.message, retryable=False, status_code=exc.status_code
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

    async def aclose(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
        self._client = None

    async def has_model(self, model: str) -> bool:
        # retrieve() also accepts alias ids that list() may not show verbatim.
        try:
            await self._get_client().models.retrieve(model)
        except anthropic.NotFoundError:
            return False
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                self.name, exc.message, retryable=False, status_code=exc.status_code
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc
        return True


def _retry_after(exc: Any) -> float | None:
    if exc.status_code != 429:
        return None
    headers = getattr(getattr(exc, "response", None), "headers", None)
    return parse_retry_after(dict(headers) if headers is not None else None, exc.message)


def build_request_kwargs(
    request: LLMRequest, model: str, options: dict[str, Any]
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": request.max_tokens,
        "messages": to_anthropic_messages(request.messages),
    }
    system: list[dict[str, Any]] = []
    if request.system:
        system_block: dict[str, Any] = {"type": "text", "text": request.system}
        if request.cache:
            system_block["cache_control"] = EPHEMERAL  # caches tools + stable system
        system.append(system_block)
    if request.system_suffix:  # after the breakpoint: a new day doesn't invalidate the prefix
        system.append({"type": "text", "text": request.system_suffix})
    if system:
        kwargs["system"] = system
    if request.cache:
        kwargs["cache_control"] = EPHEMERAL  # automatic breakpoint on the conversation tail
    if request.tools:
        kwargs["tools"] = [
            {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
            for tool in request.tools
        ]
        kwargs["tool_choice"] = _tool_choice(request.tool_choice, options)
    if "effort" in options:
        kwargs["output_config"] = {"effort": options["effort"]}
    for key, value in options.items():
        if key not in _LOCAL_OPTIONS:
            kwargs[key] = value  # e.g. thinking
    return kwargs


def _tool_choice(choice: str, options: dict[str, Any]) -> dict[str, Any]:
    if choice == "none":
        return {"type": "none"}
    if choice == "required" and options.get("forced_tool_choice"):
        return {"type": "any"}
    # Claude Opus/Sonnet 5.5 reject forced tool choice; "required" is enforced by the
    # prompt and by the router's tool-call validation instead.
    return {"type": "auto"}


def to_anthropic_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content,
            }
            if message.is_error:
                block["is_error"] = True
            previous = converted[-1] if converted else None
            # All results of one assistant turn go back in a single user message.
            if previous and previous["role"] == "user" and _is_tool_results(previous):
                previous["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
        elif message.role == "assistant":
            converted.append({"role": "assistant", "content": _assistant_content(message)})
        else:  # user, or a mid-conversation system message
            converted.append({"role": message.role, "content": message.content})
    return converted


def _is_tool_results(message: dict[str, Any]) -> bool:
    content = message["content"]
    return isinstance(content, list) and all(b.get("type") == "tool_result" for b in content)


def _assistant_content(message: ChatMessage) -> list[dict[str, Any]] | str:
    state = message.provider_state or {}
    if state.get("provider") == PROVIDER_STATE_KEY and state.get("content"):
        # Replay the exact blocks (incl. thinking + signatures) Claude produced.
        content: list[dict[str, Any]] = state["content"]
        return content
    if not message.tool_calls:
        return message.content
    blocks: list[dict[str, Any]] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    blocks.extend(
        {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments or {}}
        for call in message.tool_calls
    )
    return blocks


def parse_message(message: Any, provider: str, model: str) -> LLMResponse:
    texts: list[str] = []
    calls: list[ToolCall] = []
    for block in message.content:
        if block.type == "text":
            texts.append(block.text)
        elif block.type == "tool_use":
            arguments = block.input if isinstance(block.input, dict) else None
            calls.append(
                ToolCall(
                    block.id,
                    block.name,
                    arguments,
                    parse_error=None if arguments is not None else "input is not an object",
                )
            )
    usage = message.usage
    return LLMResponse(
        text="".join(texts),
        tool_calls=calls,
        stop_reason=_STOP_REASONS.get(message.stop_reason or "", "other"),
        usage=TokenUsage(
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cached_input_tokens=usage.cache_read_input_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
        ),
        provider=provider,
        model=message.model or model,
        provider_state={
            "provider": PROVIDER_STATE_KEY,
            "content": [
                block.model_dump(mode="json", exclude_none=True) for block in message.content
            ],
        },
    )
