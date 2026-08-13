from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4

from ai_workflow.config.settings import DEFAULT_CONTRACTS_ROOT
from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.contracts.workflow.definition import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    validate_definition_document,
    workflow_from_dict,
)
from ai_workflow.nodes.base import ExecutionContext, TransientNodeError
from ai_workflow.runtime.bindings import (
    bindings_for_node,
    resolve_available_inputs,
)
from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.runtime.checkpoint import (
    DEFINITION_HASH_KEY,
    Checkpointer,
    InMemoryCheckpointer,
)
from ai_workflow.runtime.control_flow import collect_is_ready, handle_foreach_after_execute
from ai_workflow.runtime.definition_store import DefinitionStore
from ai_workflow.runtime.execute_node import execute_with_retry
from ai_workflow.runtime.for_each_runtime import COLLECT_INJECT_KEY
from ai_workflow.runtime.interrupt import WorkflowInterrupt
from ai_workflow.runtime.outputs import NodeOutputError
from ai_workflow.runtime.registry import RuntimeRegistry
from ai_workflow.runtime.scheduler_state import (
    DEFINITION_KEY,
    SchedulerSnapshot,
    clear_interrupt,
    get_interrupt,
    load_scheduler,
    save_interrupt,
    save_scheduler,
)
from ai_workflow.runtime.semantic import (
    SemanticValidationError,
    build_state_root,
    validate_workflow_semantics,
)
from ai_workflow.runtime.state import WorkflowState
from ai_workflow.runtime.workflow_ir import get_workflow_ir
from ai_workflow.security.credentials import CredentialResolver
from ai_workflow.security.redaction import enforce_payload_limit, redact_state_snapshot


class WorkflowRunError(RuntimeError):
    """Raised when an in-process workflow run fails."""


class WorkflowRunTimedOut(WorkflowRunError):
    """Raised when a run exceeds its deadline."""


class ResumeValidationError(WorkflowRunError):
    """Raised when a resume command does not match the waiting interrupt."""


class WorkflowRunHooks(Protocol):
    """Callbacks invoked as nodes start, complete, or fail during a run."""

    async def on_node_started(self, *, node_id: UUID, node_type: str) -> None: ...

    async def on_node_completed(
        self,
        *,
        node_id: UUID,
        node_type: str,
        outputs: dict[str, JsonValue],
    ) -> None: ...

    async def on_node_failed(self, *, node_id: UUID, node_type: str, error: str) -> None: ...


class TaskDispatcher(Protocol):
    """Publishes task.start for durable-task nodes (F15)."""

    async def start_task(
        self,
        *,
        run_id: UUID,
        node_id: UUID,
        task_type: str,
        payload: dict[str, JsonValue],
        credential_refs: dict[str, UUID],
        resource_refs: dict[str, UUID],
        budgets: dict[str, JsonValue],
        task_id: UUID | None = None,
    ) -> UUID: ...


@dataclass(frozen=True, slots=True)
class WorkflowRunCompleted:
    """Workflow finished successfully with a single output value."""

    run_id: UUID
    output: JsonValue
    state: WorkflowState


@dataclass(frozen=True, slots=True)
class WorkflowRunWaiting:
    """Workflow paused until an external human or task decision arrives."""

    run_id: UUID
    interrupt_id: UUID
    waiting_reason: Literal["HUMAN", "TASK"]
    state: WorkflowState
    node_id: UUID
    approval_request: dict[str, JsonValue] | None
    approval_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class WorkflowRunCancelled:
    """Workflow stopped cooperatively after a cancel request."""

    run_id: UUID
    reason: str
    state: WorkflowState


WorkflowRunOutcome = WorkflowRunCompleted | WorkflowRunWaiting | WorkflowRunCancelled

# Backward-compatible alias used by existing tests.
WorkflowRunResult = WorkflowRunCompleted


async def _persist_canonical_definition(
    store: DefinitionStore | None,
    workflow: WorkflowDefinition,
) -> None:
    """Store the same document the IR hashes so resume can load by definition_hash."""
    if store is None:
        return
    document = workflow.model_dump(mode="json", exclude_none=True)
    await store.put(document)


def _parse_definition(
    definition: WorkflowDefinition | dict[str, JsonValue],
    *,
    contracts_root: Path,
) -> WorkflowDefinition:
    """Normalize and validate a workflow definition before execution."""
    if isinstance(definition, WorkflowDefinition):
        return definition
    validate_definition_document(definition, contracts_root=contracts_root, source="workflow")
    return workflow_from_dict(definition)


def _outgoing_by_port(
    definition: WorkflowDefinition,
) -> dict[str, dict[str, list[WorkflowEdge]]]:
    """Index workflow edges by source node id and source port."""
    result: dict[str, dict[str, list[WorkflowEdge]]] = defaultdict(lambda: defaultdict(list))
    for edge in definition.edges:
        result[str(edge.source_node_id)][edge.source_port].append(edge)
    return result


def _is_ready(
    node: WorkflowNode,
    incoming: list[WorkflowEdge],
    produced: set[tuple[str, str]],
) -> bool:
    """Return whether every required incoming port has a produced source value."""
    if not incoming:
        return True
    by_port: dict[str, list[WorkflowEdge]] = defaultdict(list)
    for edge in incoming:
        by_port[edge.target_port].append(edge)
    for edges in by_port.values():
        if not any(
            (str(edge.source_node_id), edge.source_port) in produced for edge in edges
        ):
            return False
    return True


def _validate_human_decision(decision: JsonValue) -> dict[str, JsonValue]:
    """Ensure a resume decision payload is a JSON object."""
    if not isinstance(decision, dict):
        msg = "Resume decision must be a JSON object"
        raise ResumeValidationError(msg)
    return decision


def _apply_human_resume_outputs(
    node_type: str,
    decision: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Validate a human resume decision and map it to node output ports."""
    if node_type == "human.approval@1":
        approved = decision.get("decision")
        if approved not in ("approved", "rejected"):
            msg = "Approval resume requires decision.decision of approved or rejected"
            raise ResumeValidationError(msg)
        output: dict[str, JsonValue] = {"decision": approved}
        if "data" in decision:
            output["data"] = decision["data"]
        return {"decision": output}

    if node_type == "human.review@1":
        if "value" not in decision:
            msg = "Review resume requires decision.value"
            raise ResumeValidationError(msg)
        return {"value": decision["value"]}

    msg = f"Unsupported human node type for resume: {node_type}"
    raise ResumeValidationError(msg)


def _apply_task_resume_outputs(
    node_type: str,
    decision: JsonValue,
) -> dict[str, JsonValue]:
    """Map a durable-task result onto the waiting node's output ports."""
    if not isinstance(decision, dict):
        msg = "TASK resume decision must be a JSON object"
        raise ResumeValidationError(msg)
    if node_type == "research.deep-research@1":
        if "report" in decision:
            return {"report": decision["report"]}
        return {"report": decision}
    if node_type in {"action.cleanup-plan@1"}:
        if "plan" in decision:
            return {"plan": decision["plan"]}
        return {"plan": decision}
    if node_type == "action.cleanup-execute@1":
        if "result" in decision:
            return {"result": decision["result"]}
        return {"result": decision}
    return dict(decision)


async def _checkpoint_state(
    *,
    checkpointer: Checkpointer,
    run_id: UUID,
    state: WorkflowState,
    scheduler: SchedulerSnapshot,
    max_payload_bytes: int,
) -> None:
    """Serialize and persist workflow + scheduler state to the checkpointer.

    Embeds the scheduler snapshot into ``state.runtime``, deep-copies the
    state, validates the redacted snapshot size, then saves under ``run_id``
    (``thread_id`` equals ``run_id``).
    """
    save_scheduler(state, scheduler)
    snapshot = state.snapshot()
    redacted = redact_state_snapshot(snapshot)
    enforce_payload_limit(redacted, max_payload_bytes)
    await checkpointer.save(thread_id=run_id, state=snapshot)


def _collect_inject_ready(node: WorkflowNode, state: WorkflowState | None) -> bool:
    """Return whether a collect node may run (runtime item injection present)."""
    return collect_is_ready(node, state)


async def _sleep_backoff(backoff_ms: int, *, jitter: bool) -> None:
    """Sleep for the backoff interval, optionally applying jitter.

    Jitter is derived from the event-loop clock rather than a PRNG so the
    runner stays free of ``random`` (disallowed in some sandboxes) while
    still spreading retries across the window.
    """
    delay = max(0.0, backoff_ms / 1000.0)
    if jitter and delay > 0:
        frac = asyncio.get_event_loop().time() % 1.0
        delay = delay * (0.5 + 0.5 * frac)
    if delay > 0:
        await asyncio.sleep(delay)


async def _execute_loop(
    *,
    workflow: WorkflowDefinition,
    registry: RuntimeRegistry,
    run_id: UUID,
    state: WorkflowState,
    scheduler: SchedulerSnapshot,
    checkpointer: Checkpointer,
    hooks: WorkflowRunHooks | None,
    outgoing: dict[str, dict[str, list[WorkflowEdge]]],
    nodes_by_id: dict[str, WorkflowNode],
    max_node_executions: int,
    max_payload_bytes: int,
    cancel_registry: CancelRegistry | None,
    credential_resolver: CredentialResolver | None,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
    deadline: datetime | None = None,
    task_dispatcher: TaskDispatcher | None = None,
    max_parallel_nodes: int = 32,
) -> WorkflowRunOutcome:
    """Run the workflow graph until a terminal outcome is reached.

    Pops ready nodes from ``scheduler.pending``, resolves their inputs,
    executes the registered node executor, checkpoints state after every
    step, and enqueues downstream nodes when all required inputs are
    produced.

    Returns:
        WorkflowRunCompleted when exactly one ``data.output@1`` node runs.
        WorkflowRunWaiting when a node raises WorkflowInterrupt.
        WorkflowRunCancelled when cancel_registry signals cancellation.

    Raises:
        WorkflowRunError: On executor failure, missing registration, output
            contract violation, or exceeding max_node_executions.
    """
    def try_enqueue(node_id: str) -> None:
        if node_id in scheduler.in_pending:
            return
        node = nodes_by_id[node_id]
        if not _collect_inject_ready(node, state):
            return
        incoming = workflow.incoming_edges(node.id)
        if _is_ready(node, incoming, scheduler.produced):
            scheduler.pending.append(node_id)
            scheduler.in_pending.add(node_id)

    async def  is_cancelled() -> str | None:
        if cancel_registry is None:
            return None
        request = await cancel_registry.is_cancelled(run_id)
        return request.reason if request is not None else None

    while scheduler.pending:
        cancel_reason = await is_cancelled()
        if cancel_reason is not None:
            await _checkpoint_state(
                checkpointer=checkpointer,
                run_id=run_id,
                state=state,
                scheduler=scheduler,
                max_payload_bytes=max_payload_bytes,
            )
            return WorkflowRunCancelled(run_id=run_id, reason=cancel_reason, state=state)

        node_id = scheduler.pending.popleft()
        scheduler.in_pending.discard(node_id)
        node = nodes_by_id[node_id]

        if scheduler.node_executions >= max_node_executions:
            msg = f"Exceeded max_node_executions ({max_node_executions})"
            raise WorkflowRunError(msg)

        if deadline is not None and datetime.now(UTC) >= deadline:
            raise WorkflowRunTimedOut("Run exceeded timeout_seconds")

        bindings = bindings_for_node(node, workflow.incoming_edges(node.id))
        inputs = resolve_available_inputs(
            bindings,
            state.node_outputs,
            production_order=scheduler.production_order,
        )
        inject_raw = state.runtime.get(COLLECT_INJECT_KEY)
        if (
            node.type == "control.collect@1"
            and isinstance(inject_raw, dict)
            and node_id in inject_raw
        ):
            inputs["items"] = inject_raw[node_id]

        if node.type in registry.tasks:
            if task_dispatcher is None:
                msg = f"Durable task node {node.type} requires a task dispatcher"
                raise WorkflowRunError(msg)
            task_id = uuid4()
            interrupt_id = uuid4()
            state.task_refs[str(node.id)] = str(task_id)
            save_interrupt(
                state,
                interrupt_id=str(interrupt_id),
                waiting_reason="TASK",
                node_id=str(node.id),
                approval_id=None,
                node_type=node.type,
                approval_request={"task_type": node.type},
                task_id=str(task_id),
            )
            await _checkpoint_state(
                checkpointer=checkpointer,
                run_id=run_id,
                state=state,
                scheduler=scheduler,
                max_payload_bytes=max_payload_bytes,
            )
            await task_dispatcher.start_task(
                run_id=run_id,
                node_id=node.id,
                task_type=node.type,
                payload=dict(inputs),
                credential_refs=dict(node.credential_refs),
                resource_refs=dict(node.resource_refs),
                budgets={
                    "max_seconds": workflow.execution_policy.max_task_seconds,
                    "max_items": 1,
                    "max_provider_calls": workflow.execution_policy.max_provider_calls,
                    "max_artifact_bytes": workflow.execution_policy.max_artifact_bytes,
                },
                task_id=task_id,
            )
            return WorkflowRunWaiting(
                run_id=run_id,
                interrupt_id=interrupt_id,
                waiting_reason="TASK",
                state=state,
                node_id=node.id,
                approval_request={"task_id": str(task_id), "task_type": node.type},
            )

        try:
            registration = registry.get_node(node.type)
        except KeyError as exc:
            msg = f"No executor registered for node type {node.type}"
            raise WorkflowRunError(msg) from exc

        state_root = build_state_root(
            node_outputs=state.node_outputs,
            loop_iterations=state.loop_iterations,
            runtime=state.runtime,
        )
        runtime = dict(state.runtime)
        runtime["_state_root"] = state_root
        runtime["_loop_iterations"] = dict(state.loop_iterations)

        cancel_reason = await is_cancelled()
        if cancel_reason is not None:
            await _checkpoint_state(
                checkpointer=checkpointer,
                run_id=run_id,
                state=state,
                scheduler=scheduler,
                max_payload_bytes=max_payload_bytes,
            )
            return WorkflowRunCancelled(run_id=run_id, reason=cancel_reason, state=state)

        resolved_workspace_id = workspace_id
        resolved_project_id = project_id
        if resolved_workspace_id is None:
            raw_workspace = state.runtime.get("_workspace_id")
            resolved_workspace_id = (
                UUID(str(raw_workspace)) if raw_workspace is not None else workflow.workflow_id
            )
        if resolved_project_id is None:
            raw_project = state.runtime.get("_project_id")
            resolved_project_id = (
                UUID(str(raw_project)) if raw_project is not None else workflow.workflow_id
            )

        if hooks is not None:
            await hooks.on_node_started(node_id=node.id, node_type=node.type)

        retry_policy = workflow.execution_policy.default_retry
        max_attempts = max(1, retry_policy.max_attempts)

        def context_factory(attempt: int) -> ExecutionContext:
            return ExecutionContext(
                run_id=run_id,
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                workflow_version_id=workflow.workflow_version_id,
                node_id=node.id,
                attempt=attempt,
                deadline=deadline,
                idempotency_key=f"{run_id}:{node.id}",
                runtime=runtime,
                input_schema=workflow.input_schema,
                output_schema=workflow.output_schema,
                credential_refs=dict(node.credential_refs),
                resource_refs=dict(node.resource_refs),
                credential_resolver=credential_resolver,
                cancel_check=(
                    cancel_registry.cancel_check(run_id)
                    if cancel_registry is not None
                    else (lambda: False)
                ),
            )

        try:
            result, context = await execute_with_retry(
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
        except WorkflowInterrupt as interrupt:
            save_interrupt(
                state,
                interrupt_id=str(interrupt.interrupt_id),
                waiting_reason=interrupt.waiting_reason,
                node_id=str(interrupt.node_id),
                approval_id=str(interrupt.approval_id) if interrupt.approval_id else None,
                node_type=interrupt.node_type,
                approval_request=interrupt.approval_request,
                task_id=str(interrupt.task_id) if interrupt.task_id else None,
            )
            await _checkpoint_state(
                checkpointer=checkpointer,
                run_id=run_id,
                state=state,
                scheduler=scheduler,
                max_payload_bytes=max_payload_bytes,
            )
            return WorkflowRunWaiting(
                run_id=run_id,
                interrupt_id=interrupt.interrupt_id,
                waiting_reason=interrupt.waiting_reason,
                state=state,
                node_id=interrupt.node_id,
                approval_request=interrupt.approval_request,
                approval_id=interrupt.approval_id,
            )
        except TransientNodeError as exc:
            msg = (
                f"Node {node.id} ({node.type}) failed after {max_attempts} attempt(s): {exc}"
            )
            if hooks is not None:
                await hooks.on_node_failed(
                    node_id=node.id, node_type=node.type, error=str(exc)
                )
            raise WorkflowRunError(msg) from exc
        except NodeOutputError as exc:
            msg = f"Node {node.id} ({node.type}) failed: {exc}"
            if hooks is not None:
                await hooks.on_node_failed(node_id=node.id, node_type=node.type, error=str(exc))
            raise WorkflowRunError(msg) from exc
        except Exception as exc:
            msg = f"Node {node.id} ({node.type}) failed: {exc}"
            if hooks is not None:
                await hooks.on_node_failed(node_id=node.id, node_type=node.type, error=str(exc))
            raise WorkflowRunError(msg) from exc

        loop_counters = context.runtime.get("_loop_iterations")
        if isinstance(loop_counters, dict):
            for key, value in loop_counters.items():
                if isinstance(value, int):
                    state.loop_iterations[str(key)] = value

        cancel_reason = await is_cancelled()
        if cancel_reason is not None:
            await _checkpoint_state(
                checkpointer=checkpointer,
                run_id=run_id,
                state=state,
                scheduler=scheduler,
                max_payload_bytes=max_payload_bytes,
            )
            return WorkflowRunCancelled(run_id=run_id, reason=cancel_reason, state=state)

        scheduler.node_executions += 1

        scheduler.produced = {item for item in scheduler.produced if item[0] != node_id}
        for key in list(scheduler.production_order):
            if key[0] == node_id:
                del scheduler.production_order[key]
        state.node_outputs[node_id] = dict(result.outputs)

        for port in result.outputs:
            key = (node_id, port)
            scheduler.produced.add(key)
            scheduler.production_seq += 1
            scheduler.production_order[key] = scheduler.production_seq

        if node.type == "data.output@1":
            scheduler.executed_output_ids.add(node_id)

        if hooks is not None:
            await hooks.on_node_completed(
                node_id=node.id,
                node_type=node.type,
                outputs=result.outputs,
            )

        for key, value in context.runtime.items():
            if str(key).startswith("_"):
                continue
            state.runtime[key] = value

        await _checkpoint_state(
            checkpointer=checkpointer,
            run_id=run_id,
            state=state,
            scheduler=scheduler,
            max_payload_bytes=max_payload_bytes,
        )

        if node.type == "control.for-each@1":
            try:
                cancelled = await handle_foreach_after_execute(
                    workflow=workflow,
                    registry=registry,
                    node_id=node_id,
                    node=node,
                    result=result,
                    outgoing=outgoing,
                    state=state,
                    scheduler=scheduler,
                    checkpointer=checkpointer,
                    run_id=run_id,
                    workspace_id=resolved_workspace_id,
                    project_id=resolved_project_id,
                    credential_resolver=credential_resolver,
                    cancel_registry=cancel_registry,
                    max_payload_bytes=max_payload_bytes,
                    max_parallel_nodes=min(
                        workflow.execution_policy.max_parallel_nodes,
                        max_parallel_nodes,
                    ),
                    try_enqueue=try_enqueue,
                    checkpoint_state=_checkpoint_state,
                    is_cancelled=is_cancelled,
                    hooks=hooks,
                    cancelled_factory=WorkflowRunCancelled,
                )
            except RuntimeError as exc:
                raise WorkflowRunError(str(exc)) from exc
            if cancelled is not None:
                return cancelled

        for port in result.outputs:
            if node.type == "control.for-each@1" and port == "item":
                continue
            for edge in outgoing.get(node_id, {}).get(port, []):
                try_enqueue(str(edge.target_node_id))

    if len(scheduler.executed_output_ids) != 1:
        msg = (
            "Workflow must execute exactly one data.output@1 node; "
            f"executed {sorted(scheduler.executed_output_ids)}"
        )
        raise WorkflowRunError(msg)

    output_node_id = next(iter(scheduler.executed_output_ids))
    output_ports = state.node_outputs.get(output_node_id, {})
    if "value" not in output_ports:
        msg = "Workflow did not produce an output value"
        raise WorkflowRunError(msg)

    output = output_ports["value"]
    enforce_payload_limit(output, max_payload_bytes)
    return WorkflowRunCompleted(run_id=run_id, output=output, state=state)


def _init_scheduler(
    workflow: WorkflowDefinition,
    *,
    nodes_by_id: dict[str, WorkflowNode],
    produced: set[tuple[str, str]] | None = None,
    state: WorkflowState | None = None,
) -> SchedulerSnapshot:
    """Create an initial scheduler snapshot with ready nodes enqueued."""
    scheduler = SchedulerSnapshot()
    if produced is not None:
        scheduler.produced = set(produced)

    def try_enqueue(node_id: str) -> None:
        if node_id in scheduler.in_pending:
            return
        node = nodes_by_id[node_id]
        if not _collect_inject_ready(node, state):
            return
        incoming = workflow.incoming_edges(node.id)
        if _is_ready(node, incoming, scheduler.produced):
            scheduler.pending.append(node_id)
            scheduler.in_pending.add(node_id)

    for node_id in nodes_by_id:
        try_enqueue(node_id)
    return scheduler


async def run_workflow(
    definition: WorkflowDefinition | dict[str, JsonValue],
    run_input: dict[str, JsonValue],
    *,
    registry: RuntimeRegistry,
    run_id: UUID | None = None,
    checkpointer: Checkpointer | None = None,
    hooks: WorkflowRunHooks | None = None,
    contracts_root: Path = DEFAULT_CONTRACTS_ROOT,
    max_payload_bytes: int = 1_048_576,
    max_loop_iterations: int = 100,
    max_fan_out_items: int = 1000,
    max_node_executions_cap: int = 10_000,
    max_parallel_nodes_cap: int = 32,
    max_run_seconds: int = 300,
    cancel_registry: CancelRegistry | None = None,
    credential_resolver: CredentialResolver | None = None,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
    task_dispatcher: TaskDispatcher | None = None,
    definition_store: DefinitionStore | None = None,
) -> WorkflowRunOutcome:
    """Start a fresh workflow run from the given input.

    Validates the definition (schema + semantics), seeds runtime state with
    ``run_input`` and the serialized definition, initializes the scheduler,
    and delegates to ``_execute_loop``.

    Args:
        definition: Parsed or raw workflow definition document.
        run_input: Workflow input payload passed to ``data.input@1``.
        registry: Node executors keyed by catalog node type.
        run_id: Stable run identifier; generated when omitted.
        checkpointer: Persistence backend; defaults to in-memory.
        hooks: Optional lifecycle callbacks for node events.
        contracts_root: Root of JSON Schema contract files.
        max_payload_bytes: Upper bound on input/output/checkpoint size.
        max_loop_iterations: Platform cap for ``control.loop@1`` nodes.
        cancel_registry: Optional cooperative cancellation source.
        credential_resolver: Resolves credential slots for AI nodes.
        workspace_id: Tenant workspace from the command envelope.
        project_id: Tenant project from the command envelope.

    Returns:
        One of WorkflowRunCompleted, WorkflowRunWaiting, or
        WorkflowRunCancelled depending on how execution ends.
    """
    workflow = _parse_definition(definition, contracts_root=contracts_root)
    try:
        validate_workflow_semantics(
            workflow,
            contracts_root=contracts_root,
            max_loop_iterations=max_loop_iterations,
        )
    except SemanticValidationError as exc:
        raise WorkflowRunError(str(exc)) from exc

    document = workflow.model_dump(mode="json", exclude_none=True)
    ir = get_workflow_ir(workflow)
    await _persist_canonical_definition(definition_store, workflow)
    resolved_run_id = run_id or uuid4()
    checkpoint_store = checkpointer or InMemoryCheckpointer()

    enforce_payload_limit(run_input, max_payload_bytes)

    timeout_seconds = min(workflow.execution_policy.timeout_seconds, max_run_seconds)
    deadline = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
    max_node_executions = min(
        workflow.execution_policy.max_node_executions,
        max_node_executions_cap,
    )
    max_parallel_nodes = min(
        workflow.execution_policy.max_parallel_nodes,
        max_parallel_nodes_cap,
    )

    runtime_payload: dict[str, JsonValue] = {
        "run_input": run_input,
        DEFINITION_KEY: document,
        DEFINITION_HASH_KEY: ir.definition_hash,
        "_max_fan_out_items": min(
            workflow.execution_policy.max_fan_out_items,
            max_fan_out_items,
        ),
        "_deadline": deadline.isoformat(),
    }
    if workspace_id is not None:
        runtime_payload["_workspace_id"] = str(workspace_id)
    if project_id is not None:
        runtime_payload["_project_id"] = str(project_id)
    state = WorkflowState(runtime=runtime_payload)
    scheduler = _init_scheduler(workflow, nodes_by_id=ir.nodes_by_id, state=state)

    return await _execute_loop(
        workflow=workflow,
        registry=registry,
        run_id=resolved_run_id,
        state=state,
        scheduler=scheduler,
        checkpointer=checkpoint_store,
        hooks=hooks,
        outgoing=ir.outgoing,
        nodes_by_id=ir.nodes_by_id,
        max_node_executions=max_node_executions,
        max_payload_bytes=max_payload_bytes,
        cancel_registry=cancel_registry,
        credential_resolver=credential_resolver,
        workspace_id=workspace_id,
        project_id=project_id,
        deadline=deadline,
        task_dispatcher=task_dispatcher,
        max_parallel_nodes=max_parallel_nodes,
    )


async def continue_workflow_from_checkpoint(
    definition: WorkflowDefinition | dict[str, JsonValue],
    *,
    run_id: UUID,
    registry: RuntimeRegistry,
    checkpointer: Checkpointer,
    hooks: WorkflowRunHooks | None = None,
    contracts_root: Path = DEFAULT_CONTRACTS_ROOT,
    max_payload_bytes: int = 1_048_576,
    max_loop_iterations: int = 100,
    max_fan_out_items: int = 1000,
    max_node_executions_cap: int = 10_000,
    max_parallel_nodes_cap: int = 32,
    cancel_registry: CancelRegistry | None = None,
    credential_resolver: CredentialResolver | None = None,
    task_dispatcher: TaskDispatcher | None = None,
    definition_store: DefinitionStore | None = None,
) -> WorkflowRunOutcome:
    """Continue a crashed or redelivered run from its last checkpoint.

    Used after worker crash or message redelivery when a checkpoint exists but
    the run is not in a waiting/interrupt state. Reloads scheduler snapshot
    from the checkpoint and continues from the pending queue.

    Raises:
        WorkflowRunError: When no checkpoint exists, scheduler state is
            missing, or the run is waiting for ``resume_workflow`` instead.
    """
    del max_fan_out_items
    workflow = _parse_definition(definition, contracts_root=contracts_root)
    try:
        validate_workflow_semantics(
            workflow,
            contracts_root=contracts_root,
            max_loop_iterations=max_loop_iterations,
        )
    except SemanticValidationError as exc:
        raise WorkflowRunError(str(exc)) from exc

    state = await checkpointer.load(thread_id=run_id)
    if state is None:
        msg = f"No checkpoint found for run_id={run_id}"
        raise WorkflowRunError(msg)

    if get_interrupt(state) is not None:
        msg = "Run is waiting for resume; use resume_workflow instead"
        raise WorkflowRunError(msg)

    scheduler = load_scheduler(state)
    if scheduler is None:
        msg = f"Checkpoint for run_id={run_id} has no scheduler state"
        raise WorkflowRunError(msg)

    ir = get_workflow_ir(workflow)
    await _persist_canonical_definition(definition_store, workflow)
    raw_deadline = state.runtime.get("_deadline")
    deadline = None
    if isinstance(raw_deadline, str):
        deadline = datetime.fromisoformat(raw_deadline)
    raw_workspace = state.runtime.get("_workspace_id")
    raw_project = state.runtime.get("_project_id")
    workspace_id = UUID(str(raw_workspace)) if raw_workspace is not None else None
    project_id = UUID(str(raw_project)) if raw_project is not None else None

    return await _execute_loop(
        workflow=workflow,
        registry=registry,
        run_id=run_id,
        state=state,
        scheduler=scheduler,
        checkpointer=checkpointer,
        hooks=hooks,
        outgoing=ir.outgoing,
        nodes_by_id=ir.nodes_by_id,
        max_node_executions=min(
            workflow.execution_policy.max_node_executions,
            max_node_executions_cap,
        ),
        max_payload_bytes=max_payload_bytes,
        cancel_registry=cancel_registry,
        credential_resolver=credential_resolver,
        workspace_id=workspace_id,
        project_id=project_id,
        deadline=deadline,
        task_dispatcher=task_dispatcher,
        max_parallel_nodes=min(
            workflow.execution_policy.max_parallel_nodes,
            max_parallel_nodes_cap,
        ),
    )


async def resume_workflow(
    *,
    run_id: UUID,
    waiting_reason: Literal["HUMAN", "TASK"],
    interrupt_id: UUID,
    approval_id: UUID | None,
    task_id: UUID | None,
    decision: JsonValue,
    definition: WorkflowDefinition | dict[str, JsonValue],
    registry: RuntimeRegistry,
    checkpointer: Checkpointer,
    hooks: WorkflowRunHooks | None = None,
    contracts_root: Path = DEFAULT_CONTRACTS_ROOT,
    max_payload_bytes: int = 1_048_576,
    max_loop_iterations: int = 100,
    max_fan_out_items: int = 1000,
    cancel_registry: CancelRegistry | None = None,
    credential_resolver: CredentialResolver | None = None,
    task_dispatcher: TaskDispatcher | None = None,
    definition_store: DefinitionStore | None = None,
) -> WorkflowRunOutcome:
    """Apply an external decision to a waiting interrupt and continue execution.

    Validates that ``interrupt_id``, ``waiting_reason``, and (for HUMAN)
    ``approval_id`` match the interrupt stored in the checkpoint. Maps the
    decision payload to the waiting node's output ports, clears the interrupt,
    enqueues downstream nodes, and re-enters ``_execute_loop``.

    Raises:
        ResumeValidationError: When identifiers do not match, the run is not
            waiting, or the decision shape is invalid for the node type.
    """
    workflow = _parse_definition(definition, contracts_root=contracts_root)
    await _persist_canonical_definition(definition_store, workflow)
    state = await checkpointer.load(thread_id=run_id)
    if state is None:
        msg = f"No checkpoint found for run_id={run_id}"
        raise ResumeValidationError(msg)

    interrupt = get_interrupt(state)
    if interrupt is None:
        msg = "Run is not in a waiting state"
        raise ResumeValidationError(msg)

    if cancel_registry is not None:
        cancel_request = await cancel_registry.is_cancelled(run_id)
        if cancel_request is not None:
            return WorkflowRunCancelled(
                run_id=run_id, reason=cancel_request.reason, state=state
            )

    if str(interrupt.get("interrupt_id")) != str(interrupt_id):
        msg = "interrupt_id does not match waiting interrupt"
        raise ResumeValidationError(msg)

    if interrupt.get("waiting_reason") != waiting_reason:
        msg = "waiting_reason does not match waiting interrupt"
        raise ResumeValidationError(msg)

    node_id = str(interrupt.get("node_id", ""))
    node_type = str(interrupt.get("node_type", ""))

    if waiting_reason == "HUMAN":
        if approval_id is None or str(interrupt.get("approval_id")) != str(approval_id):
            msg = "approval_id does not match waiting interrupt"
            raise ResumeValidationError(msg)
        if task_id is not None:
            msg = "task_id must be null for HUMAN resume"
            raise ResumeValidationError(msg)
        decision_obj = _validate_human_decision(decision)
        outputs = _apply_human_resume_outputs(node_type, decision_obj)
    else:
        if task_id is None or str(interrupt.get("task_id")) != str(task_id):
            msg = "task_id does not match waiting interrupt"
            raise ResumeValidationError(msg)
        if approval_id is not None:
            msg = "approval_id must be null for TASK resume"
            raise ResumeValidationError(msg)
        outputs = _apply_task_resume_outputs(node_type, decision)

    scheduler = load_scheduler(state)
    if scheduler is None:
        msg = "Waiting checkpoint has no scheduler state"
        raise ResumeValidationError(msg)

    scheduler.produced = {item for item in scheduler.produced if item[0] != node_id}
    for key in list(scheduler.production_order):
        if key[0] == node_id:
            del scheduler.production_order[key]

    state.node_outputs[node_id] = outputs
    for port in outputs:
        key = (node_id, port)
        scheduler.produced.add(key)
        scheduler.production_seq += 1
        scheduler.production_order[key] = scheduler.production_seq

    scheduler.node_executions += 1
    clear_interrupt(state)

    ir = get_workflow_ir(workflow)

    def try_enqueue(target_id: str) -> None:
        if target_id in scheduler.in_pending:
            return
        node = ir.nodes_by_id[target_id]
        incoming = workflow.incoming_edges(node.id)
        if _is_ready(node, incoming, scheduler.produced):
            scheduler.pending.append(target_id)
            scheduler.in_pending.add(target_id)

    for port in outputs:
        for edge in ir.outgoing.get(node_id, {}).get(port, []):
            try_enqueue(str(edge.target_node_id))

    return await _execute_loop(
        workflow=workflow,
        registry=registry,
        run_id=run_id,
        state=state,
        scheduler=scheduler,
        checkpointer=checkpointer,
        hooks=hooks,
        outgoing=ir.outgoing,
        nodes_by_id=ir.nodes_by_id,
        max_node_executions=min(
            workflow.execution_policy.max_node_executions,
            10_000,
        ),
        max_payload_bytes=max_payload_bytes,
        cancel_registry=cancel_registry,
        credential_resolver=credential_resolver,
        task_dispatcher=task_dispatcher,
        max_parallel_nodes=min(workflow.execution_policy.max_parallel_nodes, 32),
    )
