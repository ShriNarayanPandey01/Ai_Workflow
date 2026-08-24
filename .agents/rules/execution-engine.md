---
trigger: glob
globs: "services/execution-engine/**,design/execution-engine/**"
description: Python Execution Engine rules (applies strictly and only to services/execution-engine)
---

# Execution Engine — Python Execution Plane Rules

> [!IMPORTANT]
> **Strict Scope:** This rule applies **ONLY** to code within `services/execution-engine/**` (and associated execution engine design docs).  
> **DO NOT** apply these rules to Java/Spring Boot control plane services, frontend code, or rag services.

---

## 1. Development Approach

- Scope: `services/execution-engine`. Authoritative design docs are [`design/execution-engine/LLD.md`](file:///c:/Users/capti/OneDrive/Desktop/FullStack/Latest/frontend/Ai_Workflow/design/execution-engine/LLD.md) and [`design/execution-engine/README.md`](file:///c:/Users/capti/OneDrive/Desktop/FullStack/Latest/frontend/Ai_Workflow/design/execution-engine/README.md).
- Prefer industry-standard, production-proven solutions over custom implementations.
- Before implementing a feature, consider whether an existing standard library module or installed library solves the problem.
- Keep implementations simple, maintainable, and consistent with modern Python backend best practices.

---

## 2. Current-State Guardrails

- The graph execution is a **custom walker** with a PostgreSQL checkpointer (`ee.workflow_checkpoints`, `thread_id = run_id`). **Do not add `langgraph` or write code against a LangGraph `StateGraph`/checkpointer API.**
- Before adding a dependency, check `pyproject.toml` for what's actually installed. Confirmed present: `fastapi`, `aio-pika`, `asyncpg`, `httpx`, `uvicorn`. An S3/MinIO client (`boto3`) is **not** installed yet — do not write imports for it without adding the dependency via `uv add` first and calling it out.

---

## 3. Language & Runtime

- Target **Python 3.12+**. Use modern syntax (`X | None` not `Optional[X]`, `match` where clearer than `if/elif`, `list[str]` not `List[str]`).
- This is an **async-first** service. Any I/O (DB, HTTP, MQ, object storage) must use an async client and be awaited. Never introduce a blocking call (`requests`, sync `psycopg2`, sync `boto3`, `time.sleep`) inside an `async def`; if a sync-only library is unavoidable, wrap it with `asyncio.to_thread`.
- **No bare `except Exception: pass`.** Workflow/task code must let errors surface in a way the checkpointer and event stream can record — swallowing an exception silently breaks resumability.

---

## 4. Workflow Engine (Durable Walker)

- `thread_id` for the checkpointer is always `run_id` — never invent a separate identifier or derive a new one from a sub-step. If a node needs a sub-scope, nest it inside state, don't fork the `thread_id`.
- Checkpointer is PostgreSQL-backed (`ee.workflow_checkpoints`). Nodes must be safe to re-run from a checkpoint (idempotent or explicitly guarded) since the walker resumes from the last checkpoint after a crash/restart.
- Keep node functions small and side-effect-scoped: **one node = one clear unit of work** (call a tool, call a model, transform state). Do not fold multiple external calls into one node purely for convenience — it hurts both retry granularity and observability.

---

## 5. Data Models (Pydantic v2)

- All cross-boundary data (graph state, MQ messages, DB rows returned to callers, HTTP payloads) must be a Pydantic v2 `BaseModel`, not a raw dict.
- Models that correspond to a `contracts/` JSON Schema must be generated from or validated against that schema. If the schema changes, the model changes in the same PR.
- Use `model_config = ConfigDict(...)` (v2 style), not legacy `class Config`. Prefer `field_validator`/`model_validator` over `@validator` (v1, deprecated).

---

## 6. Internal API (FastAPI + Uvicorn)

- FastAPI in this service is **health/readiness only**. Do not add an "execute this workflow" HTTP endpoint — execution is triggered via RabbitMQ commands, not HTTP.
- Keep the API surface minimal: `/health` (liveness) and `/ready` (readiness, checking DB/broker connectivity). No business logic here.

---

## 7. Messaging (RabbitMQ / aio-pika)

- One connection, channel pooling per process — do not open a new connection per message. Use `aio_pika.connect_robust` for auto-reconnect.
- Every consumer needs explicit ack/nack handling; a message must only be acked after the corresponding checkpoint/state write succeeds.
- Set a prefetch count appropriate to the worker's concurrency — don't leave it unbounded.

---

## 8. Database (asyncpg + pgvector)

- Use an async driver/pool (`asyncpg` or an async SQLAlchemy engine) — never a sync `psycopg2` connection anywhere in worker/API code paths.
- Checkpoints and pgvector data share the async pool; do not spin up a second sync connection just for vector queries.
- Any query touching pgvector columns should have an explicit index strategy noted in the migration.

---

## 9. Outbound HTTP (httpx) & SSRF Guards

- Every outbound `httpx` call must set an explicit timeout — no default "wait forever" client. Use a shared `httpx.AsyncClient` per process.
- **SSRF guard is mandatory** for any URL that originates from user/tenant input: validate/resolve the host against an allowlist or block-list of private/internal ranges (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.169.254`, `100.64.0.0/10`) before the request goes out. Re-validate on redirects.

---

## 10. Process Roles — Keep Them Separated

This is one codebase with three distinct roles:
1. **`execution-api`** — FastAPI health/readiness only.
2. **`execution-worker`** — Consumes commands, compiles/runs graphs, emits events.
3. **`task-worker`** — Durable heavy tasks (research, screening, cleanup).

Lower layers and `execution-api` must not import worker-loop code paths (or vice versa) — each process must be startable independently with only the dependencies its role needs.

---

## 11. Tooling & Dependencies

- Dependency management is **uv** — use `uv add` / `uv sync`. Do not run `pip install` or hand-edit `pyproject.toml` dependency lists without running `uv` to keep the lockfile in sync.
- Lint with **Ruff**, type-check with **Pyright**. Code must pass cleanly under both.

---

## 12. Security & Guardrails

- Never disable SSL verification.
- Never bypass SSRF protection.
- Validate all external input against contracts.
- Never execute user-provided Python code directly (`eval`/`exec`).
- Never deserialize untrusted pickle objects.
- Redact secrets, API keys, and bearer tokens recursively before publishing events or writing logs.

---

## 13. Logging Standards

- Use structured logging only.
- Every log emitted during execution must include:
  - `run_id`
  - `correlation_id` (if available)
  - `worker role`
  - `node/task name`
- Never log secrets, API keys, OAuth tokens, or full raw prompts.
- Prefer `INFO` for workflow state transitions, `WARNING` for retries, `ERROR` for failures.

---

## 14. Testing Standards

- Async code is tested with **`pytest-asyncio`**; mark async tests explicitly (`@pytest.mark.asyncio`).
- Mock outbound HTTP with **`respx`** against the shared `httpx.AsyncClient` — do not patch internal `httpx` functions.
- Integration tests against Postgres, RabbitMQ, and MinIO use **Testcontainers**.
- Every workflow/node change must include a test exercising resumability from a checkpoint (crash mid-graph, redeliver, resume) — not just the happy path.
