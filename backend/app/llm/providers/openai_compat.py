"""OpenAI-compatible chat completions: Groq, OpenRouter, Ollama."""

import json
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import openai
from openai import AsyncOpenAI

from app.llm.types import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    ProviderError,
    ProviderNotConfiguredError,
    StopReason,
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
        self, request: LLMRequest, model: str, options: dict[str, Any]
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
            response = await self._get_client().chat.completions.create(**kwargs)
        except ProviderError:
            raise
        except openai.APIStatusError as exc:
            raise ProviderError(
                self.name,
                exc.message,
                retryable=exc.status_code == 429 or exc.status_code >= 500,
                status_code=exc.status_code,
            ) from exc
        except openai.APIConnectionError as exc:  # includes timeouts
            raise ProviderError(self.name, str(exc), retryable=True) from exc
        return self._parse(response, model)

    def _parse(self, response: Any, model: str) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message
        usage = response.usage
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        if details is not None:
            cached = getattr(details, "cached_tokens", None) or 0
        prompt = (usage.prompt_tokens or 0) if usage else 0
        token_usage = TokenUsage(
            input_tokens=max(prompt - cached, 0),
            output_tokens=(usage.completion_tokens or 0) if usage else 0,
            cached_input_tokens=cached,
            reported_cost_usd=_reported_cost(usage) if self.reports_cost else None,
        )
        return LLMResponse(
            text=message.content or "",
            tool_calls=[_parse_tool_call(call) for call in message.tool_calls or []],
            stop_reason=_STOP_REASONS.get(choice.finish_reason or "", "other"),
            usage=token_usage,
            provider=self.name,
            model=getattr(response, "model", None) or model,
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


def to_openai_messages(request: LLMRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
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


def _parse_tool_call(call: Any) -> ToolCall:
    raw = call.function.arguments or ""
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        return ToolCall(call.id, call.function.name, None, raw, f"invalid JSON: {exc.msg}")
    if not isinstance(parsed, dict):
        return ToolCall(call.id, call.function.name, None, raw, "arguments are not an object")
    return ToolCall(call.id, call.function.name, cast(dict[str, Any], parsed), raw)


def _reported_cost(usage: Any) -> Decimal | None:
    if usage is None:
        return None
    value = getattr(usage, "cost", None)
    if value is None:
        value = (getattr(usage, "model_extra", None) or {}).get("cost")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
