from __future__ import annotations

import httpx

from ai_workflow.security.http_client import DEFAULT_HTTPX_TIMEOUT, create_async_client


def test_create_async_client_sets_explicit_timeout() -> None:
    client = create_async_client()
    assert client.timeout == DEFAULT_HTTPX_TIMEOUT
    assert client.timeout.connect == 30.0


def test_create_async_client_honors_override() -> None:
    client = create_async_client(timeout=httpx.Timeout(5.0))
    assert client.timeout.connect == 5.0
