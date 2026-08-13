from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.contracts.workflow.definition import WorkflowDefinition, WorkflowEdge
from ai_workflow.nodes.base import ExecutionContext
from ai_workflow.runtime.bindings import bindings_for_node, resolve_available_inputs
from ai_workflow.runtime.execute_node import execute_with_retry
from ai_workflow.runtime.registry import RuntimeRegistry
from ai_workflow.runtime.semantic import build_state_root
from ai_workflow.runtime.state import WorkflowState

ItemStatus = Literal["pending", "success", "failure", "skipped"]


@dataclass
class ForEachFrame:
    """Tracks per-item subflow execution for one control.for-each@1 node."""

    for_each_node_id: str
    collect_node_id: str
    body_node_ids: set[str]
    body_entry_ids: list[str]
    envelopes: list[dict[str, JsonValue]]
    item_status: dict[str, ItemStatus] = field(default_factory=dict)
    item_results: dict[str, JsonValue] = field(default_factory=dict)
    item_errors: dict[str, str] = field(default_factory=dict)
    completion_seq: dict[str, int] = field(default_factory=dict)
    next_completion_seq: int = 0
    concurrency: int = 1
    item_timeout_seconds: int = 60
    failure_policy: Literal["fail_fast", "continue"] = "continue"
    ordering: Literal["preserve_input", "completion_order"] = "preserve_input"
    completed: bool = False

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "for_each_node_id": self.for_each_node_id,
            "collect_node_id": self.collect_node_id,
            "body_node_ids": sorted(self.body_node_ids),
            "body_entry_ids": self.body_entry_ids,
            "envelopes": self.envelopes,
            "item_status": dict(self.item_status),
            "item_results": dict(self.item_results),
            "item_errors": dict(self.item_errors),
            "completion_seq": {k: v for k, v in self.completion_seq.items()},
            "next_completion_seq": self.next_completion_seq,
            "concurrency": self.concurrency,
            "item_timeout_seconds": self.item_timeout_seconds,
            "failure_policy": self.failure_policy,
            "ordering": self.ordering,
            "completed": self.completed,
        }

    @classmethod
    def from_json(cls, raw: dict[str, JsonValue]) -> ForEachFrame:
        body_ids = raw.get("body_node_ids", [])
        envelopes = raw.get("envelopes", [])
        item_status_raw = raw.get("item_status", {})
        item_results_raw = raw.get("item_results", {})
        item_errors_raw = raw.get("item_errors", {})
        completion_seq_raw = raw.get("completion_seq", {})
        return cls(
            for_each_node_id=str(raw["for_each_node_id"]),
            collect_node_id=str(raw["collect_node_id"]),
            body_node_ids=set(str(x) for x in body_ids) if isinstance(body_ids, list) else set(),
            body_entry_ids=[str(x) for x in raw.get("body_entry_ids", [])]
            if isinstance(raw.get("body_entry_ids"), list)
            else [],
            envelopes=[e for e in envelopes if isinstance(e, dict)]
            if isinstance(envelopes, list)
            else [],
            item_status={
                str(k): v
                for k, v in item_status_raw.items()
                if isinstance(item_status_raw, dict) and isinstance(v, str)
            },
            item_results={
                str(k): v
                for k, v in item_results_raw.items()
                if isinstance(item_results_raw, dict)
            },
            item_errors={
                str(k): str(v)
                for k, v in item_errors_raw.items()
                if isinstance(item_errors_raw, dict)
            },
            completion_seq={
                str(k): int(v)
                for k, v in completion_seq_raw.items()
                if isinstance(completion_seq_raw, dict) and isinstance(v, int)
            },
            next_completion_seq=int(raw.get("next_completion_seq", 0))
            if isinstance(raw.get("next_completion_seq"), int)
            else 0,
            concurrency=int(raw["concurrency"]) if isinstance(raw.get("concurrency"), int) else 1,
            item_timeout_seconds=int(raw["item_timeout_seconds"])
            if isinstance(raw.get("item_timeout_seconds"), int)
            else 60,
            failure_policy=raw["failure_policy"]
            if raw.get("failure_policy") in {"fail_fast", "continue"}
            else "continue",
            ordering=raw["ordering"]
            if raw.get("ordering") in {"preserve_input", "completion_order"}
            else "preserve_input",
            completed=bool(raw.get("completed", False)),
        )

    def collect_items(self) -> list[dict[str, JsonValue]]:
        rows: list[dict[str, JsonValue]] = []
        for envelope in self.envelopes:
            item_key = str(envelope.get("item_key", ""))
            index = envelope.get("index", 0)
            status = self.item_status.get(item_key, "pending")
            row: dict[str, JsonValue] = {
                "item_key": item_key,
                "index": index,
                "status": status,
            }
            if status == "success" and item_key in self.item_results:
                row["value"] = self.item_results[item_key]
            if status == "failure" and item_key in self.item_errors:
                row["error"] = self.item_errors[item_key]
            if status == "skipped":
                row["reason"] = "fail_fast"
            if item_key in self.completion_seq:
                row["completion_seq"] = self.completion_seq[item_key]
            rows.append(row)
        return rows

    def pending_keys(self) -> list[str]:
        return [
            str(envelope["item_key"])
            for envelope in self.envelopes
            if isinstance(envelope.get("item_key"), str)
            and self.item_status.get(str(envelope["item_key"]), "pending") == "pending"
        ]


FOREACH_FRAMES_KEY = "_for_each_frames"
COLLECT_INJECT_KEY = "_collect_inject"


def save_foreach_frames(state: WorkflowState, frames: dict[str, ForEachFrame]) -> None:
    state.runtime[FOREACH_FRAMES_KEY] = {
        node_id: frame.to_json() for node_id, frame in frames.items()
    }


def load_foreach_frames(state: WorkflowState) -> dict[str, ForEachFrame]:
    raw = state.runtime.get(FOREACH_FRAMES_KEY)
    if not isinstance(raw, dict):
        return {}
    frames: dict[str, ForEachFrame] = {}
    for node_id, payload in raw.items():
        if isinstance(payload, dict):
            frames[str(node_id)] = ForEachFrame.from_json(payload)
    return frames


def _collect_node_ids(workflow: WorkflowDefinition) -> set[str]:
    return {str(node.id) for node in workflow.nodes if node.type == "control.collect@1"}


def detect_foreach_region(
    workflow: WorkflowDefinition,
    *,
    for_each_node_id: str,
    outgoing: dict[str, dict[str, list[WorkflowEdge]]],
) -> tuple[set[str], list[str], str | None]:
    """Return body node ids, entry ids, and downstream collect node id."""
    item_edges = outgoing.get(for_each_node_id, {}).get("item", [])
    body_entry_ids = [str(edge.target_node_id) for edge in item_edges]
    collect_candidates = _collect_node_ids(workflow)

    body_nodes: set[str] = set()
    queue = deque(body_entry_ids)
    while queue:
        current = queue.popleft()
        if current in body_nodes or current == for_each_node_id:
            continue
        if current in collect_candidates:
            continue
        body_nodes.add(current)
        for edge in workflow.edges:
            if str(edge.source_node_id) != current:
                continue
            target = str(edge.target_node_id)
            if target in collect_candidates or target == for_each_node_id:
                continue
            if target not in body_nodes:
                queue.append(target)

    collect_node_id: str | None = None
    for candidate in collect_candidates:
        for edge in workflow.edges:
            source = str(edge.source_node_id)
            if str(edge.target_node_id) == candidate and (
                source in body_nodes or source == for_each_node_id
            ):
                collect_node_id = candidate
                break
        if collect_node_id is not None:
            break

    if collect_node_id is None and len(collect_candidates) == 1:
        collect_node_id = next(iter(collect_candidates))

    return body_nodes, body_entry_ids, collect_node_id


def _body_topo_order(
    workflow: WorkflowDefinition,
    body_node_ids: set[str],
    body_entry_ids: list[str],
) -> list[str]:
    indegree: dict[str, int] = {node_id: 0 for node_id in body_node_ids}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in workflow.edges:
        source = str(edge.source_node_id)
        target = str(edge.target_node_id)
        if source in body_node_ids and target in body_node_ids:
            adjacency[source].append(target)
            indegree[target] += 1

    queue = deque([node_id for node_id in body_entry_ids if node_id in body_node_ids])
    for node_id in body_node_ids:
        if indegree[node_id] == 0 and node_id not in queue:
            queue.append(node_id)

    order: list[str] = []
    seen: set[str] = set()
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        order.append(current)
        for target in adjacency.get(current, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    for node_id in body_node_ids:
        if node_id not in seen:
            order.append(node_id)
    return order


def _body_sink_nodes(
    workflow: WorkflowDefinition,
    body_node_ids: set[str],
) -> list[str]:
    has_outgoing: set[str] = set()
    for edge in workflow.edges:
        source = str(edge.source_node_id)
        target = str(edge.target_node_id)
        if source in body_node_ids and target in body_node_ids:
            has_outgoing.add(source)
    return [node_id for node_id in body_node_ids if node_id not in has_outgoing]


async def _sleep_backoff(backoff_ms: int, *, jitter: bool) -> None:
    delay = max(0.0, backoff_ms / 1000.0)
    if jitter and delay > 0:
        frac = asyncio.get_event_loop().time() % 1.0
        delay = delay * (0.5 + 0.5 * frac)
    if delay > 0:
        await asyncio.sleep(delay)


async def _execute_item_body(
    *,
    workflow: WorkflowDefinition,
    registry: RuntimeRegistry,
    frame: ForEachFrame,
    envelope: dict[str, JsonValue],
    global_state: WorkflowState,
    run_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    credential_resolver: object | None,
    cancel_check: Callable[[], bool] | None = None,
) -> JsonValue:
    item_key = str(envelope["item_key"])
    item_outputs: dict[str, dict[str, JsonValue]] = {}
    item_outputs[frame.for_each_node_id] = {"item": envelope}

    nodes_by_id = workflow.node_by_id()
    order = _body_topo_order(workflow, frame.body_node_ids, frame.body_entry_ids)
    retry_policy = workflow.execution_policy.default_retry
    max_attempts = max(1, retry_policy.max_attempts)

    for body_node_id in order:
        node = nodes_by_id[body_node_id]
        registration = registry.get_node(node.type)
        bindings = bindings_for_node(node, workflow.incoming_edges(node.id))
        merged_outputs = dict(global_state.node_outputs)
        merged_outputs.update(item_outputs)
        inputs = resolve_available_inputs(bindings, merged_outputs)

        state_root = build_state_root(
            node_outputs=merged_outputs,
            loop_iterations=global_state.loop_iterations,
            runtime=global_state.runtime,
        )
        runtime = dict(global_state.runtime)
        runtime["_state_root"] = state_root
        runtime["_loop_iterations"] = dict(global_state.loop_iterations)
        runtime["_foreach_item"] = envelope

        def context_factory(
            attempt: int,
            *,
            _node=node,
            _runtime=runtime,
        ) -> ExecutionContext:
            return ExecutionContext(
                run_id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                workflow_version_id=workflow.workflow_version_id,
                node_id=_node.id,
                attempt=attempt,
                idempotency_key=f"{run_id}:{_node.id}:{item_key}",
                runtime=_runtime,
                input_schema=workflow.input_schema,
                output_schema=workflow.output_schema,
                credential_refs=dict(_node.credential_refs),
                resource_refs=dict(_node.resource_refs),
                credential_resolver=credential_resolver,
                cancel_check=cancel_check or (lambda: False),
            )

        result, _context = await execute_with_retry(
            registration=registration,
            context_factory=context_factory,
            config=node.config,
            inputs=inputs,
            max_attempts=max_attempts,
            initial_backoff_ms=retry_policy.initial_backoff_ms,
            multiplier=retry_policy.multiplier,
            max_backoff_ms=retry_policy.max_backoff_ms,
            jitter=retry_policy.jitter,
            sleep_backoff=_sleep_backoff,
        )
        item_outputs[body_node_id] = dict(result.outputs)

    sinks = _body_sink_nodes(workflow, frame.body_node_ids)
    if not sinks:
        msg = f"No sink nodes in for-each body for item {item_key}"
        raise ValueError(msg)

    last_sink = sinks[-1]
    sink_outputs = item_outputs.get(last_sink, {})
    if "value" in sink_outputs:
        return sink_outputs["value"]
    if "text" in sink_outputs:
        return sink_outputs["text"]
    if len(sink_outputs) == 1:
        return next(iter(sink_outputs.values()))
    return sink_outputs


async def run_foreach_frame(
    *,
    workflow: WorkflowDefinition,
    registry: RuntimeRegistry,
    frame: ForEachFrame,
    state: WorkflowState,
    run_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    credential_resolver: object | None,
    cancel_check: asyncio.Event | None = None,
    on_item_complete: Callable[[ForEachFrame], Awaitable[None]] | None = None,
) -> ForEachFrame:
    """Execute pending items in a for-each frame with bounded concurrency.

    ``on_item_complete`` — when provided — is awaited after each item reaches a
    terminal status (success/failure/skipped), under the frame lock, so the
    caller can checkpoint mid-frame progress. This makes a crashed fan-out
    resumable: already-completed items are skipped on the next
    ``run_foreach_frame`` call because their ``item_status`` is no longer
    ``pending``.
    """
    if frame.completed:
        return frame

    semaphore = asyncio.Semaphore(frame.concurrency)
    fail_fast_triggered = asyncio.Event()
    lock = asyncio.Lock()

    async def _mark(item_key: str, status: ItemStatus) -> None:
        frame.item_status[item_key] = status
        frame.next_completion_seq += 1
        frame.completion_seq[item_key] = frame.next_completion_seq

    async def run_one(envelope: dict[str, JsonValue]) -> None:
        item_key = str(envelope["item_key"])
        if frame.item_status.get(item_key) not in (None, "pending"):
            return
        if fail_fast_triggered.is_set():
            async with lock:
                await _mark(item_key, "skipped")
                if on_item_complete is not None:
                    await on_item_complete(frame)
            return

        async with semaphore:
            if fail_fast_triggered.is_set():
                async with lock:
                    await _mark(item_key, "skipped")
                    if on_item_complete is not None:
                        await on_item_complete(frame)
                return
            if cancel_check is not None and cancel_check.is_set():
                async with lock:
                    await _mark(item_key, "skipped")
                    if on_item_complete is not None:
                        await on_item_complete(frame)
                return

            try:
                value = await asyncio.wait_for(
                    _execute_item_body(
                        workflow=workflow,
                        registry=registry,
                        frame=frame,
                        envelope=envelope,
                        global_state=state,
                        run_id=run_id,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        credential_resolver=credential_resolver,
                        cancel_check=(
                            (lambda: cancel_check.is_set())
                            if cancel_check is not None
                            else None
                        ),
                    ),
                    timeout=frame.item_timeout_seconds,
                )
                async with lock:
                    frame.item_results[item_key] = value
                    await _mark(item_key, "success")
                    if on_item_complete is not None:
                        await on_item_complete(frame)
            except Exception as exc:
                async with lock:
                    frame.item_errors[item_key] = str(exc)
                    await _mark(item_key, "failure")
                    if frame.failure_policy == "fail_fast":
                        fail_fast_triggered.set()
                    if on_item_complete is not None:
                        await on_item_complete(frame)

    pending = [
        envelope
        for envelope in frame.envelopes
        if frame.item_status.get(str(envelope.get("item_key", "")), "pending") == "pending"
    ]
    tasks = [asyncio.create_task(run_one(envelope)) for envelope in pending]
    if tasks:
        await asyncio.gather(*tasks)

    if frame.failure_policy == "fail_fast" and fail_fast_triggered.is_set():
        for envelope in frame.envelopes:
            item_key = str(envelope.get("item_key", ""))
            if frame.item_status.get(item_key, "pending") == "pending":
                await _mark(item_key, "skipped")

    frame.completed = True
    inject = state.runtime.setdefault(COLLECT_INJECT_KEY, {})
    if not isinstance(inject, dict):
        inject = {}
        state.runtime[COLLECT_INJECT_KEY] = inject
    inject[frame.collect_node_id] = frame.collect_items()
    return frame


def build_frame_from_outputs(
    *,
    workflow: WorkflowDefinition,
    for_each_node_id: str,
    node_config: dict[str, JsonValue],
    outputs: dict[str, JsonValue],
    outgoing: dict[str, dict[str, list[WorkflowEdge]]],
    max_parallel_nodes: int,
) -> ForEachFrame | None:
    """Create a for-each frame after the control node executes."""
    body_nodes, body_entries, collect_id = detect_foreach_region(
        workflow,
        for_each_node_id=for_each_node_id,
        outgoing=outgoing,
    )
    if collect_id is None:
        return None

    raw_envelopes = outputs.get("item")
    if not isinstance(raw_envelopes, list):
        return None

    envelopes = [e for e in raw_envelopes if isinstance(e, dict)]
    concurrency = node_config.get("concurrency", 1)
    if not isinstance(concurrency, int):
        concurrency = 1
    effective_concurrency = min(concurrency, max_parallel_nodes)

    failure_policy = node_config.get("failure_policy", "continue")
    if failure_policy not in {"fail_fast", "continue"}:
        failure_policy = "continue"

    ordering = node_config.get("ordering", "preserve_input")
    if ordering not in {"preserve_input", "completion_order"}:
        ordering = "preserve_input"

    timeout = node_config.get("item_timeout_seconds", 60)
    if not isinstance(timeout, int):
        timeout = 60

    return ForEachFrame(
        for_each_node_id=for_each_node_id,
        collect_node_id=collect_id,
        body_node_ids=body_nodes,
        body_entry_ids=body_entries,
        envelopes=envelopes,
        concurrency=effective_concurrency,
        item_timeout_seconds=timeout,
        failure_policy=failure_policy,
        ordering=ordering,
    )
