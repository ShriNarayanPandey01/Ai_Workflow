# Execution Engine — Low-Level Design

Target blueprint for `services/execution-engine`. When prose and `contracts/` disagree, **contracts win**.

This document is **as-built plus locked Target**. Root [design/LLD.md](../LLD.md) §10 defers here.

## 1. Technical baseline

| Concern | Choice |
| --- | --- |
| Language | Python 3.12+ |
| API | FastAPI health only |
| Runtime | Custom **interpreter/walker** + PostgreSQL checkpointer (`thread_id = run_id`). Not LangGraph. Not a compiled StateGraph. |
| Models | Pydantic v2 aligned to JSON Schema + shared fixtures |
| Messaging | aio-pika; durable queues; DLX `aiw.dead.v1` bound on command queues |
| DB | async PostgreSQL (`ee.*` checkpoints, inbox, leases, definitions, action keys). Vector tables are **rag-owned**; EE reads only. |
| HTTP | httpx + hard timeouts + SSRF guards |
| Objects | S3-compatible (MinIO) for artifacts |
| Tooling | uv, Ruff, Pyright, pytest |

## 2. Package layout (as-built)

```text
src/ai_workflow/
|-- api/           # health
|-- config/        # settings, limits, logging
|-- contracts/     # schema/Pydantic wrappers
|-- messaging/     # topology, consumers, publisher, inbox
|-- runtime/       # walker, IR cache, state, bindings, semantic, checkpoint, cancel, lease
|-- nodes/         # executors by category
|-- rag/           # retrieve only (read-only copy of rag schema access)
|-- security/      # credentials, redaction, ssrf, service_auth
|-- tasks/         # durable task framework + domain executors
|-- providers/     # OpenAI-compatible chat/embedding
`-- worker/        # execution_worker, task_worker
```

Lower layers must not import worker or api.

## 3. Locked decisions

### 3.1 Interpreter, not compiler

The walker interprets a validated definition. **WorkflowIR** is an in-process cache of adjacency, bindings, caps, and `definition_hash`. It is not an executable compiled graph.

### 3.2 Resume ownership

- Parent run waits with `HUMAN` or `TASK`.
- **Only `execution.resume` continues the walker.**
- Task-worker never calls `run_workflow`.
- Thin adapter: execution-worker consumes `task.completed` / `task.failed` from `aiw.task.results.v1` and issues the matching `resume_workflow` (same process, not a second resume path from control-plane). Control-plane must **not** also send `execution.resume` for the same TASK interrupt.
- `execution.resume` does not carry the workflow definition; the worker loads it from `ee.workflow_definitions` by hash (fallback: legacy checkpoint `runtime._definition`).

### 3.3 Per-run lease and inbox

- One walker owns a `run_id` at a time (`ee.run_leases`).
- Inbox reclaim TTL is **greater than** `AIW_MAX_RUN_SECONDS` (or reclaim only after lease expiry). Never reclaim a live walk at 60s.
- Inbox `failed` is distinct from `completed`. Reclaim of `failed` is allowed only for retryable publish failures, not for terminal `WorkflowRunError` after `execution.failed` was published.
- In-flight command handlers are bounded by a semaphore matching QoS prefetch.

### 3.4 Cancel

Cancel is durable in `ee.run_cancels`. Nodes and the walker must observe cancel across processes (DB poll or lease-backed event), not only an in-memory lambda on the worker that consumed `execution.cancel`.

### 3.5 Artifacts

Workers write artifacts to MinIO (in-memory store is tests only). Collect overflow **strips** bulk arrays from the node output and leaves `summary` + `artifact_ref`.

### 3.6 HTTP idempotency

Side-effect key is `run_id:node_id` (plus `item_key` inside for-each). **Retry `attempt` is not part of the key.** Attempt is stored as metadata.

### 3.7 For-each bodies (F14)

Forbidden inside a `control.for-each@1` body (semantic validation):

- `human.approval@1`, `human.review@1`
- `control.for-each@1`, `control.loop@1`
- any `execution_mode=durable-task` node

Item-body execution shares the walker’s retry and output-validation helper. Nested map / human-in-map requires sharing the full walker (future).

### 3.8 Durable nodes

Until a `DurableTaskExecutor` is registered, semantic validation **rejects** `execution_mode=durable-task`. After F15, durable nodes dispatch `task.start` and interrupt with `TASK`.

### 3.9 Tenancy

`workspace_id` and `project_id` come from the command envelope. Missing tenant IDs **fail closed**. Never substitute `workflow_id`.

### 3.10 Caps and budgets

Workflow `execution_policy` may tighten platform caps, never raise them. Enforce `min(policy, AIW_MAX_*)` for loop, fan-out, node executions, parallel nodes, run seconds, task budgets.

Run deadline = `min(policy.timeout_seconds, AIW_MAX_RUN_SECONDS)` from start. Expiry emits `execution.failed` with status **`TIMED_OUT`** (or dedicated timed-out payload if the contract adds it; until then `status: FAILED` / code `TIMED_OUT`).

### 3.11 Redaction

- **Events and logs:** redact secrets.
- **Checkpoints:** persist unredacted run state (needed for resume). No credential plaintext in `node_outputs`. Access-control the `ee` schema.
- Size limits apply to the serialized checkpoint envelope.

### 3.12 Control-flow handlers

Ordinary nodes: `NodeExecutor` only — adding `ai.*` / `market.*` is catalog + executor + register, **zero walker edits**.

`ControlFlowHandler` (runtime, not a graph compiler) is for types that are not “execute → write ports → follow edges”: `control.for-each@1` (and future durable dispatch / parallel-join). **`control.loop@1` is a normal node** (`body` / `done` ports). `data.output@1` is a walker completion rule (exactly one output node).

## 4. Core protocols

```python
class NodeExecutor(Protocol):
    node_type: str

    async def execute(
        self, context: ExecutionContext, config: dict, inputs: dict
    ) -> NodeResult: ...


class DurableTaskExecutor(Protocol):
    task_type: str

    async def run(
        self,
        context: TaskContext,
        payload: dict,
        checkpoint: TaskCheckpoint | None,
    ) -> TaskResult: ...


class ControlFlowHandler(Protocol):
    node_type: str

    async def after_node(
        self, *, node, result, state, scheduler, workflow, registry, run_id
    ) -> None: ...
```

`ExecutionContext`: tenant/run/node IDs, attempt, cancel check, deadline, idempotency key (`run_id:node_id` or `run_id:node_id:item_key`), credential resolver. No raw DB sessions.

## 5. Registry

Map `type@majorVersion` → manifest, `default_bindings`, executor factory, optional `ControlFlowHandler`.

Startup **fails** if:

- Duplicate type registration
- Inline catalog node (execution-engine owned) missing executor
- Executor missing catalog manifest
- Durable node missing `DurableTaskExecutor` when F15 is enabled (`strict_catalog` includes tasks)

## 6. Configuration / limits

Fail fast on missing env; log **names only**.

| Family | Examples |
| --- | --- |
| Connectivity | `AIW_DATABASE_URL`, `AIW_RABBITMQ_URL`, `AIW_MINIO_*`, `AIW_CONTROL_PLANE_INTERNAL_URL` |
| Auth | `AIW_INTERNAL_AUTH_*` |
| Caps | `AIW_MAX_GRAPH_NODES`, `AIW_MAX_LOOP_ITERATIONS`, `AIW_MAX_RUN_SECONDS`, `AIW_MAX_FAN_OUT_ITEMS`, `AIW_MAX_TASK_*` |
| Role | `AIW_SERVICE_ROLE` = `execution-api` \| `execution-worker` \| `task-worker` (entrypoint refuses mismatch) |

## 7. Run path

1. Validate definition (schema + semantic).
2. Persist document in `ee.workflow_definitions` keyed by `definition_hash`; cache WorkflowIR in-process.
3. Acquire `ee.run_leases` for `run_id`.
4. Build `WorkflowState`; resolve bindings at execute time.
5. Walk ready nodes; retry `TransientNodeError` with a **stable** action key.
6. Validate outputs against catalog port schemas.
7. Checkpoint versioned envelope after each node.
8. For-each handler runs bounded item bodies; collect injects items.
9. Durable node → `task.start` + `WAITING/TASK`.
10. Human node → `WAITING/HUMAN`.
11. Deadline / cancel → terminal.
12. Ack only after durable inbox + checkpoint + event obligations.

### Checkpoint envelope

```text
{
  schema_version,      # integer; migrate_checkpoint(old) -> current
  definition_hash,
  scheduler,
  interrupt,
  foreach,
  node_outputs,
  loop_iterations,
  task_refs,
  runtime              # run_input, tenant ids, collect inject — not a junk drawer
}
```

v0 (unversioned blob with `_scheduler` / `_definition` / `_interrupt` in `runtime`) migrates on load.

### State

```python
class WorkflowState:
    node_outputs: dict[str, dict]
    loop_iterations: dict[str, int]
    task_refs: dict[str, str]
    runtime: dict
```

Loop counters update `state.loop_iterations` explicitly (no aliasing via `_loop_iterations`).

## 8. Command handling

### `execution.start`

Inbox claim → lease → `execution.started` → run or continue from checkpoint → waiting/completed/failed/cancelled → mark inbox.

### `execution.resume`

Load definition by hash; match interrupt id + reason (`HUMAN`/`TASK`) + `approval_id`/`task_id`; apply decision to node outputs; continue walker.

### `execution.cancel`

Persist cancel; cancel child tasks; emit `execution.cancelled` when the walker stops or if already waiting.

### Documents

Owned by `services/rag` (`document.ingest` / `document.delete`). EE does not ingest.

### Tasks

`task.start` / `task.cancel` on **task-worker**. Progress/completion on events + `aiw.task.results.v1` for parent resume.

## 9. Event sequencing

- Monotonic `sequence` per run starting at 1.
- Commands always `sequence: null`.
- Redact before publish.
- Target: worker outbox (allocate sequence + persist payload, then publish). Until outbox exists, publish is best-effort after checkpoint.

## 10. Starter nodes

| Type | Notes |
| --- | --- |
| `data.input@1` / `data.output@1` | Validate against workflow I/O schemas |
| `control.condition@1` | Pure AST eval → named branches |
| `control.merge@1` | Explicit field mappings |
| `control.loop@1` | `body`/`done` ports; platform cap |
| `control.for-each@1` / `control.collect@1` | Bounded items; restricted bodies |
| `ai.prompt-template@1` | Substitution only |
| `ai.chat-model@1` | OpenAI-compatible; slot `provider` |
| `rag.retrieve@1` | Mandatory ownership filters; read-only |
| `human.approval@1` / `human.review@1` | One interrupt per invoke |
| `action.http-request@1` | SSRF, timeouts, stable action key |
| `market.*@1` | Inline; unimplemented placeholder until F16 |
| `research.deep-research@1` | Durable task (F15+) |
| `action.cleanup-*@1` | Durable task (F15+) |

## 11. RAG

**Ingest:** `services/rag` only.

**Retrieve:** EE `rag.retrieve@1` embeds query and reads `rag.*` with workspace/project/dataset/active filters.

## 12. Outbound HTTP

Parse URL → scheme allowlist → resolve DNS → reject private/metadata → timeouts → revalidate redirects → bound bytes → allowlist headers → redact → persist action key (`run_id:node_id`[+item]).

## 13. Storage ownership

| Store | Content |
| --- | --- |
| `ee.workflow_checkpoints` | Versioned walker state |
| `ee.workflow_definitions` | Immutable definition by hash |
| `ee.run_leases` | Exclusive run ownership |
| `ee.worker_inbox` | Command idempotency |
| `ee.run_sequences` | Event sequence |
| `ee.run_cancels` | Cooperative cancel |
| `ee.action_execution_keys` | HTTP idempotency |
| `ee.task_checkpoints` | Durable task item state |
| `rag.*` | Vectors — **rag service writes**; EE reads |
| MinIO | Artifacts (workers write) |
| Never | Spring `users`, drafts, credentials ciphertext |

## 14. Security

- Credentials only via control-plane resolve.
- Redact events and logs.
- No browser routes.
- Cleanup only typed connectors + unchanged approved plan hash (F16).

## 15. Tests

| Layer | Focus |
| --- | --- |
| Unit | Registry, bindings, IR, loop limits, interrupts, SSRF, redaction, for-each forbid list, action keys without attempt, checkpoint migrate |
| Contract | Shared fixtures |
| Integration | Lease vs reclaim, checkpoint resume, RabbitMQ redelivery, task item restart, MinIO artifact refs |

## 16. Implementation order

See [BUILD-GUIDE.md](./BUILD-GUIDE.md).
