"""Provider-neutral request/response types. Every provider converts to and from these."""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]
ToolChoice = Literal["auto", "required", "none"]
StopReason = Literal["end", "tool_use", "max_tokens", "refusal", "other"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments object


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None  # None when the model's JSON could not be parsed
    raw_arguments: str | None = None
    parse_error: str | None = None

    def arguments_json(self) -> str:
        if self.arguments is not None:
            return json.dumps(self.arguments, ensure_ascii=False, sort_keys=True)
        return self.raw_arguments or "{}"


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # role == "tool": which call this answers
    is_error: bool = False  # role == "tool": the tool failed
    # Provider-native content to replay verbatim on the same provider (e.g. Anthropic
    # thinking blocks with signatures). Ignored by other providers.
    provider_state: dict[str, Any] | None = None


@dataclass(slots=True)
class LLMRequest:
    messages: list[ChatMessage]
    system: str | None = None  # keep stable across requests: it is the cached prefix
    # Changes per day/request (calendar context, today's date): sent after the cached part.
    system_suffix: str | None = None
    tools: list[ToolSpec] = field(default_factory=list)
    tool_choice: ToolChoice = "auto"
    max_tokens: int = 4096
    cache: bool = True


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int = 0  # uncached input
    output_tokens: int = 0
    cached_input_tokens: int = 0  # prompt-cache reads
    cache_write_tokens: int = 0
    reported_cost_usd: Decimal | None = None  # provider-reported (OpenRouter)

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cached_input_tokens + self.cache_write_tokens


@dataclass(slots=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    usage: TokenUsage
    provider: str
    model: str
    provider_state: dict[str, Any] | None = None
    # Filled in by the router:
    tier: str = ""
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0
    usage_id: int | None = None

    def to_message(self) -> ChatMessage:
        return ChatMessage(
            role="assistant",
            content=self.text,
            tool_calls=list(self.tool_calls),
            provider_state=self.provider_state,
        )


class ProviderError(Exception):
    """A provider call failed. `retryable` errors (429, 5xx, network, missing key) make the
    router fail over to the next tier; others are raised to the caller."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code


class ProviderNotConfiguredError(ProviderError):
    def __init__(self, provider: str, message: str) -> None:
        super().__init__(provider, message, retryable=True)
