from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

import aio_pika
import asyncpg
import httpx

from ai_workflow.config.settings import Settings
from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.messaging.envelope import (
    parse_execution_cancel,
    parse_execution_resume,
    parse_execution_start,
)
from ai_workflow.messaging.inbox import ClaimResult, PostgresInbox
from ai_workflow.messaging.publisher import EventPublisher, publisher_hooks
from ai_workflow.messaging.validation import EnvelopeValidationError, validate_envelope_document
from ai_workflow.runtime.action_keys import PostgresActionKeyStore
from ai_workflow.runtime.bootstrap import build_runner_registry
from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.runtime.checkpoint import DEFINITION_HASH_KEY, PostgresCheckpointer
from ai_workflow.runtime.definition_store import PostgresDefinitionStore
from ai_workflow.runtime.lease import LeaseError, RunLeaseStore
from ai_workflow.runtime.registry import RuntimeRegistry
from ai_workflow.runtime.runner import (
    ResumeValidationError,
    WorkflowRunCancelled,
    WorkflowRunCompleted,
    WorkflowRunError,
    WorkflowRunTimedOut,
    WorkflowRunWaiting,
    continue_workflow_from_checkpoint,
    resume_workflow,
    run_workflow,
)
from ai_workflow.runtime.scheduler_state import DEFINITION_KEY, clear_interrupt, get_interrupt
from ai_workflow.security.credentials import CredentialResolver, build_credential_resolver
from ai_workflow.security.http_client import SafeHttpClient
from ai_workflow.security.redaction import redact_value
from ai_workflow.worker.task_dispatcher import RabbitTaskDispatcher

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


class MessageInFlightError(RuntimeError):
    """Raised when the same message is already being processed by another worker."""


class MessageNotReadyError(RuntimeError):
    """Raised when a task result arrived before the parent run is waiting."""


def _parse_envelope(body: bytes) -> dict[str, Any]:
    """Decode a RabbitMQ message body into a JSON envelope dict."""
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = "Invalid JSON payload"
        raise EnvelopeValidationError(msg) from exc
    if not isinstance(raw, dict):
        msg = "Envelope must be a JSON object"
        raise EnvelopeValidationError(msg)
    return raw


async def _publish_outcome(
    publisher: EventPublisher,
    outcome: WorkflowRunCompleted | WorkflowRunWaiting | WorkflowRunCancelled,
) -> None:
    """Publish the terminal or waiting event that matches a workflow run outcome."""
    if isinstance(outcome, WorkflowRunWaiting):
        await publisher.publish_execution_waiting(
            waiting_reason=outcome.waiting_reason,
            interrupt_id=outcome.interrupt_id,
            node_id=outcome.node_id,
            approval_request=outcome.approval_request,
        )
        return

    if isinstance(outcome, WorkflowRunCancelled):
        await publisher.publish_execution_cancelled(reason=outcome.reason)
        return

    output_payload: JsonValue = redact_value(outcome.output)
    await publisher.publish_execution_completed(outputs=output_payload)


class ExecutionCommandHandler:
    """Process RabbitMQ execution commands and drive the workflow runtime.

    Handles idempotent inbox claiming, envelope validation, event publishing,
    checkpoint persistence, and routing to start/resume/cancel flows. Each
    command is processed at-most-once per ``message_id`` via PostgresInbox.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        pool: asyncpg.Pool,
        channel: aio_pika.abc.AbstractChannel,
        registry: RuntimeRegistry,
        cancel_registry: CancelRegistry,
        credential_resolver: CredentialResolver | None = None,
        lease_store: RunLeaseStore | None = None,
        definition_store: PostgresDefinitionStore | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Wire dependencies used to validate, dedupe, and execute workflow commands."""
        self._settings = settings
        self._pool = pool
        self._channel = channel
        self._registry = registry
        self._cancel_registry = cancel_registry
        self._inbox = PostgresInbox(
            pool,
            stale_after=timedelta(seconds=settings.max_run_seconds + 60),
        )
        self._leases = lease_store
        self._definitions = definition_store
        self._http_client = http_client
        if credential_resolver is not None:
            self._credential_resolver = credential_resolver
        else:
            self._credential_resolver = build_credential_resolver(
                control_plane_url=settings.control_plane_internal_url,
                internal_auth_token=settings.internal_auth_token,
                openai_api_key=settings.openai_api_key,
            )

    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()

    async def handle(self, body: bytes) -> None:
        """Parse an envelope and dispatch by ``message_type``.

        Supported types: ``execution.start``, ``execution.resume``,
        ``execution.cancel``. Raises EnvelopeValidationError for malformed
        envelopes and MessageInFlightError when a duplicate in-flight message
        is detected.
        """
        raw = _parse_envelope(body)
        message_type = raw.get("message_type")
        if not isinstance(message_type, str):
            msg = "Envelope missing message_type"
            raise EnvelopeValidationError(msg)

        if message_type == "execution.start":
            await self._handle_start(raw)
            return
        if message_type == "execution.resume":
            await self._handle_resume(raw)
            return
        if message_type == "execution.cancel":
            await self._handle_cancel(raw)
            return
        if message_type in {"task.completed", "task.failed"}:
            await self._handle_task_result(raw)
            return

        msg = f"Unsupported message type: {message_type}"
        raise EnvelopeValidationError(msg)

    async def _handle_start(self, raw: dict[str, Any]) -> None:
        """Handle ``execution.start``: run a new workflow or continue from checkpoint.

        Claims the message in the inbox, publishes ``execution.started`` for new
        runs, then calls ``run_workflow`` or ``continue_workflow_from_checkpoint``
        depending on whether a checkpoint already exists for the run_id.
        Publishes completed/waiting/failed events and marks the inbox row done.
        """
        validate_envelope_document(
            raw,
            contracts_root=self._settings.contracts_root,
            source="execution.start",
        )
        parsed = parse_execution_start(raw)
        if parsed.envelope.message_type != "execution.start":
            msg = f"Unexpected message type: {parsed.envelope.message_type}"
            raise EnvelopeValidationError(msg)

        claim = await self._inbox.claim(
            message_id=parsed.envelope.message_id,
            run_id=parsed.subject.run_id,
            message_type=parsed.envelope.message_type,
        )
        if claim is ClaimResult.DUPLICATE_COMPLETED:
            logger.info("Skipping duplicate completed message %s", parsed.envelope.message_id)
            return
        if claim is ClaimResult.DUPLICATE_IN_FLIGHT:
            msg = f"Message {parsed.envelope.message_id} is still processing"
            raise MessageInFlightError(msg)

        publisher = EventPublisher(
            pool=self._pool,
            channel=self._channel,
            source_envelope=parsed.envelope,
            subject=parsed.subject,
        )

        checkpointer = PostgresCheckpointer(self._pool)
        hooks = publisher_hooks(publisher)
        dispatcher = RabbitTaskDispatcher(
            channel=self._channel,
            source_envelope=parsed.envelope,
            subject=parsed.subject,
        )
        if claim is ClaimResult.NEW and await publisher.get_last_sequence() == 0:
            await publisher.publish_execution_started()

        existing = await checkpointer.load(thread_id=parsed.subject.run_id)
        try:
            await self._acquire_lease(parsed.subject.run_id)
            if existing is not None and get_interrupt(existing) is not None:
                logger.info(
                    "Skipping execution.start for waiting run %s",
                    parsed.subject.run_id,
                )
                await self._inbox.mark_completed(message_id=parsed.envelope.message_id)
                return
            cancel_request = await self._cancel_registry.is_cancelled(parsed.subject.run_id)
            if cancel_request is not None:
                await publisher.publish_execution_cancelled(reason=cancel_request.reason)
                await self._inbox.mark_completed(message_id=parsed.envelope.message_id)
                return
            run_kwargs = {
                "registry": self._registry,
                "checkpointer": checkpointer,
                "hooks": hooks,
                "contracts_root": self._settings.contracts_root,
                "max_payload_bytes": self._settings.max_payload_bytes,
                "max_loop_iterations": self._settings.max_loop_iterations,
                "max_fan_out_items": self._settings.max_fan_out_items,
                "max_node_executions_cap": self._settings.max_node_executions,
                "max_parallel_nodes_cap": self._settings.max_parallel_nodes,
                "cancel_registry": self._cancel_registry,
                "credential_resolver": self._credential_resolver,
                "task_dispatcher": dispatcher,
                "definition_store": self._definitions,
            }
            if existing is not None:
                outcome = await continue_workflow_from_checkpoint(
                    parsed.payload.definition,
                    run_id=parsed.subject.run_id,
                    **run_kwargs,
                )
            else:
                outcome = await run_workflow(
                    parsed.payload.definition,
                    parsed.payload.input,
                    run_id=parsed.subject.run_id,
                    workspace_id=parsed.envelope.tenant.workspace_id,
                    project_id=parsed.envelope.tenant.project_id,
                    max_run_seconds=self._settings.max_run_seconds,
                    **run_kwargs,
                )
        except LeaseError:
            await self._inbox.mark_failed(message_id=parsed.envelope.message_id)
            raise
        except WorkflowRunTimedOut as exc:
            await publisher.publish_execution_failed(
                code="TIMED_OUT",
                message=str(exc),
                status="TIMED_OUT",
            )
            await self._inbox.mark_failed(message_id=parsed.envelope.message_id)
            return
        except WorkflowRunError as exc:
            await publisher.publish_execution_failed(code="WORKFLOW_RUN_FAILED", message=str(exc))
            await self._inbox.mark_failed(message_id=parsed.envelope.message_id)
            return
        finally:
            await self._release_lease(parsed.subject.run_id)

        await _publish_outcome(publisher, outcome)
        await self._cancel_registry.clear(parsed.subject.run_id)
        await self._inbox.mark_completed(message_id=parsed.envelope.message_id)

    async def _handle_resume(self, raw: dict[str, Any]) -> None:
        """Handle ``execution.resume``: unblock a human-interrupted workflow.

        Loads the workflow definition from the checkpoint, validates the resume
        command against the stored interrupt metadata, applies the decision,
        and publishes the resulting outcome event.
        """
        validate_envelope_document(
            raw,
            contracts_root=self._settings.contracts_root,
            source="execution.resume",
        )
        parsed = parse_execution_resume(raw)
        if parsed.envelope.message_type != "execution.resume":
            msg = f"Unexpected message type: {parsed.envelope.message_type}"
            raise EnvelopeValidationError(msg)

        claim = await self._inbox.claim(
            message_id=parsed.envelope.message_id,
            run_id=parsed.subject.run_id,
            message_type=parsed.envelope.message_type,
        )
        if claim is ClaimResult.DUPLICATE_COMPLETED:
            logger.info("Skipping duplicate completed message %s", parsed.envelope.message_id)
            return
        if claim is ClaimResult.DUPLICATE_IN_FLIGHT:
            msg = f"Message {parsed.envelope.message_id} is still processing"
            raise MessageInFlightError(msg)

        publisher = EventPublisher(
            pool=self._pool,
            channel=self._channel,
            source_envelope=parsed.envelope,
            subject=parsed.subject,
        )
        checkpointer = PostgresCheckpointer(self._pool)
        hooks = publisher_hooks(publisher)
        dispatcher = RabbitTaskDispatcher(
            channel=self._channel,
            source_envelope=parsed.envelope,
            subject=parsed.subject,
        )

        definition = await self._load_definition_from_checkpoint(
            checkpointer,
            parsed.subject.run_id,
        )
        if definition is None:
            await publisher.publish_execution_failed(
                code="RESUME_FAILED",
                message="No checkpoint found for resume",
            )
            await self._inbox.mark_failed(message_id=parsed.envelope.message_id)
            return

        try:
            await self._acquire_lease(parsed.subject.run_id)
            outcome = await resume_workflow(
                run_id=parsed.subject.run_id,
                waiting_reason=parsed.payload.waiting_reason,  # type: ignore[arg-type]
                interrupt_id=parsed.payload.interrupt_id,
                approval_id=parsed.payload.approval_id,
                task_id=parsed.payload.task_id,
                decision=parsed.payload.decision,
                definition=definition,
                registry=self._registry,
                checkpointer=checkpointer,
                hooks=hooks,
                contracts_root=self._settings.contracts_root,
                max_payload_bytes=self._settings.max_payload_bytes,
                max_loop_iterations=self._settings.max_loop_iterations,
                cancel_registry=self._cancel_registry,
                credential_resolver=self._credential_resolver,
                task_dispatcher=dispatcher,
                definition_store=self._definitions,
            )
        except LeaseError:
            await self._inbox.mark_failed(message_id=parsed.envelope.message_id)
            raise
        except ResumeValidationError as exc:
            await publisher.publish_execution_failed(
                code="RESUME_VALIDATION_FAILED",
                message=str(exc),
            )
            await self._inbox.mark_failed(message_id=parsed.envelope.message_id)
            return
        except WorkflowRunTimedOut as exc:
            await publisher.publish_execution_failed(
                code="TIMED_OUT",
                message=str(exc),
                status="TIMED_OUT",
            )
            await self._inbox.mark_failed(message_id=parsed.envelope.message_id)
            return
        except WorkflowRunError as exc:
            await publisher.publish_execution_failed(code="WORKFLOW_RUN_FAILED", message=str(exc))
            await self._inbox.mark_failed(message_id=parsed.envelope.message_id)
            return
        finally:
            await self._release_lease(parsed.subject.run_id)

        await _publish_outcome(publisher, outcome)
        await self._cancel_registry.clear(parsed.subject.run_id)
        await self._inbox.mark_completed(message_id=parsed.envelope.message_id)

    async def _handle_cancel(self, raw: dict[str, Any]) -> None:
        """Handle ``execution.cancel``: request cooperative run cancellation.

        Registers the cancel reason in CancelRegistry so the running
        ``_execute_loop`` can exit cleanly. If no checkpoint exists (run never
        started), publishes ``execution.cancelled`` immediately.
        """
        validate_envelope_document(
            raw,
            contracts_root=self._settings.contracts_root,
            source="execution.cancel",
        )
        parsed = parse_execution_cancel(raw)
        if parsed.envelope.message_type != "execution.cancel":
            msg = f"Unexpected message type: {parsed.envelope.message_type}"
            raise EnvelopeValidationError(msg)

        claim = await self._inbox.claim(
            message_id=parsed.envelope.message_id,
            run_id=parsed.subject.run_id,
            message_type=parsed.envelope.message_type,
        )
        if claim is ClaimResult.DUPLICATE_COMPLETED:
            logger.info("Skipping duplicate completed message %s", parsed.envelope.message_id)
            return
        if claim is ClaimResult.DUPLICATE_IN_FLIGHT:
            msg = f"Message {parsed.envelope.message_id} is still processing"
            raise MessageInFlightError(msg)

        await self._cancel_registry.request_cancel(
            parsed.subject.run_id,
            reason=parsed.payload.reason,
        )

        publisher = EventPublisher(
            pool=self._pool,
            channel=self._channel,
            source_envelope=parsed.envelope,
            subject=parsed.subject,
        )
        checkpointer = PostgresCheckpointer(self._pool)
        state = await checkpointer.load(thread_id=parsed.subject.run_id)
        if state is None or get_interrupt(state) is not None:
            if state is not None:
                clear_interrupt(state)
                await checkpointer.save(thread_id=parsed.subject.run_id, state=state)
            await publisher.publish_execution_cancelled(reason=parsed.payload.reason)
            await self._inbox.mark_completed(message_id=parsed.envelope.message_id)
            return

        await self._inbox.mark_completed(message_id=parsed.envelope.message_id)


    async def _handle_task_result(self, raw: dict[str, Any]) -> None:
        """Resume a waiting parent run from task.completed / task.failed events."""
        envelope_type = str(raw.get("message_type"))
        validate_envelope_document(
            raw,
            contracts_root=self._settings.contracts_root,
            source=envelope_type,
        )
        from ai_workflow.messaging.envelope import ExecutionSubject, MessageEnvelope

        envelope = MessageEnvelope.model_validate(raw)
        subject = ExecutionSubject.model_validate(envelope.subject)
        claim = await self._inbox.claim(
            message_id=envelope.message_id,
            run_id=subject.run_id,
            message_type=envelope.message_type,
        )
        if claim is ClaimResult.DUPLICATE_COMPLETED:
            return
        if claim is ClaimResult.DUPLICATE_IN_FLIGHT:
            raise MessageInFlightError(f"Message {envelope.message_id} is still processing")

        publisher = EventPublisher(
            pool=self._pool,
            channel=self._channel,
            source_envelope=envelope,
            subject=subject,
        )
        checkpointer = PostgresCheckpointer(self._pool)
        state = None
        interrupt = None
        # task.completed can land before the parent walker finishes writing the
        # TASK interrupt. Acking that delivery drops the resume forever; poll
        # briefly, then nack so the start handler can finish checkpointing.
        for _attempt in range(40):
            state = await checkpointer.load(thread_id=subject.run_id)
            interrupt = get_interrupt(state) if state is not None else None
            if interrupt is not None:
                break
            await asyncio.sleep(0.05)
        if state is None or interrupt is None:
            logger.info(
                "Deferring %s for run %s; parent not waiting yet",
                envelope.message_type,
                subject.run_id,
            )
            await self._inbox.mark_failed(message_id=envelope.message_id)
            raise MessageNotReadyError(
                f"{envelope.message_type} for run {subject.run_id} arrived before TASK interrupt"
            )

        payload = envelope.payload
        task_id_raw = payload.get("task_id") or subject.task_id
        if envelope.message_type == "task.failed":
            await publisher.publish_execution_failed(
                code="TASK_FAILED",
                message=str((payload.get("error") or {}).get("message", "task failed")),
            )
            await self._inbox.mark_failed(message_id=envelope.message_id)
            return

        definition = await self._load_definition_from_checkpoint(checkpointer, subject.run_id)
        if definition is None:
            await publisher.publish_execution_failed(
                code="RESUME_FAILED",
                message="No definition found for task resume",
            )
            await self._inbox.mark_failed(message_id=envelope.message_id)
            return

        decision = payload.get("result")
        if not isinstance(decision, dict):
            decision = {}
        dispatcher = RabbitTaskDispatcher(
            channel=self._channel,
            source_envelope=envelope,
            subject=subject,
        )
        try:
            await self._acquire_lease(subject.run_id)
            outcome = await resume_workflow(
                run_id=subject.run_id,
                waiting_reason="TASK",
                interrupt_id=UUID(str(interrupt["interrupt_id"])),
                approval_id=None,
                task_id=UUID(str(task_id_raw)),
                decision=decision,
                definition=definition,
                registry=self._registry,
                checkpointer=checkpointer,
                hooks=publisher_hooks(publisher),
                contracts_root=self._settings.contracts_root,
                max_payload_bytes=self._settings.max_payload_bytes,
                max_loop_iterations=self._settings.max_loop_iterations,
                cancel_registry=self._cancel_registry,
                credential_resolver=self._credential_resolver,
                task_dispatcher=dispatcher,
                definition_store=self._definitions,
            )
        except LeaseError:
            await self._inbox.mark_failed(message_id=envelope.message_id)
            raise
        except (ResumeValidationError, WorkflowRunError) as exc:
            await publisher.publish_execution_failed(code="TASK_RESUME_FAILED", message=str(exc))
            await self._inbox.mark_failed(message_id=envelope.message_id)
            return
        finally:
            await self._release_lease(subject.run_id)

        await _publish_outcome(publisher, outcome)
        await self._cancel_registry.clear(subject.run_id)
        await self._inbox.mark_completed(message_id=envelope.message_id)

    async def _acquire_lease(self, run_id: UUID) -> None:
        if self._leases is None:
            return
        await self._leases.acquire(
            run_id,
            ttl=timedelta(seconds=self._settings.max_run_seconds + 60),
        )

    async def _release_lease(self, run_id: UUID) -> None:
        if self._leases is None:
            return
        await self._leases.release(run_id)

    async def _load_definition_from_checkpoint(
        self,
        checkpointer: PostgresCheckpointer,
        run_id: Any,
    ) -> dict[str, JsonValue] | None:
        """Load the workflow definition by hash, falling back to checkpoint sidecar."""
        state = await checkpointer.load(thread_id=run_id)
        if state is None:
            return None
        digest = state.runtime.get(DEFINITION_HASH_KEY)
        if isinstance(digest, str) and self._definitions is not None:
            stored = await self._definitions.get(digest)
            if isinstance(stored, dict):
                return stored
        stored_def = state.runtime.get(DEFINITION_KEY)
        if isinstance(stored_def, dict):
            return stored_def
        return None


# Backward-compatible alias for existing tests.
ExecutionStartHandler = ExecutionCommandHandler


def build_execution_handler(
    *,
    settings: Settings,
    pool: asyncpg.Pool,
    channel: aio_pika.abc.AbstractChannel,
    cancel_registry: CancelRegistry | None = None,
    registry: RuntimeRegistry | None = None,
    credential_resolver: CredentialResolver | None = None,
) -> ExecutionCommandHandler:
    """Construct a fully wired handler for the execution worker process."""
    http_client = httpx.AsyncClient()
    if registry is None:
        safe_http_client = SafeHttpClient(http_client)
        action_key_store = PostgresActionKeyStore(pool)
        built_registry = build_runner_registry(
            settings.contracts_root,
            settings=settings,
            max_loop_iterations=settings.max_loop_iterations,
            max_fan_out_items=settings.max_fan_out_items,
            credential_resolver=credential_resolver,
            safe_http_client=safe_http_client,
            action_key_store=action_key_store,
            pool=pool,
        )
    else:
        built_registry = registry
    return ExecutionCommandHandler(
        settings=settings,
        pool=pool,
        channel=channel,
        registry=built_registry,
        cancel_registry=cancel_registry or CancelRegistry(),
        credential_resolver=credential_resolver,
        lease_store=RunLeaseStore(pool),
        definition_store=PostgresDefinitionStore(pool),
        http_client=http_client,
    )
