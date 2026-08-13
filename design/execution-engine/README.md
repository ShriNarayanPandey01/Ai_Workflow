# Execution Engine — Developer Entry

**Code:** `services/execution-engine`  
**Stack:** Python 3.12+, FastAPI (health), custom walker + PostgreSQL checkpointer, aio-pika, asyncpg, httpx, MinIO client, uv

## Purpose

Internal runtime that **interprets** (does not compile) neutral workflow definitions, runs AI/control/RAG/human/action nodes, emits ordered events, and processes durable heavy tasks. Never exposed to browsers.

## Process roles (one codebase)

| Process | Role |
| --- | --- |
| `execution-api` | Liveness/readiness only — no execute-over-HTTP |
| `execution-worker` | Consume start/resume/cancel; run the walker; coordinate task dispatch/resume |
| `task-worker` | Consume heavy `task.*` commands; item checkpoints; progress; artifacts |

Document ingest/delete is owned by the separate **`services/rag`** worker (`rag-worker`), not execution-worker.

Scale workers independently by queue depth.

## Boundaries

**Does**

- Re-validate contracts; cache WorkflowIR by `definition_hash`; execute via registry and resolved input bindings
- Checkpoint durability and interrupts (`HUMAN` / `TASK`)
- Publish ordered events; redact secrets
- Resolve credentials via control-plane internal API
- Scoped RAG **retrieve** (`rag.retrieve@1`) against the shared `rag` schema (read-only)
- Bounded heavy tasks (research, screening, cleanup)

**Does not**

- Own identity, drafts, triggers, or credential ciphertext
- Write Spring platform tables
- Ingest documents or write vector tables (owned by `services/rag`)
- Arbitrary user code, shell, or host FS
- Trade execution or unrestricted cleanup

## Docs in this folder

| Doc | Contents |
| --- | --- |
| [LLD.md](./LLD.md) | As-built + locked Target: walker, IR, nodes, storage |
| [FEATURES.md](./FEATURES.md) | Feature checklist |
| [BUILD-GUIDE.md](./BUILD-GUIDE.md) | Ordered implementation steps |

## Related

- [Service interactions](../01-service-interactions.md)
- [Contracts](../02-shared-contracts.md)
- [Messaging](../03-messaging.md)
- [Data ownership](../04-data-ownership.md)

## Dependency direction

```text
worker / api
  → messaging, runtime, tasks
    → nodes, rag, contracts, security
      → config
```

Lower layers must not import worker or api.
