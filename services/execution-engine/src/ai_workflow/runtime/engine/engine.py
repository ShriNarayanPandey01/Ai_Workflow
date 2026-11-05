from __future__ import annotations

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
from ai_workflow.nodes.base import TransientNodeError
from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.runtime.control.foreach import ForEachRuntime
from ai_workflow.runtime.engine.dispatch import (
    CollectInjectHandler,
    DurableTaskHandler,
    ForEachAfterHandler,
    InlineNodeHandler,
)
from ai_workflow.runtime.engine.invoke import NodeInvoker, RetryingNodeInvoker
from ai_workflow.runtime.graph.interrupt import WorkflowInterrupt
from ai_workflow.runtime.graph.ir import WorkflowIRCache, get_workflow_ir
from ai_workflow.runtime.graph.keys import RuntimeKeys
from ai_workflow.runtime.graph.scheduler import (
    DEFINITION_KEY,
    SchedulerSnapshot,
    clear_interrupt,
    get_interrupt,
    load_scheduler,
    save_interrupt,
    save_scheduler,
)
from ai_workflow.runtime.graph.state import WorkflowState
from ai_workflow.runtime.persistence.checkpoint import (
    DEFINITION_HASH_KEY,
    Checkpointer,
    InMemoryCheckpointer,
)
from ai_workflow.runtime.persistence.definition_store import DefinitionStore
from ai_workflow.runtime.registry import RuntimeRegistry
from ai_workflow.runtime.semantics.bindings import bindings_for_node, resolve_available_inputs
from ai_workflow.runtime.semantics.outputs import NodeOutputError
from ai_workflow.runtime.semantics.validator import (
    CatalogSemanticValidator,
    SemanticValidationError,
    SemanticValidator,
    validate_workflow_semantics,
)
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


def _enqueue_if_ready(
    node_id: str,
    *,
    workflow: WorkflowDefinition,
    nodes_by_id: dict[str, WorkflowNode],
    scheduler: SchedulerSnapshot,
    state: WorkflowState | None,
) -> None:
    """Enqueue a node when its required inputs (and collect inject) are ready."""
    if node_id in scheduler.in_pending:
        return
    node = nodes_by_id[node_id]
    if node.type == "control.collect@1" and (
        state is None or not state.collect_is_ready(node.type, node_id)
    ):
        return
    incoming = workflow.incoming_edges(node.id)
    if _is_ready(node, incoming, scheduler.produced):
        scheduler.enqueue_if_absent(node_id)


def _resolve_scope_ids(
    *,
    workflow: WorkflowDefinition,
    state: WorkflowState,
    workspace_id: UUID | None,
    project_id: UUID | None,
) -> tuple[UUID, UUID]:
    resolved_workspace = workspace_id
    resolved_project = project_id
    if resolved_workspace is None:
        raw_workspace = state.runtime.get(RuntimeKeys.WORKSPACE_ID)
        resolved_workspace = (
            UUID(str(raw_workspace)) if raw_workspace is not None else workflow.workflow_id
        )
    if resolved_project is None:
        raw_project = state.runtime.get(RuntimeKeys.PROJECT_ID)
        resolved_project = (
            UUID(str(raw_project)) if raw_project is not None else workflow.workflow_id
        )
    return resolved_workspace, resolved_project


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
    node_invoker: NodeInvoker | None = None,
    semantic: SemanticValidator | None = None,
    foreach_runtime: ForEachRuntime | None = None,
) -> WorkflowRunOutcome:
    """Run the workflow graph until a terminal outcome is reached.

    Pops ready nodes from ``scheduler.pending``, resolves their inputs,
    executes the registered node executor, enqueues downstream nodes when
    all required inputs are produced, then checkpoints so a crash can
    resume from the next pending node.

    Returns:
        WorkflowRunCompleted when exactly one ``data.output@1`` node runs.
        WorkflowRunWaiting when a node raises WorkflowInterrupt.
        WorkflowRunCancelled when cancel_registry signals cancellation.

    Raises:
        WorkflowRunError: On executor failure, missing registration, output
            contract violation, or exceeding max_node_executions.
    """
    def try_enqueue(node_id: str) -> None:
        _enqueue_if_ready(
            node_id,
            workflow=workflow,
            nodes_by_id=nodes_by_id,
            scheduler=scheduler,
            state=state,
        )

    async def is_cancelled() -> str | None:
        if cancel_registry is None:
            return None
        request = await cancel_registry.is_cancelled(run_id)
        return request.reason if request is not None else None

    resolved_workspace_id, resolved_project_id = _resolve_scope_ids(
        workflow=workflow,
        state=state,
        workspace_id=workspace_id,
        project_id=project_id,
    )

    invoker = node_invoker or RetryingNodeInvoker()
    validator = semantic or CatalogSemanticValidator(contracts_root=DEFAULT_CONTRACTS_ROOT)
    foreach = foreach_runtime or ForEachRuntime(node_invoker=invoker)
    collect_handler = CollectInjectHandler()
    durable_handler = DurableTaskHandler()
    inline_handler = InlineNodeHandler(invoker, validator)
    foreach_handler = ForEachAfterHandler(foreach)

    cancel_reason = await foreach.resume_incomplete(
        workflow=workflow,
        registry=registry,
        outgoing=outgoing,
        nodes_by_id=nodes_by_id,
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
        deadline=deadline,
    )
    if cancel_reason is not None:
        return WorkflowRunCancelled(run_id=run_id, reason=cancel_reason, state=state)

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

        node_id = scheduler.dequeue()
        if node_id is None:
            break
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
        inputs = collect_handler.apply(node, inputs, state)

        if registry.is_durable_task(node.type):
            if task_dispatcher is None:
                msg = f"Durable task node {node.type} requires a task dispatcher"
                raise WorkflowRunError(msg)
            return await durable_handler.run(
                node=node,
                inputs=inputs,
                workflow=workflow,
                run_id=run_id,
                state=state,
                scheduler=scheduler,
                checkpointer=checkpointer,
                max_payload_bytes=max_payload_bytes,
                task_dispatcher=task_dispatcher,
                checkpoint_state=_checkpoint_state,
                waiting_factory=WorkflowRunWaiting,
            )

        try:
            registration = registry.get_node(node.type)
        except KeyError as exc:
            msg = f"No executor registered for node type {node.type}"
            raise WorkflowRunError(msg) from exc

        runtime = inline_handler.build_runtime(state)

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

        if hooks is not None:
            await hooks.on_node_started(node_id=node.id, node_type=node.type)

        retry_policy = workflow.execution_policy.default_retry
        max_attempts = max(1, retry_policy.max_attempts)
        context_factory = inline_handler.context_factory(
            node=node,
            workflow=workflow,
            run_id=run_id,
            workspace_id=resolved_workspace_id,
            project_id=resolved_project_id,
            deadline=deadline,
            runtime=runtime,
            credential_resolver=credential_resolver,
            cancel_registry=cancel_registry,
        )

        try:
            result, context = await inline_handler.invoke(
                registration=registration,
                node=node,
                inputs=inputs,
                retry=retry_policy,
                context_factory=context_factory,
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

        loop_counters = context.runtime.get(RuntimeKeys.LOOP_ITERATIONS)
        if isinstance(loop_counters, dict):
            state.merge_loop_iterations(loop_counters)

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
        state.record_node_outputs(node_id, dict(result.outputs))
        scheduler.mark_produced(node_id, result.outputs)
        if node.type == "data.output@1":
            scheduler.record_output_node(node_id)

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

        for port in result.outputs:
            if node.type == "control.for-each@1" and port == "item":
                continue
            for edge in outgoing.get(node_id, {}).get(port, []):
                try_enqueue(str(edge.target_node_id))

        await _checkpoint_state(
            checkpointer=checkpointer,
            run_id=run_id,
            state=state,
            scheduler=scheduler,
            max_payload_bytes=max_payload_bytes,
        )

        if foreach_handler.matches(node):
            try:
                cancel_reason = await foreach_handler.run(
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
                    deadline=deadline,
                )
            except Exception as exc:
                msg = f"For-each subflow failed for node {node.id}: {exc}"
                if hooks is not None:
                    await hooks.on_node_failed(
                        node_id=node.id, node_type=node.type, error=str(exc)
                    )
                raise WorkflowRunError(msg) from exc
            if cancel_reason is not None:
                return WorkflowRunCancelled(
                    run_id=run_id, reason=cancel_reason, state=state
                )

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

    for node_id in nodes_by_id:
        _enqueue_if_ready(
            node_id,
            workflow=workflow,
            nodes_by_id=nodes_by_id,
            scheduler=scheduler,
            state=state,
        )
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
    node_invoker: NodeInvoker | None = None,
    semantic: SemanticValidator | None = None,
    foreach_runtime: ForEachRuntime | None = None,
    ir_cache: WorkflowIRCache | None = None,
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
    validator = semantic or CatalogSemanticValidator(
        contracts_root=contracts_root,
        max_loop_iterations=max_loop_iterations,
    )
    try:
        validator.validate(workflow)
    except SemanticValidationError as exc:
        raise WorkflowRunError(str(exc)) from exc

    document = workflow.model_dump(mode="json", exclude_none=True)
    ir = ir_cache.get(workflow) if ir_cache is not None else get_workflow_ir(workflow)
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
        RuntimeKeys.MAX_FAN_OUT_ITEMS: min(
            workflow.execution_policy.max_fan_out_items,
            max_fan_out_items,
        ),
        RuntimeKeys.DEADLINE: deadline.isoformat(),
    }
    if workspace_id is not None:
        runtime_payload[RuntimeKeys.WORKSPACE_ID] = str(workspace_id)
    if project_id is not None:
        runtime_payload[RuntimeKeys.PROJECT_ID] = str(project_id)
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
        node_invoker=node_invoker,
        semantic=validator,
        foreach_runtime=foreach_runtime,
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
    raw_deadline = state.runtime.get(RuntimeKeys.DEADLINE)
    deadline = None
    if isinstance(raw_deadline, str):
        deadline = datetime.fromisoformat(raw_deadline)
    raw_workspace = state.runtime.get(RuntimeKeys.WORKSPACE_ID)
    raw_project = state.runtime.get(RuntimeKeys.PROJECT_ID)
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
    max_node_executions_cap: int = 10_000,
    max_parallel_nodes_cap: int = 32,
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

    state.record_node_outputs(node_id, outputs)
    scheduler.mark_produced(node_id, outputs)
    scheduler.node_executions += 1
    clear_interrupt(state)

    ir = get_workflow_ir(workflow)

    for port in outputs:
        for edge in ir.outgoing.get(node_id, {}).get(port, []):
            _enqueue_if_ready(
                str(edge.target_node_id),
                workflow=workflow,
                nodes_by_id=ir.nodes_by_id,
                scheduler=scheduler,
                state=state,
            )

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
        task_dispatcher=task_dispatcher,
        max_parallel_nodes=min(
            workflow.execution_policy.max_parallel_nodes,
            max_parallel_nodes_cap,
        ),
    )


class WorkflowEngine:
    """Injectable workflow walker. Facades construct a default instance."""

    def __init__(
        self,
        *,
        registry: RuntimeRegistry | None = None,
        checkpointer: Checkpointer | None = None,
        semantic: SemanticValidator | None = None,
        node_invoker: NodeInvoker | None = None,
        ir_cache: WorkflowIRCache | None = None,
        foreach_runtime: ForEachRuntime | None = None,
        task_dispatcher: TaskDispatcher | None = None,
        cancel_registry: CancelRegistry | None = None,
        definition_store: DefinitionStore | None = None,
        hooks: WorkflowRunHooks | None = None,
    ) -> None:
        self._registry = registry
        self._checkpointer = checkpointer
        self._semantic = semantic
        self._node_invoker = node_invoker or RetryingNodeInvoker()
        self._ir_cache = ir_cache
        self._foreach = foreach_runtime or ForEachRuntime(node_invoker=self._node_invoker)
        self._task_dispatcher = task_dispatcher
        self._cancel_registry = cancel_registry
        self._definition_store = definition_store
        self._hooks = hooks

    async def run(self, definition, run_input, **kwargs):
        registry = kwargs.pop("registry", None) or self._registry
        if registry is None:
            msg = "WorkflowEngine requires a registry"
            raise WorkflowRunError(msg)
        return await run_workflow(
            definition,
            run_input,
            registry=registry,
            checkpointer=kwargs.pop("checkpointer", self._checkpointer),
            hooks=kwargs.pop("hooks", self._hooks),
            cancel_registry=kwargs.pop("cancel_registry", self._cancel_registry),
            task_dispatcher=kwargs.pop("task_dispatcher", self._task_dispatcher),
            definition_store=kwargs.pop("definition_store", self._definition_store),
            node_invoker=kwargs.pop("node_invoker", self._node_invoker),
            semantic=kwargs.pop("semantic", self._semantic),
            foreach_runtime=kwargs.pop("foreach_runtime", self._foreach),
            ir_cache=kwargs.pop("ir_cache", self._ir_cache),
            **kwargs,
        )

