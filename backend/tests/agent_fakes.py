"""Scripted LLM for agent tests: per agent_id a queue of responses (or functions of the
request, to use earlier tool results the way a real model would)."""

import datetime as dt
import json
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any

import yaml

from app.agent.coordinator import Coordinator
from app.agent.team import Team, TeamConfig, build_team
from app.config import Settings
from app.llm.types import LLMRequest, LLMResponse, TokenUsage, ToolCall

# Monday 23 November 2026, 10:00 in Istanbul
NOW = dt.datetime(2026, 11, 23, 7, 0, tzinfo=dt.UTC)
REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"

Step = LLMResponse | Callable[[LLMRequest], LLMResponse]
_ids = count(1)


def call(name: str, **arguments: Any) -> LLMResponse:
    return calls((name, arguments))


def calls(*items: tuple[str, dict[str, Any]]) -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=[ToolCall(f"call_{next(_ids)}", name, args) for name, args in items],
        stop_reason="tool_use",
        usage=TokenUsage(100, 20),
        provider="",
        model="",
    )


def say(text: str) -> LLMResponse:
    return LLMResponse(text, [], "end", TokenUsage(100, 20), "", "")


def last_result(request: LLMRequest) -> dict[str, Any]:
    """The newest tool result the model can see."""
    tool_messages = [m for m in request.messages if m.role == "tool"]
    assert tool_messages, "no tool result yet"
    result: dict[str, Any] = json.loads(tool_messages[-1].content)
    return result


class ScriptedLLM:
    def __init__(self, scripts: dict[str, list[Step]] | None = None) -> None:
        self.scripts: dict[str, list[Step]] = {k: list(v) for k, v in (scripts or {}).items()}
        self.requests: list[tuple[str | None, LLMRequest]] = []
        self.models: list[Mapping[str, str] | None] = []
        self.purposes: list[str] = []

    def add(self, agent_id: str, *steps: Step) -> None:
        self.scripts.setdefault(agent_id, []).extend(steps)

    async def complete(
        self,
        request: LLMRequest,
        *,
        purpose: str = "chat",
        tier: str | None = None,
        agent_id: str | None = None,
        ignore_budget: bool = False,
        model: Mapping[str, str] | None = None,
        on_text: Callable[[str], Awaitable[None]] | None = None,
        on_retry: Callable[[], Awaitable[None]] | None = None,
        on_wait: Callable[[float, str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        self.requests.append((agent_id, request))
        self.models.append(model)
        self.purposes.append(purpose)
        queue = self.scripts.get(agent_id or "")
        assert queue, f"unexpected LLM call for {agent_id!r}"
        step = queue.pop(0)
        response = step(request) if callable(step) else step
        response.tier, response.provider, response.model = tier or "fast", "fake", "fake"
        response.cost_usd = Decimal("0.0001")
        if on_text is not None and response.text:
            for word in response.text.split(" "):
                await on_text(word + " ")
        return response

    def assert_done(self) -> None:
        leftover = {agent: len(queue) for agent, queue in self.scripts.items() if queue}
        assert not leftover, f"unused scripted steps: {leftover}"


def example_team() -> Team:
    with (REPO_CONFIG / "agents.example.yaml").open(encoding="utf-8") as fh:
        config = TeamConfig.model_validate(yaml.safe_load(fh))
    return build_team(config, "Görkem")


def coordinator(llm: ScriptedLLM) -> Coordinator:
    return Coordinator(llm, example_team(), Settings(_env_file=None))
