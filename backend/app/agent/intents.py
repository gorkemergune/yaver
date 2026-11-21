"""Intent-first routing: before the coordinator answers, one cheap call (`intent_classify`,
fast tier) splits the message into parts and names what the user wants to do in each.
Who owns an intent is fixed here, in code - never a guess from a word in the message: a
place ("Medipol", "Iceberg") or a course-sounding word decides nothing on its own.

The coordinator then delegates each owned part in code (app.agent.coordinator) and only
writes the answer; questions about the plan, memories and undo stay with the coordinator.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agent.intent_map import AREAS, OWNERS, Intent  # noqa: F401 (re-exported)
from app.agent.tools import json_schema
from app.llm.types import ChatMessage, LLMRequest, ProviderError, ToolSpec

logger = logging.getLogger(__name__)

PURPOSE = "intent_classify"  # fast tier (providers.yaml routing.purposes)


class Part(BaseModel):
    intent: Intent
    text: str = Field(max_length=2000, description="the user's own words for this part")


class Classification(BaseModel):
    parts: list[Part] = Field(min_length=1, max_length=5)


TOOL = ToolSpec(
    "route",
    "Split the message into parts and name each part's intent.",
    json_schema(Classification),
)
# The rules and the intents with examples (kept out of code: long lines of prose).
PROMPT = (Path(__file__).with_name("prompts") / "intents.md").read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class Routed:
    intent: str
    text: str
    owner: str | None  # employee id, None = the coordinator


def owner_of(intent: str, team_ids: set[str]) -> str | None:
    owner = OWNERS.get(intent)
    return owner if owner in team_ids else None


async def classify(
    llm: Any, text: str, team_ids: set[str], *, open_question: str | None = None
) -> list[Routed] | None:
    """The parts of the message with their owners; None when no model answered (the
    coordinator then routes on its own, as before)."""
    content = f"Mesaj: {text}"
    if open_question:
        content = f"Açık soru (ekip az önce sordu): {open_question}\n\n{content}"
    request = LLMRequest(
        system=PROMPT,
        messages=[ChatMessage("user", content)],
        tools=[TOOL],
        tool_choice="required",
        max_tokens=600,
    )
    try:
        response = await llm.complete(request, purpose=PURPOSE, agent_id="yaver")
        call = next((c for c in response.tool_calls if c.name == TOOL.name), None)
        if call is None or call.arguments is None:
            raise ValueError("the model did not call route")
        parts = Classification.model_validate(call.arguments).parts
    except (ProviderError, ValidationError, ValueError) as exc:
        logger.warning("intent classification failed: %s", exc)
        return None
    except Exception as exc:  # e.g. LLMUnavailableError: routing falls back, chat goes on
        logger.warning("intent classification failed: %r", exc)
        return None
    if not open_question:
        parts = [p if p.intent != "answer" else Part(intent="other", text=p.text) for p in parts]
    routed = [Routed(p.intent, p.text.strip() or text, owner_of(p.intent, team_ids)) for p in parts]
    logger.info("intents for %r: %s", text, [(r.intent, r.owner) for r in routed])
    return routed
