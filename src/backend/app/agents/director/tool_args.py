"""Coerce Ollama nested JSON-string tool arguments into objects."""

from __future__ import annotations

import json
from typing import Any


def coerce_jsonish(value: Any) -> Any:
    """Parse JSON objects/arrays that arrived as strings; recurse into containers."""
    if isinstance(value, str):
        text = value.strip()
        if len(text) >= 2 and text[0] in "{[" and text[-1] in "}]":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return value
            return coerce_jsonish(parsed)
        return value
    if isinstance(value, list):
        return [coerce_jsonish(item) for item in value]
    if isinstance(value, dict):
        return {str(key): coerce_jsonish(item) for key, item in value.items()}
    return value


def coerce_tool_args(value: Any) -> dict[str, Any]:
    parsed = coerce_jsonish(value)
    return parsed if isinstance(parsed, dict) else {}
