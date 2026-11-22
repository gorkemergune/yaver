"""JSON schema of a Pydantic model as sent to the LLM (tool arguments, structured replies).

Its own module, with no app imports: code outside the tool registry (materials ingest,
documents, vision, jobs) needs a schema without loading `app.agent.tools`, whose import
registers every tool module (`tools/materials.py` -> `app.materials` ...). Importing the
registry from `app.materials.mapping` made a cycle that only broke when `app.materials`
was imported first (`python -m app.materials.bundle` on live, 2026-11-22).
"""

from typing import Any

from pydantic import BaseModel

HHMM_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Compact JSON schema: no titles, enums inlined (Literal types), no $defs."""
    schema = model.model_json_schema()

    def clean(node: Any) -> Any:
        if isinstance(node, list):
            return [clean(item) for item in node]
        if not isinstance(node, dict):
            return node
        # Optional fields: {"anyOf": [X, {"type": "null"}]} -> X with type [t, "null"].
        # Models often send null for unused optional fields and Groq validates the schema
        # server-side, so null must stay allowed.
        options = node.get("anyOf")
        if isinstance(options, list) and len(options) == 2 and {"type": "null"} in options:
            merged = {k: v for k, v in node.items() if k != "anyOf"}
            merged.update(next(o for o in options if o != {"type": "null"}))
            if isinstance(merged.get("type"), str):
                merged["type"] = [merged["type"], "null"]
            node = merged
        if node.get("format") == "time":
            # JSON-schema "time" is RFC 3339 (09:00:00+00:00) and providers that validate
            # server-side (Groq) reject "09:00"; we want HH:MM.
            node = {k: v for k, v in node.items() if k != "format"}
            node["pattern"] = HHMM_PATTERN
        return {
            key: clean(value)
            for key, value in node.items()
            # Drop schema annotations only: a property *named* "title" is a dict, keep it.
            if not (key in ("title", "default") and not isinstance(value, dict))
        }

    cleaned: dict[str, Any] = clean(schema)
    cleaned.setdefault("properties", {})
    cleaned["additionalProperties"] = False
    return cleaned
