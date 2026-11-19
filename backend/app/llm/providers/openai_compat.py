"""OpenAI-compatible chat completions: Groq, OpenRouter, Ollama."""

import json
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import openai
from openai import AsyncOpenAI

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

_STOP_REASONS: dict[str, StopReason] = {
    "stop": "end",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


class OpenAICompatProvider:
    def __init__(
        self,
        name: str,
        *,
        base_url: str | None,
        api_key: str | None,
        api_key_required: bool = True,
        reports_cost: bool = False,
        timeout_seconds: float = 60.0,
        max_retries: int = 1,
        client: Any = None,
    ) -> None:
        self.name = name
        self.reports_cost = reports_cost
        self.supports_vision = False  # images go to Claude only (privacy + routing decision)
        self._base_url = base_url
        self._api_key = api_key
        self._api_key_required = api_key_required
        self._client = client
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    @property
    def configured(self) -> bool:
        return bool(self._base_url) and (bool(self._api_key) or not self._api_key_required)

    def _get_client(self) -> Any:
        if self._client is None:
            if not self.configured:
                raise ProviderNotConfiguredError(self.name, "API key or base URL not set")
            self._client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=self._api_key or "not-needed",  # Ollama ignores the key
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
        return self._client

    async def complete(
        self,
        request: LLMRequest,
        model: str,
        options: dict[str, Any],
        on_text: TextCallback | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": to_openai_messages(request),
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            kwargs["tool_choice"] = request.tool_choice
        if options:
            kwargs["extra_body"] = dict(options)

        try:
            if on_text is not None:
                return await self._stream(kwargs, model, on_text)
            response = await self._get_client().chat.completions.create(**kwargs)
        except ProviderError:
            raise
        except openai.APIStatusError as exc:
            raise ProviderError(
                self.name,
                exc.message,
                retryable=exc.status_code == 429 or exc.status_code >= 500,
                status_code=exc.status_code,
                retry_after=_retry_after(exc),
                invalid_tool_call=_is_tool_call_rejection(exc),
            ) from exc
        except openai.APIConnectionError as exc:  # includes timeouts
            raise ProviderError(self.name, str(exc), retryable=True) from exc
        return self._parse(response, model)

    def _parse(self, response: Any, model: str) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message
        return LLMResponse(
            text=message.content or "",
            tool_calls=[
                _tool_call(call.id, call.function.name, call.function.arguments)
                for call in message.tool_calls or []
            ],
            stop_reason=_STOP_REASONS.get(choice.finish_reason or "", "other"),
            usage=_token_usage(response.usage, self.reports_cost),
            provider=self.name,
            model=getattr(response, "model", None) or model,
        )

    async def _stream(
        self, kwargs: dict[str, Any], model: str, on_text: TextCallback
    ) -> LLMResponse:
        """Stream text deltas to on_text; tool-call fragments are joined by index."""
        stream = await self._get_client().chat.completions.create(
            **kwargs, stream=True, stream_options={"include_usage": True}
        )
        text: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish, usage, served_by = None, None, model
        async for chunk in stream:
            served_by = getattr(chunk, "model", None) or served_by
            extra = getattr(chunk, "model_extra", None) or {}
            usage = getattr(chunk, "usage", None) or extra.get("x_groq", {}).get("usage") or usage
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta.content:
                text.append(delta.content)
                await on_text(delta.content)
            for fragment in delta.tool_calls or []:
                entry = calls.setdefault(fragment.index, {"id": "", "name": "", "arguments": ""})
                entry["id"] = fragment.id or entry["id"]
                if fragment.function is not None:
                    entry["name"] = fragment.function.name or entry["name"]
                    entry["arguments"] += fragment.function.arguments or ""
            finish = choice.finish_reason or finish
        return LLMResponse(
            text="".join(text),
            tool_calls=[
                _tool_call(c["id"] or f"call_{i}", c["name"], c["arguments"])
                for i, c in sorted(calls.items())
            ],
            stop_reason=_STOP_REASONS.get(finish or "", "other"),
            usage=_token_usage(usage, self.reports_cost),
            provider=self.name,
            model=served_by,
        )

    async def list_models(self) -> list[str]:
        client = self._get_client()
        try:
            return [item.id async for item in client.models.list()]
        except openai.APIStatusError as exc:
            raise ProviderError(
                self.name, exc.message, retryable=False, status_code=exc.status_code
            ) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

    async def aclose(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
        self._client = None

    async def has_model(self, model: str) -> bool:
        return model in await self.list_models()


def _retry_after(exc: Any) -> float | None:
    if exc.status_code != 429:
        return None
    headers = getattr(getattr(exc, "response", None), "headers", None)
    return parse_retry_after(dict(headers) if headers is not None else None, exc.message)


def to_openai_messages(request: LLMRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system = "\n\n".join(part for part in (request.system, request.system_suffix) if part)
    if system:  # stable part first: providers with automatic prefix caching reuse it
        messages.append({"role": "system", "content": system})
    for message in request.messages:
        messages.append(_to_openai_message(message))
    return messages


def _to_openai_message(message: ChatMessage) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments_json()},
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.content}


def _tool_call(call_id: str, name: str, raw: str | None) -> ToolCall:
    raw = raw or ""
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        return ToolCall(call_id, name, None, raw, f"invalid JSON: {exc.msg}")
    if not isinstance(parsed, dict):
        return ToolCall(call_id, name, None, raw, "arguments are not an object")
    return ToolCall(call_id, name, cast(dict[str, Any], parsed), raw)


def _field(obj: Any, key: str) -> Any:
    """Usage arrives as SDK objects, or as plain dicts (Groq's x_groq.usage)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    value = getattr(obj, key, None)
    if value is None:
        value = (getattr(obj, "model_extra", None) or {}).get(key)
    return value


def _token_usage(usage: Any, reports_cost: bool) -> TokenUsage:
    prompt = _field(usage, "prompt_tokens") or 0
    cached = _field(_field(usage, "prompt_tokens_details"), "cached_tokens") or 0
    return TokenUsage(
        input_tokens=max(prompt - cached, 0),
        output_tokens=_field(usage, "completion_tokens") or 0,
        cached_input_tokens=cached,
        reported_cost_usd=_reported_cost(usage) if reports_cost else None,
    )


_TOOL_CALL_REJECTIONS = ("tool call validation failed", "failed to call a function")


def _is_tool_call_rejection(exc: openai.APIStatusError) -> bool:
    """Groq answers 400 (code tool_use_failed) when the model's tool call is malformed."""
    if exc.status_code != 400:
        return False
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error", body)
    code = error.get("code") if isinstance(error, dict) else None
    return code == "tool_use_failed" or any(
        marker in exc.message.lower() for marker in _TOOL_CALL_REJECTIONS
    )


def _reported_cost(usage: Any) -> Decimal | None:
    value = _field(usage, "cost")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
