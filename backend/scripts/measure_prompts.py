"""Token cost of every yaver's system prompt and tool schemas (gpt-oss tokenizer family).

    PYTHONPATH=. uv run python scripts/measure_prompts.py
    docker compose exec api python scripts/measure_prompts.py

o200k_base is the base vocabulary of gpt-oss's o200k_harmony; Groq adds a few tokens of
formatting per message / tool, so totals are slightly below what Groq bills.
"""

import datetime as dt
import json
import uuid
from collections import defaultdict
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import tiktoken

from app.agent.context import ToolContext
from app.agent.coordinator import system_suffix
from app.agent.team import get_team
from app.llm.types import ToolSpec

ENC = tiktoken.get_encoding("o200k_base")


def tokens(text: str) -> int:
    return len(ENC.encode(text))


def tool_tokens(spec: ToolSpec) -> int:
    return tokens(
        json.dumps(
            {"name": spec.name, "description": spec.description, "parameters": spec.parameters},
            ensure_ascii=False,
        )
    )


def main() -> None:
    team = get_team()
    ctx = ToolContext(
        session=MagicMock(),
        now=dt.datetime(2026, 11, 23, 7, tzinfo=dt.UTC),
        tz=ZoneInfo("Europe/Istanbul"),
        change_set_id=uuid.uuid4(),
        recorder=MagicMock(),
    )
    suffix = tokens(system_suffix(ctx, []))
    items: dict[str, list[str]] = defaultdict(list)
    sizes: dict[str, int] = {}
    print(f"{'member':<11} {'prompt':>6} {'suffix':>6} {'tools':>6} {'total':>6}  tools")
    for member in (team.coordinator, *team.agents):
        specs = member.tool_specs(team.delegate_spec())
        prompt = tokens(member.system_prompt)
        tool_total = sum(tool_tokens(s) for s in specs)
        print(
            f"{member.id:<11} {prompt:>6} {suffix:>6} {tool_total:>6} "
            f"{prompt + suffix + tool_total:>6}  {len(specs)}"
        )
        prompt_key = "prompt:coordinator" if member is team.coordinator else "prompt:agent"
        sizes[prompt_key] = max(sizes.get(prompt_key, 0), prompt)
        items[prompt_key].append(member.id)
        items["calendar suffix"].append(member.id)
        sizes["calendar suffix"] = suffix
        for spec in specs:
            sizes[f"tool:{spec.name}"] = tool_tokens(spec)
            items[f"tool:{spec.name}"].append(member.id)
    print("\nlargest items (tokens x members that send it on every call):")
    ranked = sorted(sizes, key=lambda k: sizes[k] * len(items[k]), reverse=True)
    for key in ranked[:12]:
        print(
            f"  {key:<32} {sizes[key]:>5} x {len(items[key])} = {sizes[key] * len(items[key]):>5}"
        )


if __name__ == "__main__":
    main()
