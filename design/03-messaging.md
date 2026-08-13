# Messaging Design

RabbitMQ is transport, not the long-term system of record. PostgreSQL outbox/read models and checkpoints remain authoritative.

## Topology

| Entity | Name | Purpose |
| --- | --- | --- |
| Topic exchange | `aiw.commands.v1` | Commands to workers |
| Topic exchange | `aiw.events.v1` | Events to control plane / coordinators |
| Queue | `aiw.execution.commands.v1` | start / resume / cancel |
| Queue | `aiw.ingestion.commands.v1` | document ingest / delete |
| Queue | `aiw.task.commands.v1` | heavy task start / cancel |
| Queue | `aiw.task.results.v1` | task completion for parent resume |
| Queue | `aiw.control.events.v1` | events for Spring projector |
| DLX | `aiw.dead.v1` | exhausted / invalid messages |

Routing keys use versioned forms: `execution.start.v1`, `node.completed.v1`, `document.ingest.v1`, `task.progress.v1`, etc.

## Commands

| Type | Publisher | Consumer | Payload intent |
| --- | --- | --- | --- |
| `execution.start` | control-plane outbox | execution-worker | Frozen definition snapshot + input + `mode` |
| `execution.cancel` | control-plane outbox | execution-worker | Cooperative cancel for run (+ child tasks) |
| `execution.resume` | control-plane outbox **HUMAN only** | execution-worker | Approval/review decision. **Not** used for TASK waits. |
| `document.ingest` | control-plane outbox | **rag-worker** | Document version to index |
| `document.delete` | control-plane outbox | **rag-worker** | Remove vectors / mark inactive |
| `task.start` | **execution-worker** | task-worker | Typed job payload + budgets. Control plane never publishes this. |
| `task.cancel` | control-plane (user) and/or execution-worker (run cancel) | task-worker | Stop between items / await points |

Commands never carry credential plaintext. Commands have `sequence: null`. TASK waits resume in-process on execution-worker after `aiw.task.results.v1`.

## Events (workers → control)

| Type | Meaning |
| --- | --- |
| `execution.queued` / `started` / `waiting` | Lifecycle. Spring sets `QUEUED` on insert; the first broker event may be `execution.started`. |
| `execution.completed` / `failed` / `cancelled` | Terminal |
| `node.started` / `completed` / `failed` | Per-node |
| `document.ingestion.started` / `completed` / `failed` | Ingest |
| `task.progress` / `item.completed` / `completed` / `failed` | Heavy tasks |

Events carry monotonic `sequence` per run (or per document flow). Progress events may be rate-limited; large payloads become artifact refs.

## Outbox (control plane)

```text
Create run + outbox row  →  one DB transaction
Publisher claims with FOR UPDATE SKIP LOCKED
Publish with broker confirms
Mark published / backoff on failure
```

A committed run always yields an eventually published command.

## Inbox / idempotency (workers + control)

1. Persist `message_id` (or consumer+message composite) before side effects complete.
2. Duplicate delivery → ack and skip.
3. Side-effecting nodes use stable execution keys: `run_id + node_id` (plus `item_key` inside for-each). Retry **attempt is not part of the key**.
4. Task items use stable `task_id + item_key`.
5. Spring enforces unique `(execution_id, sequence)`.

## Retry and DLQ

| Error class | Behavior |
| --- | --- |
| Schema / auth / unsupported version | Immediate DLQ |
| Transient network / rate limit | Bounded exponential backoff + jitter |
| Exhausted attempts | DLQ with safe metadata (no secrets) |

## Ack rules

- Workers ack only after durable obligations: inbox row, checkpoint/event outbox as required.
- Control plane acks events only after projector transaction commits.
- Never ack then process.

## Developer tips

- Validate envelopes with shared fixtures before wiring business logic.
- Include `tenant` and `subject` on every message; reject missing scope.
- Redact sensitive fields before publishing events.
- Prefer embedding bounded immutable definition in `execution.start` for MVP (avoids worker callback for definition fetch).
