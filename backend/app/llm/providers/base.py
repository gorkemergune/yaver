from typing import Any, Protocol

from app.llm.types import LLMRequest, LLMResponse


class Provider(Protocol):
    name: str
    reports_cost: bool

    @property
    def configured(self) -> bool:
        """False when the API key / base URL is missing (the router then skips the tier)."""
        ...

    async def complete(
        self, request: LLMRequest, model: str, options: dict[str, Any]
    ) -> LLMResponse: ...

    async def list_models(self) -> list[str]: ...

    async def has_model(self, model: str) -> bool:
        """Does the provider's /models endpoint know this model id?"""
        ...

    async def aclose(self) -> None:
        """Close the underlying HTTP client (if one was created)."""
        ...
