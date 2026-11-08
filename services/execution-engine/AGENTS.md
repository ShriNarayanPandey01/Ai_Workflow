# Execution Engine — Agent Guide

Python 3.12+ execution plane for the AI Workflow Platform. Implements graph compilation, custom deterministic DAG walking, state checkpoints, durable task execution, and event generation.

---

## 1. Authoritative Documentation Map (Reference Method)

Before modifying code in this service, refer to the authoritative documents below:

| Document | Path | Purpose & When to Read |
|---|---|---|
| **Execution Engine LLD** | [design/execution-engine/LLD.md](../../design/execution-engine/LLD.md) | **Primary technical blueprint**: Custom interpreter/walker, `ee.workflow_checkpoints` state machine, distributed run leases, 6-pass semantic validator, task workers, and SSRF filtering. |
| **Execution Engine Features** | [design/execution-engine/FEATURES.md](../../design/execution-engine/FEATURES.md) | **Acceptance criteria (F1–F16)**: Acceptance tests, edge cases, pause/resume behavior, loop caps, human-in-the-loop review nodes, and failure semantics. |
| **Python Standards & Rules** | [.agents/rules/execution-engine.md](../../.agents/rules/execution-engine.md) | **Execution plane rules**: Strict async-first standards, no LangGraph prohibition, Pydantic v2 models, SSRF guards, logging formats, and test patterns. |
| **System High-Level Design** | [design/HLD.md](../../design/HLD.md) | **System topology**: Container topology, RabbitMQ exchange/queue bindings, schema ownership, and cross-service sequence flows. |
| **Shared Contracts** | [contracts/README.md](../../contracts/README.md) | **Canonical JSON schemas**: Single source of truth for workflow definitions, node manifests, message envelopes, commands, and events. |
| **Local Run Guide** | [README.md](./README.md) | Setup instructions, uv commands, local script triggers, and integration test setup. |

---

## 2. Core Architectural Invariants & Boundaries

1. **Custom Interpreter / Walker (NOT LangGraph)**: The graph execution engine uses a custom interpreter and DAG walker with a PostgreSQL checkpointer (`ee.workflow_checkpoints`, `thread_id = run_id`). **Never introduce LangGraph or write code against `StateGraph` APIs.**
2. **Schema Ownership (`ee.*`)**: This service owns the `ee.*` PostgreSQL schema (`ee.workflow_checkpoints`, `ee.worker_inbox`, `ee.run_leases`). It never writes to `public.*` or `rag.*`. Note: For workflow retrieval (`rag.retrieve@1`), it reads from `rag.*` in-process with read-only access.
3. **Process Roles**: One codebase powers three distinct runtime roles:
   - `execution-api`: FastAPI health/readiness probes (`/actuator/health/liveness`, `/actuator/health/readiness`). Never serves public traffic or execution triggers.
   - `execution-worker`: Consumes commands (`execution.start`, `execution.cancel`, `execution.resume`) from `aiw.execution.commands.v1`, compiles and executes graphs, and publishes ordered events to `aiw.events.v1`.
   - `task-worker`: Consumes heavy durable tasks (`task.start`, `task.cancel`) from `aiw.task.commands.v1`.
4. **Async-First & Blocking I/O Ban**: Target Python 3.12+. Any I/O (DB, HTTP, RabbitMQ, S3) must use an async client (`asyncpg`, `httpx`, `aio-pika`). Never use blocking calls (`time.sleep`, `requests`, sync `psycopg2`) inside async code.
5. **SSRF Filtering Mandatory**: Outbound HTTP requests (`httpx`) targeting user-supplied URLs must resolve and validate against internal/private IP blocks before connecting and on every redirect.
6. **No Arbitrary Code Execution**: Control-flow conditions use a validated Abstract Syntax Tree (AST); loops are bounded and budgeted. Never use `eval` or `exec`.
7. **Secrets Recursive Redaction**: Secrets, API keys, and bearer tokens must be recursively redacted before publishing events or persisting checkpoints.

---

## 3. Package Layout

```text
src/ai_workflow/
├── api/           # FastAPI health & readiness probes
├── config/        # Pydantic settings, limits, and structured logging
├── contracts/     # Pydantic v2 models generated from /contracts schemas
├── messaging/     # RabbitMQ topology, envelope codecs, publisher, consumer inbox
├── nodes/         # Node executors (action, ai, control, human, rag)
├── providers/     # ZenMux OpenAI-compatible chat and Gemini embedding clients
├── rag/           # In-process vector retrieval against rag.* schema
├── runtime/       # Custom DAG walker, IR cache, state, bindings, validator, checkpointer, leases
├── security/      # Service auth tokens, SSRF validator, recursive redaction
├── tasks/         # Durable task framework & background workers
└── worker/        # CLI entrypoints for execution-worker and task-worker
```

---

## 4. Development & Verification Commands

Run from `services/execution-engine`:

```powershell
# Install dependencies with uv
uv sync --extra dev

# Code style and type checking
uv run ruff check .
uv run pyright

# Run test suite
uv run pytest

# Run integration tests (requires local PostgreSQL)
uv run pytest -m integration
```
