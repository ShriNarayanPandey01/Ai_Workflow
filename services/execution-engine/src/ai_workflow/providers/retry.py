from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

T = TypeVar("T")


async def retry_provider_call(
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    initial_backoff_ms: int,
    max_backoff_ms: int,
    multiplier: float,
    transient_error: type[Exception],
) -> T:
    """Retry a provider HTTP call on transient HTTP and transport errors."""
    attempt = 0
    backoff_ms = initial_backoff_ms
    last_error: Exception | None = None
    while attempt < max_attempts:
        attempt += 1
        try:
            return await operation()
        except transient_error as exc:
            last_error = exc
        except httpx.TransportError as exc:
            last_error = transient_error(str(exc))
        if attempt >= max_attempts:
            break
        await asyncio.sleep(backoff_ms / 1000.0)
        backoff_ms = min(int(backoff_ms * multiplier), max_backoff_ms)
    assert last_error is not None
    raise last_error
