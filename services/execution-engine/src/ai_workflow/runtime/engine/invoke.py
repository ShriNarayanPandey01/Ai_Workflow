from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.contracts.workflow.definition import RetryPolicy
from ai_workflow.nodes.base import ExecutionContext, NodeResult, TransientNodeError
from ai_workflow.runtime.registry import NodeRegistration
from ai_workflow.runtime.semantics.outputs import NodeOutputContract

SleepBackoff = Callable[..., Awaitable[None]]
ContextFactory = Callable[[int], ExecutionContext]


async def sleep_backoff(backoff_ms: int, *, jitter: bool) -> None:
    """Sleep for the backoff interval, optionally applying jitter.

    Jitter is derived from the event-loop clock rather than a PRNG so the
    runner stays free of ``random`` (disallowed in some sandboxes) while
    still spreading retries across the window.
    """
    import asyncio

    delay = max(0.0, backoff_ms / 1000.0)
    if jitter and delay > 0:
        frac = asyncio.get_running_loop().time() % 1.0
        delay = delay * (0.5 + 0.5 * frac)
    if delay > 0:
        await asyncio.sleep(delay)


class NodeInvoker(ABC):
    """Replaceable strategy for executing one registered inline node."""

    @abstractmethod
    async def invoke(
        self,
        *,
        registration: NodeRegistration,
        context_factory: ContextFactory,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
        retry: RetryPolicy,
    ) -> tuple[NodeResult, ExecutionContext]: ...


class RetryingNodeInvoker(NodeInvoker):
    """Retry TransientNodeError using the workflow retry policy."""

    def __init__(
        self,
        sleeper: SleepBackoff = sleep_backoff,
        *,
        outputs: NodeOutputContract | None = None,
    ) -> None:
        self._sleeper = sleeper
        self._outputs = outputs or NodeOutputContract()

    async def invoke(
        self,
        *,
        registration: NodeRegistration,
        context_factory: ContextFactory,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
        retry: RetryPolicy,
    ) -> tuple[NodeResult, ExecutionContext]:
        max_attempts = max(1, retry.max_attempts)
        backoff_ms = retry.initial_backoff_ms
        last_error: TransientNodeError | None = None
        for attempt in range(1, max_attempts + 1):
            context = context_factory(attempt)
            executor = registration.executor_factory()
            try:
                result = await executor.execute(context, config, inputs)
                self._outputs.require_result(result, registration.manifest)
                return result, context
            except TransientNodeError as exc:
                last_error = exc
                if attempt < max_attempts:
                    await self._sleeper(backoff_ms, jitter=retry.jitter)
                    backoff_ms = min(int(backoff_ms * retry.multiplier), retry.max_backoff_ms)
                    continue
                raise
        assert last_error is not None
        raise last_error


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
    retry = RetryPolicy(
        max_attempts=max_attempts,
        initial_backoff_ms=initial_backoff_ms,
        multiplier=multiplier,
        max_backoff_ms=max_backoff_ms,
        jitter=jitter,
    )
    return await RetryingNodeInvoker(sleeper=sleep_backoff).invoke(
        registration=registration,
        context_factory=context_factory,
        config=config,
        inputs=inputs,
        retry=retry,
    )
