# Service Interactions

How backend services collaborate. Frontend is out of scope; it only calls the control plane.

## Interaction matrix

| From → To | Mechanism | Purpose |
| --- | --- | --- |
| Client → control-plane | HTTPS REST `/api/v1`, SSE, `/hooks/v1` | All product operations |
| control-plane → RabbitMQ | Outbox publish to `aiw.commands.v1` | `execution.start` / `execution.cancel` / HUMAN `execution.resume` / `document.ingest` / `document.delete` / user `task.cancel` (never `task.start`) |
| RabbitMQ → execution-worker | Queue `aiw.execution.commands.v1` | Run graphs, resume, cancel |
| RabbitMQ → rag-worker | Queue `aiw.ingestion.commands.v1` | Document ingest/delete, vector writes |
| RabbitMQ → task-worker | Queue `aiw.task.commands.v1` | Heavy jobs |
| execution / task workers → RabbitMQ | Publish to `aiw.events.v1` | Ordered run/node/task/document events |
| RabbitMQ → control-plane | Queue `aiw.control.events.v1` | Project read models + SSE |
| Workers → control-plane | Internal HTTPS `/internal/v1` | Credential resolve, document download intent |
| Workers → MinIO | S3 API (via signed intents or service creds) | Read docs / write artifacts |
| control-plane → MinIO | Signed upload/download | User uploads, artifact download |
| Workers → providers | HTTPS | Chat, embeddings, market, research, HTTP action |

## Trust boundaries

```mermaid
flowchart LR
    Internet[Untrusted Internet] -->|TLS + rate limits| Proxy[Proxy + control-plane public API]
    Proxy -->|JWT + project authz| App[Application network]
    App -->|least privilege DB users| Data[Postgres / Rabbit / MinIO]
    App -->|egress policy + scoped secrets| Ext[External providers]
```

- Public clients never reach Python or internal endpoints.
- Internal endpoints require service authentication (service JWT / mTLS later).
- Workers never decrypt credentials locally; Spring verifies the **run snapshot** (draft or published) declares the slot, then decrypts.

## Primary flows

### 1. Publish a workflow

```mermaid
sequenceDiagram
    participant CP as Control Plane
    participant DB as Platform DB

    Note over CP: Authorize project
    CP->>CP: Full validation (schema + graph + refs)
    CP->>DB: Lock workflow, insert immutable version
```

Execution plane is not involved until a run starts.

### 2. Start and execute a run

```mermaid
sequenceDiagram
    participant CP as Control Plane
    participant DB as Platform DB
    participant MQ as RabbitMQ
    participant EW as Execution Worker

    CP->>DB: INSERT execution + outbox (one tx)
    CP-->>CP: 202 runId
    CP->>MQ: execution.start
    MQ->>EW: deliver
    EW->>EW: inbox dedup + revalidate + compile + run
    EW->>MQ: ordered events (started, node.*, terminal)
    MQ->>CP: project read model
```

### 3. Human approval resume

```mermaid
sequenceDiagram
    participant EW as Execution Worker
    participant MQ as RabbitMQ
    participant CP as Control Plane

    EW->>MQ: execution.waiting (HUMAN)
    MQ->>CP: persist approval_requests
    CP->>MQ: execution.resume (after authorized decision)
    MQ->>EW: resume same thread_id = run_id
```

`WAITING` reason must match: human decisions cannot resume `TASK` waits and vice versa.

### 4. Document ingest + RAG

```mermaid
sequenceDiagram
    participant CP as Control Plane
    participant Obj as MinIO
    participant MQ as RabbitMQ
    participant EW as RagWorker
    participant V as pgvector schema

    CP-->>CP: signed upload intent
    Note over Obj: client uploads object
    CP->>MQ: document.ingest (outbox)
    MQ->>EW: ingest
    EW->>CP: download-intent (internal)
    EW->>Obj: read bytes
    EW->>V: transactional chunk replace
    EW->>MQ: document.ingestion.*
    MQ->>CP: update document status
```

Retrieval (`rag.retrieve@1`) runs in the execution-engine against the same `rag` schema (read-only).

### 5. Durable heavy task

```mermaid
sequenceDiagram
    participant EW as Execution Worker
    participant MQ as RabbitMQ
    participant TW as Task Worker
    participant CP as Control Plane

    EW->>MQ: task.start
    EW->>EW: checkpoint WAITING/TASK
    MQ->>TW: process items + checkpoints
    TW->>MQ: task.progress / task.completed
    MQ->>CP: task read model + SSE
    MQ->>EW: task.completed on aiw.task.results.v1
    EW->>EW: resume_workflow (TASK) — only resume path
```

**Locked:** only `execution.resume` / in-process `resume_workflow` continues the parent walker. Task-worker never calls `run_workflow`. Execution-worker consumes `aiw.task.results.v1` and resumes. Control-plane must not also send `execution.resume` for the same TASK interrupt.

### 6. Credential use during a node

```mermaid
sequenceDiagram
    participant Node as Node Executor
    participant CP as Control Plane
    participant Prov as Provider

    Node->>CP: POST /internal/v1/executions/{runId}/credentials:resolve
    CP->>CP: verify run snapshot declares slots
    CP-->>Node: plaintext for call lifetime only
    Node->>Prov: authenticated call
    Node->>Node: redact before events/logs
```

## Ownership of failures

| Failure | Owner of response |
| --- | --- |
| Invalid draft / publish | Control plane validation → `422` with field errors |
| Authz / unknown project | Control plane → `403`/`404` |
| Broker down after run commit | Outbox retries until published |
| Duplicate command/event | Consumer inbox / unique constraints → no-op |
| Provider blip | Worker retry policy on node; eventual `node.failed` / run fail |
| Dead-letter | Ops inspect DLQ; create new run (no silent replay into changed graph) |

## Correlation

Every hop should carry:

- `correlation_id` (request/run lineage)
- `causation_id` (parent message)
- `run_id` / `workflow_version_id` when applicable
- `message_id` + `idempotency_key` on broker messages

Logs and traces use the same IDs without secret payloads.
