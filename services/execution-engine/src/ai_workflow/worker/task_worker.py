from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

import aio_pika

from ai_workflow.config.settings import SERVICE_ROOT, load_settings, require_service_role
from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.log_context import execution_log_extra
from ai_workflow.messaging import constants as mq
from ai_workflow.messaging.consumer import connect_rabbitmq, consume_queue
from ai_workflow.messaging.envelope import MessageEnvelope, build_event_envelope
from ai_workflow.messaging.topology import declare_topology
from ai_workflow.runtime.bootstrap import build_runner_registry
from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.runtime.db import create_pool, run_migrations
from ai_workflow.security.redaction import redact_value
from ai_workflow.tasks.base import TaskContext
from ai_workflow.tasks.checkpoints import PostgresTaskCheckpointStore

logger = logging.getLogger(__name__)
_ROLE = "task-worker"


async def run_task_worker() -> None:
    """Boot the durable-task worker and consume task.start / task.cancel."""
    settings = load_settings()
    require_service_role(settings, "task-worker")
    logging.basicConfig(level=settings.log_level)

    pool = await create_pool(
        settings.database_url,
        max_size=max(settings.worker_prefetch + 4, 10),
    )
    applied = await run_migrations(pool, SERVICE_ROOT / "sql")
    extra = execution_log_extra(role=_ROLE)
    if applied:
        logger.info("Applied migrations: %s", ", ".join(applied), extra=extra)

    cancel_registry = CancelRegistry(pool)
    checkpoints = PostgresTaskCheckpointStore(pool)
    registry = build_runner_registry(settings.contracts_root, settings=settings, pool=pool)

    connection = await connect_rabbitmq(settings.rabbitmq_url, role=_ROLE)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=settings.worker_prefetch)
    await declare_topology(channel)
    semaphore = asyncio.Semaphore(settings.worker_prefetch)

    async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
        async with semaphore:
            try:
                await _handle_task_command(
                    message.body,
                    channel=channel,
                    registry=registry,
                    checkpoints=checkpoints,
                    cancel_registry=cancel_registry,
                )
            except Exception:
                logger.exception("Task command failed", extra=extra)
                await message.nack(requeue=False)
                return
            await message.ack()

    await consume_queue(channel, mq.TASK_COMMANDS_QUEUE, on_message)
    logger.info("Task worker listening on %s", mq.TASK_COMMANDS_QUEUE, extra=extra)
    try:
        await asyncio.Future()
    finally:
        await connection.close()
        await pool.close()


async def _handle_task_command(
    body: bytes,
    *,
    channel: aio_pika.abc.AbstractChannel,
    registry,
    checkpoints: PostgresTaskCheckpointStore,
    cancel_registry: CancelRegistry,
) -> None:
    raw = json.loads(body.decode("utf-8"))
    envelope = MessageEnvelope.model_validate(raw)
    if envelope.message_type == "task.cancel":
        run_id = UUID(str(envelope.subject["run_id"]))
        await cancel_registry.request_cancel(run_id, reason="user_requested")
        return
    if envelope.message_type != "task.start":
        msg = f"Unsupported task command: {envelope.message_type}"
        raise ValueError(msg)

    payload = envelope.payload
    task_id = UUID(str(payload["task_id"]))
    task_type = str(payload["task_type"])
    node_id = UUID(str(payload["node_id"]))
    run_id = UUID(str(envelope.subject["run_id"]))
    task_payload = payload.get("payload")
    if not isinstance(task_payload, dict):
        task_payload = {}

    cancel = await cancel_registry.is_cancelled(run_id)
    if cancel is not None:
        await _publish_task_event(
            channel,
            envelope,
            message_type="task.failed",
            routing_key=mq.TASK_FAILED_ROUTING_KEY,
            payload={
                "task_id": str(task_id),
                "status": "CANCELLED",
                "error": {"code": "CANCELLED", "message": cancel.reason},
            },
        )
        return

    registration = registry.get_task(task_type)
    executor = registration.executor_factory()
    stored = await checkpoints.load(task_id)
    context = TaskContext(
        run_id=run_id,
        workspace_id=envelope.tenant.workspace_id,
        project_id=envelope.tenant.project_id,
        workflow_version_id=(
            UUID(str(envelope.subject["workflow_version_id"]))
            if envelope.subject.get("workflow_version_id")
            else None
        ),
        node_id=node_id,
        task_id=task_id,
        attempt=1,
        deadline=None,
    )
    result = await executor.run(context, task_payload, stored)
    checkpoint_data = dict(result.metadata) if result.metadata else {
        "completed_at": datetime.now(UTC).isoformat(),
    }
    await checkpoints.save(
        task_id=task_id,
        run_id=run_id,
        node_id=node_id,
        task_type=task_type,
        data=checkpoint_data,
    )
    await _publish_task_event(
        channel,
        envelope,
        message_type="task.completed",
        routing_key=mq.TASK_COMPLETED_ROUTING_KEY,
        payload={
            "task_id": str(task_id),
            "status": "SUCCEEDED",
            "result": redact_value(result.outputs),
        },
    )


async def _publish_task_event(
    channel: aio_pika.abc.AbstractChannel,
    source: MessageEnvelope,
    *,
    message_type: str,
    routing_key: str,
    payload: dict[str, JsonValue],
) -> None:
    envelope = build_event_envelope(
        message_id=uuid4(),
        message_type=message_type,
        correlation_id=source.correlation_id,
        causation_id=source.message_id,
        idempotency_key=f"{message_type}:{source.subject.get('task_id')}",
        tenant=source.tenant,
        subject=source.subject,
        sequence=1,
        payload=payload,
    )
    exchange = await channel.get_exchange(mq.EVENTS_EXCHANGE)
    body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    await exchange.publish(
        aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=routing_key,
    )


def main() -> None:
    asyncio.run(run_task_worker())


if __name__ == "__main__":
    main()
