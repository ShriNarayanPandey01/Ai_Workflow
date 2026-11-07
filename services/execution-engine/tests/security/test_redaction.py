from __future__ import annotations

import pytest

from ai_workflow.runtime.graph.state import WorkflowState
from ai_workflow.security.redaction import (
    REDACTED,
    PayloadTooLargeError,
    enforce_payload_limit,
    redact_state_snapshot,
    redact_value,
)


def test_redact_value_hides_sensitive_keys() -> None:
    value = {
        "authorization": "Bearer secret-token",
        "headers": {"api_key": "sk-test"},
        "order_id": "ord-1",
    }

    redacted = redact_value(value)

    assert redacted["authorization"] == REDACTED
    assert redacted["headers"]["api_key"] == REDACTED
    assert redacted["order_id"] == "ord-1"


def test_redact_value_hides_compound_secret_keys() -> None:
    value = {
        "openai_api_key": "sk-live-123",
        "client_secret": "csx",
        "webhook_secret": "whsec",
        "private_key": "-----BEGIN",
        "cookie": "session=abc",
        "set-cookie": "session=abc",
        "config": {"stripe_secret_key": "sk_live"},
    }

    redacted = redact_value(value)

    assert redacted["openai_api_key"] == REDACTED
    assert redacted["client_secret"] == REDACTED
    assert redacted["webhook_secret"] == REDACTED
    assert redacted["private_key"] == REDACTED
    assert redacted["cookie"] == REDACTED
    assert redacted["set-cookie"] == REDACTED
    assert redacted["config"]["stripe_secret_key"] == REDACTED


def test_redact_value_preserves_token_count_fields() -> None:
    # Usage metadata must survive: plural ``_tokens`` is not a secret suffix.
    value = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}

    redacted = redact_value(value)

    assert redacted["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


def test_enforce_payload_limit_raises_when_too_large() -> None:
    with pytest.raises(PayloadTooLargeError):
        enforce_payload_limit({"data": "x" * 1000}, max_bytes=10)


def test_redact_state_snapshot_redacts_runtime_secrets() -> None:
    state = WorkflowState(runtime={"api_key": "secret", "run_input": {"id": "1"}})

    snapshot = redact_state_snapshot(state)

    assert snapshot["runtime"]["api_key"] == REDACTED
    assert snapshot["runtime"]["run_input"] == {"id": "1"}
