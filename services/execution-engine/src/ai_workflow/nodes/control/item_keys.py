from __future__ import annotations

import hashlib
import json

from ai_workflow.contracts.common.types import JsonValue


def canonical_json(value: JsonValue) -> str:
    """Serialize JSON with stable key ordering for hashing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_item_key(index: int, item: JsonValue) -> str:
    """Return a restart-stable key from index plus canonical item hash."""
    digest = hashlib.sha256(canonical_json(item).encode("utf-8")).hexdigest()[:16]
    return f"{index}:{digest}"


def parse_items_input(raw: JsonValue) -> list[JsonValue]:
    """Normalize for-each items input from catalog shape or bare list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return raw["items"]
    msg = "for-each items input must be a list or {items: [...]}"
    raise ValueError(msg)
