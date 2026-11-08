"""Shared helpers for execution-engine live e2e scripts (MQ + Postgres + mock CP)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import aio_pika
import asyncpg
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from uvicorn import Config, Server

from ai_workflow.config.settings import SERVICE_ROOT, Settings, load_settings
from ai_workflow.messaging.broker import MessagingNames as mq
from ai_workflow.messaging.broker import RabbitBroker
from ai_workflow.runtime.cancel import CancelRegistry
from ai_workflow.runtime.graph.scheduler import INTERRUPT_KEY
from ai_workflow.runtime.persistence.action_keys import PostgresActionKeyStore
from ai_workflow.runtime.persistence.database import create_pool, run_migrations
from ai_workflow.runtime.registry.bootstrap import build_runner_registry
from ai_workflow.security.credentials import build_credential_resolver
from ai_workflow.security.http_client import SafeHttpClient
from ai_workflow.security.ssrf import fake_resolver
from ai_workflow.tasks.checkpoints import PostgresTaskCheckpointStore
from ai_workflow.worker.execution_worker import _handle_message
from ai_workflow.worker.handler import ExecutionCommandHandler, build_execution_handler
from ai_workflow.worker.task_worker import _handle_task_command

logger = logging.getLogger(__name__)

WAIT_TIMEOUT_SECONDS = 300.0
MOCK_CP_HOST = "127.0.0.1"
LIVE_HTTP_URL_TEMPLATE = "https://httpbin.org/get?item={{item}}"

TERMINAL_MESSAGE_TYPES = frozenset(
    {
        "execution.completed",
        "execution.failed",
        "execution.waiting",
        "execution.cancelled",
    }
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fail(step: str, message: str) -> int:
    print(f"[FAIL] {step}: {message}", file=sys.stderr)
    return 1


def ok(step: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[OK] {step}{suffix}")


def require_real_llm(settings: Settings) -> str:
    if settings.fake_llm:
        msg = (
            "AIW_FAKE_LLM is enabled. Set AIW_FAKE_LLM=false in "
            "services/execution-engine/.env for a real AI run."
        )
        raise SystemExit(msg)
    api_key = settings.chat_api_key
    if not api_key:
        msg = (
            "No chat API key is configured. Add OPENAI_API_KEY for OpenAI or a "
            "ZenMux key to services/execution-engine/.env to run the live chat workflow."
        )
        raise SystemExit(msg)
    return api_key


def create_mock_control_plane_app(*, chat_api_key: str) -> Starlette:
    async def _credentials_resolve(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)

        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be an object"}, status_code=400)

        node_id = body.get("nodeId")
        slots = body.get("slots")
        if not isinstance(node_id, str) or not node_id:
            return JSONResponse({"error": "nodeId is required"}, status_code=400)
        if not isinstance(slots, list) or not slots:
            return JSONResponse({"error": "slots is required"}, status_code=400)

        credentials: dict[str, str] = {}
        for slot in slots:
            if not isinstance(slot, str):
                return JSONResponse({"error": "slots must be strings"}, status_code=400)
            if slot in {"provider", "model_provider"}:
                credentials[slot] = chat_api_key
            elif slot == "search_provider":
                credentials[slot] = "e2e-search-placeholder"
            else:
                return JSONResponse({"error": f"unknown slot: {slot}"}, status_code=404)

        return JSONResponse({"credentials": credentials})

    return Starlette(
        routes=[
            Route(
                "/internal/v1/executions/{run_id}/credentials:resolve",
                _credentials_resolve,
                methods=["POST"],
            ),
        ],
    )


def prepare_live_workflow(
    workflow: dict[str, Any],
    *,
    http_node_id: str,
    chat_node_id: str,
    chat_model: str = "deepseek/deepseek-v4-pro",
    http_url_template: str = LIVE_HTTP_URL_TEMPLATE,
    collect_node_id: str | None = None,
    artifact_threshold_bytes: int | None = 256,
) -> dict[str, Any]:
    """Point HTTP + chat credential refs at a live path (mutates a deep copy)."""
    prepared = deepcopy(workflow)
    for node in prepared.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("id") == http_node_id:
            config = node.setdefault("config", {})
            if isinstance(config, dict):
                config["url_template"] = http_url_template
        if node.get("id") == chat_node_id:
            config = node.setdefault("config", {})
            if isinstance(config, dict):
                config["model"] = chat_model
            node["credential_refs"] = {
                "provider": "cccccccc-cccc-4ccc-8ccc-cccccccccc01",
            }
        if collect_node_id and node.get("id") == collect_node_id:
            config = node.setdefault("config", {})
            if isinstance(config, dict) and artifact_threshold_bytes is not None:
                config["artifact_threshold_bytes"] = artifact_threshold_bytes
    return prepared


def build_start_envelope(
    workflow: dict[str, Any],
    *,
    run_input: dict[str, Any],
    run_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], str]:
    resolved_run_id = run_id or str(uuid4())
    envelope: dict[str, Any] = {
        "message_id": str(uuid4()),
        "message_type": "execution.start",
        "schema_version": "1.0",
        "occurred_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "correlation_id": str(uuid4()),
        "causation_id": None,
        "idempotency_key": idempotency_key or f"start:{resolved_run_id}",
        "tenant": {
            "workspace_id": "55555555-5555-4555-8555-555555555501",
            "project_id": "66666666-6666-4666-8666-666666666601",
        },
        "subject": {
            "workflow_id": workflow["workflow_id"],
            "workflow_version_id": workflow["workflow_version_id"],
            "run_id": resolved_run_id,
        },
        "sequence": None,
        "payload": {
            "mode": "published",
            "draft_revision": None,
            "trigger": {"type": "manual", "trigger_id": None},
            "input": run_input,
            "definition": deepcopy(workflow),
        },
    }
    return envelope, resolved_run_id


def mint_resume_envelope(
    *,
    waiting_event: dict[str, Any],
    run_id: str,
    workflow_id: str,
    workflow_version_id: str,
    interrupt_id: str,
    approval_id: str | None,
    decision: dict[str, Any],
    task_id: str | None = None,
    waiting_reason: str | None = None,
) -> dict[str, Any]:
    payload = waiting_event.get("payload") or {}
    reason = waiting_reason or payload.get("waiting_reason", "HUMAN")
    return {
        "message_id": str(uuid4()),
        "message_type": "execution.resume",
        "schema_version": "1.0",
        "occurred_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00",
            "Z",
        ),
        "correlation_id": str(uuid4()),
        "causation_id": waiting_event.get("message_id"),
        "idempotency_key": f"resume:{run_id}:{interrupt_id}",
        "tenant": waiting_event.get("tenant")
        or {
            "workspace_id": "55555555-5555-4555-8555-555555555501",
            "project_id": "66666666-6666-4666-8666-666666666601",
        },
        "subject": {
            "workflow_id": workflow_id,
            "workflow_version_id": workflow_version_id,
            "run_id": run_id,
        },
        "sequence": None,
        "payload": {
            "waiting_reason": reason,
            "interrupt_id": interrupt_id,
            "approval_id": approval_id,
            "task_id": task_id,
            "decision": decision,
        },
    }


def mint_cancel_envelope(
    *,
    run_id: str,
    workflow_id: str,
    workflow_version_id: str,
    waiting_event: dict[str, Any] | None = None,
    reason: str = "user_requested",
) -> dict[str, Any]:
    tenant = (waiting_event or {}).get("tenant") or {
        "workspace_id": "55555555-5555-4555-8555-555555555501",
        "project_id": "66666666-6666-4666-8666-666666666601",
    }
    return {
        "message_id": str(uuid4()),
        "message_type": "execution.cancel",
        "schema_version": "1.0",
        "occurred_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00",
            "Z",
        ),
        "correlation_id": str(uuid4()),
        "causation_id": (waiting_event or {}).get("message_id"),
        "idempotency_key": f"cancel:{run_id}",
        "tenant": tenant,
        "subject": {
            "workflow_id": workflow_id,
            "workflow_version_id": workflow_version_id,
            "run_id": run_id,
        },
        "sequence": None,
        "payload": {
            "reason": reason,
            "requested_by": "99999999-9999-4999-8999-999999999901",
        },
    }


async def publish_command(
    channel: aio_pika.abc.AbstractChannel,
    envelope: dict[str, Any],
    routing_key: str,
) -> None:
    commands = await channel.get_exchange(mq.COMMANDS_EXCHANGE)
    payload = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    await commands.publish(
        aio_pika.Message(
            body=payload,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=routing_key,
    )


class EventCollector:
    def __init__(self, channel: aio_pika.abc.AbstractChannel) -> None:
        self._channel = channel
        self._events: list[dict[str, Any]] = []
        self._queue: aio_pika.abc.AbstractQueue | None = None
        self._consumer_tag: str | None = None
        self._ready = asyncio.Event()

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def event_count(self) -> int:
        return len(self._events)

    async def start(self) -> None:
        events_exchange = await self._channel.get_exchange(mq.EVENTS_EXCHANGE)
        self._queue = await self._channel.declare_queue(exclusive=True, auto_delete=True)
        await self._queue.bind(events_exchange, routing_key="#")

        async def _on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            async with message.process(requeue=False):
                body = json.loads(message.body.decode("utf-8"))
                self._events.append(body)

        self._consumer_tag = await self._queue.consume(_on_message)
        self._ready.set()

    async def wait_ready(self, timeout: float = 5.0) -> None:
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    async def stop(self) -> None:
        if self._queue is not None and self._consumer_tag is not None:
            await self._queue.cancel(self._consumer_tag)


def events_for_run(events: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if (event.get("subject") or {}).get("run_id") == run_id
    ]


async def wait_for_terminal(
    collector: EventCollector,
    *,
    run_id: str,
    timeout_seconds: float,
    allowed: frozenset[str] | None = None,
    after_index: int = 0,
) -> dict[str, Any]:
    """Wait for a terminal event for ``run_id`` appearing at or after ``after_index``."""
    terminal = allowed or TERMINAL_MESSAGE_TYPES
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        for event in collector.events[after_index:]:
            if (event.get("subject") or {}).get("run_id") != run_id:
                continue
            if event.get("message_type") in terminal:
                return event

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            msg = f"Timed out waiting for terminal event run_id={run_id}"
            raise TimeoutError(msg)
        await asyncio.sleep(0.1)


async def query_interrupt_from_checkpoint(
    pool: asyncpg.Pool,
    run_id: str,
) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        "SELECT state FROM ee.workflow_checkpoints WHERE thread_id = $1::uuid",
        UUID(run_id),
    )
    if row is None:
        return None
    state = row["state"]
    if isinstance(state, str):
        state = json.loads(state)
    if not isinstance(state, dict):
        return None
    interrupt = state.get("interrupt")
    if isinstance(interrupt, dict):
        return interrupt
    runtime = state.get("runtime")
    if not isinstance(runtime, dict):
        return None
    interrupt = runtime.get(INTERRUPT_KEY)
    return interrupt if isinstance(interrupt, dict) else None


async def query_checkpoint_envelope(
    pool: asyncpg.Pool,
    run_id: str,
) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """
        SELECT state, definition_hash
        FROM ee.workflow_checkpoints
        WHERE thread_id = $1::uuid
        """,
        UUID(run_id),
    )
    if row is None:
        return None
    state = row["state"]
    if isinstance(state, str):
        state = json.loads(state)
    if not isinstance(state, dict):
        return None
    envelope = dict(state)
    if row["definition_hash"] and not envelope.get("definition_hash"):
        envelope["definition_hash"] = row["definition_hash"]
    return envelope


async def assert_run_scale_invariants(pool: asyncpg.Pool, run_id: str) -> str | None:
    """Return an error if definition/lease/checkpoint invariants failed after a run."""
    envelope = await query_checkpoint_envelope(pool, run_id)
    if envelope is None:
        return "no checkpoint row after run"
    digest = envelope.get("definition_hash")
    if not isinstance(digest, str) or not digest:
        return "checkpoint missing definition_hash"
    stored = await pool.fetchrow(
        "SELECT 1 FROM ee.workflow_definitions WHERE definition_hash = $1",
        digest,
    )
    if stored is None:
        return f"definition_hash {digest} not in ee.workflow_definitions"
    lease = await pool.fetchrow(
        "SELECT 1 FROM ee.run_leases WHERE run_id = $1::uuid",
        UUID(run_id),
    )
    if lease is not None:
        return "run lease was not released after the walker finished"
    version = envelope.get("schema_version")
    if version not in (None, 1):
        return f"unexpected checkpoint schema_version={version!r}"
    return None


def assert_event_sequences(events: list[dict[str, Any]], run_id: str) -> str | None:
    """Return an error if execution/node event sequences are duplicated or gapped.

    ``task.*`` events use a separate per-task sequence (often ``1`` for
    ``task.completed``) and must not be mixed with the run's execution sequence.
    """
    sequences: list[int] = []
    for event in events_for_run(events, run_id):
        message_type = event.get("message_type")
        if not isinstance(message_type, str):
            continue
        if not (message_type.startswith("execution.") or message_type.startswith("node.")):
            continue
        sequence = event.get("sequence")
        if sequence is None:
            continue
        if not isinstance(sequence, int) or sequence < 1:
            return f"invalid sequence {sequence!r} on {message_type}"
        sequences.append(sequence)
    if not sequences:
        return "no sequenced execution/node events published for run"
    unique = set(sequences)
    if len(unique) != len(sequences):
        return f"duplicate execution/node event sequences: {sorted(sequences)}"
    missing = set(range(1, max(unique) + 1)) - unique
    if missing:
        return f"event sequence gaps: {sorted(missing)}"
    return None


async def assert_path_invariants(
    pool: asyncpg.Pool,
    events: list[dict[str, Any]],
    run_id: str,
    *,
    secret: str | None = None,
) -> str | None:
    """Scale + ordered-event (+ optional secret) checks after a path finishes."""
    scale = await assert_run_scale_invariants(pool, run_id)
    if scale:
        return scale
    sequenced = assert_event_sequences(events, run_id)
    if sequenced:
        return sequenced
    if secret:
        return assert_no_secret_in_events(events_for_run(events, run_id), secret)
    return None


def print_llm_response(response: dict[str, Any], *, topic: str) -> None:
    text = response.get("text")
    usage = response.get("usage")
    print("\n=== LLM RESPONSE (ai.chat-model) ===")
    print(f"Topic: {topic}")
    print("---")
    print(text if isinstance(text, str) else "")
    print("---")
    if isinstance(usage, dict) and usage:
        print(f"Usage: {json.dumps(usage, ensure_ascii=False)}")
    print("===================================\n")


async def prompt_human_decision() -> dict[str, Any]:
    """Block until the operator types approve or reject in the terminal."""
    print("=== HUMAN APPROVAL REQUIRED ===")
    print("Review the LLM response above.")
    print("Type 'approve' or 'reject', then press Enter:")
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        choice = (line or "").strip().lower()
        if choice in {"approve", "approved", "a", "y", "yes"}:
            return {"decision": "approved"}
        if choice in {"reject", "rejected", "r", "n", "no"}:
            return {"decision": "rejected"}
        print("Please type approve or reject:")


async def prompt_human_review_value(default_value: dict[str, Any]) -> dict[str, Any]:
    """Interactive review: Enter keeps default; otherwise parse JSON object."""
    print("=== HUMAN REVIEW REQUIRED ===")
    print("Collect result presented for review:")
    print(json.dumps(default_value, indent=2, ensure_ascii=False))
    print("Press Enter to accept as-is, or paste a JSON object and Enter:")
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        raw = (line or "").strip()
        if not raw:
            return {"value": default_value}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            print("Invalid JSON; try again or press Enter to accept default:")
            continue
        if not isinstance(parsed, dict):
            print("Review value must be a JSON object; try again:")
            continue
        return {"value": parsed}


async def prompt_review_correctness() -> bool:
    """Ask whether generated chat output is correct (True) or should be regenerated."""
    print("=== HUMAN REVIEW: is the generated output correct? ===")
    print("Type 'correct' to accept, or 'incorrect' to regenerate from the same prompt:")
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        choice = (line or "").strip().lower()
        if choice in {"correct", "yes", "y", "ok", "approve", "approved"}:
            return True
        if choice in {"incorrect", "no", "n", "reject", "rejected", "regenerate"}:
            return False
        print("Please type correct or incorrect:")


def node_completed_ids(events: list[dict]) -> set[str]:
    return {
        str((event.get("payload") or {}).get("node_id"))
        for event in events
        if event.get("message_type") == "node.completed"
    }


def node_completed_count(events: list[dict], node_id: str) -> int:
    return sum(
        1
        for event in events
        if event.get("message_type") == "node.completed"
        and str((event.get("payload") or {}).get("node_id")) == node_id
    )


def chat_response_from_events(events: list[dict], *, chat_node_id: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("message_type") != "node.completed":
            continue
        payload = event.get("payload") or {}
        if payload.get("node_id") != chat_node_id:
            continue
        outputs = payload.get("outputs") or {}
        response = outputs.get("response")
        if isinstance(response, dict):
            text = response.get("text")
            if isinstance(text, str) and text:
                return response
    return None


def latest_chat_response_from_events(
    events: list[dict],
    *,
    chat_node_id: str,
) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("message_type") != "node.completed":
            continue
        payload = event.get("payload") or {}
        if payload.get("node_id") != chat_node_id:
            continue
        outputs = payload.get("outputs") or {}
        response = outputs.get("response")
        if isinstance(response, dict):
            text = response.get("text")
            if isinstance(text, str) and text:
                return response
    return None


def collect_result_from_events(
    events: list[dict],
    *,
    collect_node_id: str,
) -> dict[str, Any] | None:
    for event in events:
        if event.get("message_type") != "node.completed":
            continue
        payload = event.get("payload") or {}
        if payload.get("node_id") != collect_node_id:
            continue
        outputs = payload.get("outputs") or {}
        result = outputs.get("result")
        if isinstance(result, dict):
            return result
    return None


def assert_no_secret_in_events(events: list[dict[str, Any]], secret: str) -> str | None:
    """Return an error message if ``secret`` appears in serialized events."""
    if not secret:
        return None
    blob = json.dumps(events, ensure_ascii=False)
    if secret in blob:
        return "provider API key leaked into published events"
    return None


def build_live_http_registry(
    settings: Settings,
    *,
    action_key_store: PostgresActionKeyStore | None = None,
    pool: asyncpg.Pool | None = None,
):
    # Windows/DNS64 often returns NAT64 IPv6 (64:ff9b::/96) for public hosts;
    # SSRF treats those as reserved. Pin a public IPv4 for the SSRF check only —
    # httpx still dials httpbin.org by hostname for the real request.
    http_client = SafeHttpClient(
        httpx.AsyncClient(),
        resolver=fake_resolver({"httpbin.org": ["93.184.216.34"]}),
    )
    store = action_key_store
    if store is None and pool is not None:
        store = PostgresActionKeyStore(pool)
    return build_runner_registry(
        settings.contracts_root,
        settings=settings,
        safe_http_client=http_client,
        action_key_store=store,
        pool=pool,
        max_loop_iterations=settings.max_loop_iterations,
        max_fan_out_items=settings.max_fan_out_items,
    )


class CrashOnceExecutor:
    """Delegate wrapper that fails once for a specific node id, then succeeds."""

    def __init__(
        self,
        delegate: object,
        *,
        crash_node_id: str,
        state: dict[str, int],
    ) -> None:
        self.node_type = getattr(delegate, "node_type", "")
        self._delegate = delegate
        self._crash_node_id = crash_node_id
        self._state = state

    async def execute(self, context: object, config: object, inputs: object) -> object:
        node_id = str(getattr(context, "node_id", ""))
        if node_id == self._crash_node_id and self._state["crashes"] == 0:
            self._state["crashes"] += 1
            raise RuntimeError("simulated worker crash after checkpoint")
        return await self._delegate.execute(context, config, inputs)  # type: ignore[attr-defined]


def install_crash_once_node(
    registry: object,
    *,
    node_type: str,
    crash_node_id: str,
) -> dict[str, int]:
    """Replace ``node_type`` so the named node fails once, then delegates."""
    original = registry.get_node(node_type)  # type: ignore[attr-defined]
    delegate = original.executor_factory()
    state = {"crashes": 0}
    registry._nodes[node_type] = replace(  # noqa: SLF001 - e2e crash-injection seam
        original,
        executor_factory=lambda: CrashOnceExecutor(
            delegate,
            crash_node_id=crash_node_id,
            state=state,
        ),
    )
    return state


@dataclass
class E2ERuntime:
    settings: Settings
    pool: asyncpg.Pool
    connection: aio_pika.abc.AbstractRobustConnection
    channel: aio_pika.abc.AbstractChannel
    collector: EventCollector
    handler: ExecutionCommandHandler
    consumer_tag: str
    queue: aio_pika.abc.AbstractQueue
    task_consumer_tag: str
    task_queue: aio_pika.abc.AbstractQueue
    results_consumer_tag: str
    results_queue: aio_pika.abc.AbstractQueue
    mock_cp_server: Server
    mock_cp_task: asyncio.Task[None]
    chat_api_key: str


async def start_mock_control_plane(
    *,
    chat_api_key: str,
) -> tuple[Server, asyncio.Task[None], int]:
    app = create_mock_control_plane_app(chat_api_key=chat_api_key)
    bind = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bind.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bind.bind((MOCK_CP_HOST, 0))
    port = bind.getsockname()[1]
    bind.close()
    config = Config(app=app, host=MOCK_CP_HOST, port=port, log_level="warning")
    server = Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.3)
    return server, task, port


async def setup_runtime(*, log_label: str = "e2e") -> E2ERuntime:
    os.environ.setdefault("AIW_INTERNAL_AUTH_TOKEN", "e2e-test-token")
    os.environ.setdefault("AIW_SERVICE_ROLE", "execution-worker")
    # Override .env smoke-test defaults (dotenv uses override=False).
    os.environ["AIW_FAKE_LLM"] = "false"

    preliminary = load_settings()
    api_key = require_real_llm(preliminary)

    mock_cp_server, mock_cp_task, mock_cp_port = await start_mock_control_plane(
        chat_api_key=api_key,
    )
    os.environ["AIW_CONTROL_PLANE_INTERNAL_URL"] = f"http://{MOCK_CP_HOST}:{mock_cp_port}"
    settings = load_settings()
    require_real_llm(settings)

    bootstrap_pool = await create_pool(settings.database_url)
    try:
        sql_dir = SERVICE_ROOT / "sql"
        applied = await run_migrations(bootstrap_pool, sql_dir)
        if applied:
            logger.info("Applied migrations: %s", ", ".join(applied))
        result = await bootstrap_pool.execute(
            "UPDATE ee.worker_inbox SET status = 'failed', updated_at = NOW() "
            "WHERE status = 'processing'"
        )
        if result and result != "UPDATE 0":
            logger.info("Marked stale inbox processing rows as failed: %s", result)
    finally:
        await bootstrap_pool.close()

    pool = await create_pool(
        settings.database_url,
        max_size=max(settings.worker_prefetch + 4, 10),
    )

    broker = RabbitBroker()
    connection = await broker.connect(
        settings.rabbitmq_url, attempts=15, delay_seconds=1.0, role="execution-worker"
    )
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=settings.worker_prefetch)
    await broker.declare_topology(channel)

    credential_resolver = build_credential_resolver(
        control_plane_url=settings.control_plane_internal_url,
        internal_auth_token=settings.internal_auth_token,
        chat_api_key=settings.chat_api_key,
    )
    action_key_store = PostgresActionKeyStore(pool)
    registry = build_live_http_registry(
        settings,
        action_key_store=action_key_store,
        pool=pool,
    )
    cancel_registry = CancelRegistry(pool)
    handler = build_execution_handler(
        settings=settings,
        pool=pool,
        channel=channel,
        cancel_registry=cancel_registry,
        registry=registry,
        credential_resolver=credential_resolver,
    )
    task_checkpoints = PostgresTaskCheckpointStore(pool)
    semaphore = asyncio.Semaphore(settings.worker_prefetch)

    async def _purge(name: str) -> aio_pika.abc.AbstractQueue:
        declared = await broker.declare_durable_queue(channel, name)
        purged = await declared.purge()
        if purged:
            logger.info("Purged %s stale message(s) from %s", purged, name)
        return declared

    queue = await _purge(mq.EXECUTION_COMMANDS_QUEUE)
    task_queue = await _purge(mq.TASK_COMMANDS_QUEUE)
    results_queue = await _purge(mq.TASK_RESULTS_QUEUE)

    async def on_execution_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
        async def _run() -> None:
            async with semaphore:
                await _handle_message(handler, message)

        asyncio.create_task(_run())

    async def on_task_command(message: aio_pika.abc.AbstractIncomingMessage) -> None:
        async def _run() -> None:
            async with semaphore:
                try:
                    await _handle_task_command(
                        message.body,
                        channel=channel,
                        registry=registry,
                        checkpoints=task_checkpoints,
                        cancel_registry=cancel_registry,
                    )
                except Exception:
                    logger.exception("Task command failed")
                    await message.nack(requeue=False)
                    return
                await message.ack()

        asyncio.create_task(_run())

    exclusive_error = (
        "Queue has another consumer (docker compose execution-worker/task-worker?). "
        "Stop those services so this script can consume exclusively:\n"
        "  docker compose stop execution-worker task-worker"
    )

    async def _consume_exclusive(
        declared: aio_pika.abc.AbstractQueue,
        callback: Any,
    ) -> str:
        try:
            return await declared.consume(callback, exclusive=True)
        except Exception as exc:  # noqa: BLE001 - broker exclusive-lock errors vary
            raise SystemExit(f"{exclusive_error}\nOriginal error: {exc}") from exc

    consumer_tag = await _consume_exclusive(queue, on_execution_message)
    task_consumer_tag = await _consume_exclusive(task_queue, on_task_command)
    results_consumer_tag = await _consume_exclusive(results_queue, on_execution_message)
    logger.info(
        "%s worker consuming %s + %s + %s (real LLM base_url=%s)",
        log_label,
        mq.EXECUTION_COMMANDS_QUEUE,
        mq.TASK_COMMANDS_QUEUE,
        mq.TASK_RESULTS_QUEUE,
        settings.chat_base_url,
    )

    collector = EventCollector(channel)
    await collector.start()
    await collector.wait_ready()

    return E2ERuntime(
        settings=settings,
        pool=pool,
        connection=connection,
        channel=channel,
        collector=collector,
        handler=handler,
        consumer_tag=consumer_tag,
        queue=queue,
        task_consumer_tag=task_consumer_tag,
        task_queue=task_queue,
        results_consumer_tag=results_consumer_tag,
        results_queue=results_queue,
        mock_cp_server=mock_cp_server,
        mock_cp_task=mock_cp_task,
        chat_api_key=api_key,
    )


async def teardown_runtime(runtime: E2ERuntime) -> None:
    await runtime.collector.stop()
    await runtime.queue.cancel(runtime.consumer_tag)
    await runtime.task_queue.cancel(runtime.task_consumer_tag)
    await runtime.results_queue.cancel(runtime.results_consumer_tag)
    await runtime.handler.aclose()
    await runtime.connection.close()
    await runtime.pool.close()
    runtime.mock_cp_server.should_exit = True
    await runtime.mock_cp_task
