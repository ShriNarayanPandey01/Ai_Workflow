from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult, TransientNodeError
from ai_workflow.runtime.outputs import require_node_result
from ai_workflow.runtime.registry import NodeRegistration

SleepBackoff = Callable[..., Awaitable[None]]
ContextFactory = Callable[[int], ExecutionContext]


async def sleep_backoff(backoff_ms: int, *, jitter: bool) -> None:
    """Sleep for the backoff interval, optionally applying jitter.

    Jitter is derived from the event-loop clock rather than a PRNG so the
    runner stays free of ``random`` (disallowed in some sandboxes) while
    still spreading retries across the window.
    """
    delay = max(0.0, backoff_ms / 1000.0)
    if jitter and delay > 0:
        frac = asyncio.get_running_loop().time() % 1.0
        delay = delay * (0.5 + 0.5 * frac)
    if delay > 0:
        await asyncio.sleep(delay)


async def execute_with_retry(
    *,
    registration: NodeRegistration,
    context_factory: ContextFactory,
    config: dict[str, JsonValue],
    inputs: dict[str, JsonValue],
    max_attempts: int,
    initial_backoff_ms: int,
    multiplier: float,
    max_backoff_ms: int,
    jitter: bool,
    sleep_backoff: SleepBackoff = sleep_backoff,
) -> tuple[NodeResult, ExecutionContext]:
    """Retry TransientNodeError. Idempotency keys must not include attempt."""
    backoff_ms = initial_backoff_ms
    last_error: TransientNodeError | None = None
    for attempt in range(1, max_attempts + 1):
        context = context_factory(attempt)
        executor = registration.executor_factory()
        try:
            result = await executor.execute(context, config, inputs)
            require_node_result(result, registration.manifest)
            return result, context
        except TransientNodeError as exc:
            last_error = exc
            if attempt < max_attempts:
                await sleep_backoff(backoff_ms, jitter=jitter)
                backoff_ms = min(int(backoff_ms * multiplier), max_backoff_ms)
                continue
            raise
    assert last_error is not None
    raise last_error
