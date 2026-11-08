from __future__ import annotations

import json
from typing import Any

from ai_workflow.contracts.common.types import JsonValue

REDACTED = "[REDACTED]"

DEFAULT_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "api-key",
        "x-api-key",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "session_token",
        "private_key",
        "bearer",
        "cookie",
        "set-cookie",
        "credentials",
    }
)

# Suffixes that mark a compound key as secret-bearing (e.g. ``openai_api_key``,
# ``webhook_secret``). Kept deliberately narrow so token *count* fields such as
# ``prompt_tokens``/``total_tokens`` (which end in ``_tokens``, not ``_token``)
# are never redacted.
_SENSITIVE_KEY_SUFFIXES = (
    "_api_key",
    "-api-key",
    "_apikey",
    "-apikey",
    "_secret",
    "-secret",
    "_password",
    "-password",
    "_passwd",
    "_token",
    "-token",
    "_private_key",
    "-private-key",
    "_access_key",
    "-access-key",
    "_secret_key",
    "-secret-key",
)


def _is_sensitive_key(key: object, sensitive_keys: frozenset[str]) -> bool:
    """Return whether a mapping key should have its value redacted."""
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    if lowered in sensitive_keys:
        return True
    return any(lowered.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


class PayloadTooLargeError(ValueError):
    """Raised when a value exceeds the configured payload size limit."""


def redact_value(
    value: JsonValue,
    *,
    sensitive_keys: frozenset[str] = DEFAULT_SENSITIVE_KEYS,
) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: REDACTED
            if _is_sensitive_key(key, sensitive_keys)
            else redact_value(item, sensitive_keys=sensitive_keys)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, sensitive_keys=sensitive_keys) for item in value]
    return value


def payload_size_bytes(value: JsonValue) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def enforce_payload_limit(value: JsonValue, max_bytes: int) -> JsonValue:
    """Validate that a JSON value does not exceed the configured byte limit."""
    if payload_size_bytes(value) > max_bytes:
        msg = f"Payload exceeds limit of {max_bytes} bytes"
        raise PayloadTooLargeError(msg)
    return value


def redact_state_snapshot(value: Any) -> JsonValue:
    """Redact a workflow state snapshot for checkpointing or logging."""
    if hasattr(value, "snapshot"):
        snapshot = value.snapshot()
        return redact_value(
            {
                "node_outputs": snapshot.node_outputs,
                "loop_iterations": snapshot.loop_iterations,
                "task_refs": snapshot.task_refs,
                "runtime": snapshot.runtime,
            }
        )
    return redact_value(value)
