# Execution Engine — Build Guide

Ordered vertical slices for `services/execution-engine`. Tests first; hermetic fakes for network/broker/providers; ≥80% coverage on changed code.

**Prereqs:** Python 3.12+, `uv`, Docker, repo-root `contracts/`.

Working directory: `services/execution-engine`.

---

## Step 0 — Scaffold

```powershell
uv sync
# layout from LLD package tree
uv run ruff check .
uv run pyright
uv run pytest
```

Entrypoints: API module, `execution_worker`, later `task_worker`.

## Step 1 — Settings and limits

Pydantic settings for DB, broker, MinIO, control-plane URL, service auth, all `AIW_MAX_*`. Fail fast with variable **names**.

## Step 2 — Contracts

Models/validators from JSON Schema. Run shared fixtures (valid + invalid) identically to Java expectations.

## Step 3 — Registry + protocols

`NodeExecutor`, `DurableTaskExecutor`, fail-fast startup validation.

## Step 4 — Redaction + state

`security/redaction.py` first (tested). `WorkflowState` namespacing. Size limits.

## Step 5 — Minimal walker + Input/Output

Interpret Input→Output with binding resolver (pass-through inference); PostgreSQL checkpointer; in-process run test. Cache WorkflowIR by `definition_hash` (not a compiled StateGraph).

## Step 5b — Explicit input bindings (Phase 2)

`runtime/bindings.py`; validate required bindings; fixture with field-level maps (e.g. form field → prompt variable).

## Step 6 — Messaging backbone

Inbox by `message_id`; consume `execution.start`; publish sequenced events; ack rules from [../03-messaging.md](../03-messaging.md).

**Done:** redelivered start does not double-execute side effects.

## Step 7 — Condition / Merge / Loop

AST evaluator; merge mappings; real loop body scheduling + caps. Use contract fixtures as golden graphs.

## Step 8 — Prompt + Chat

Fake provider via `respx`/fakes; then real OpenAI-compatible adapter behind interface.

## Step 9 — Cancel + resume commands

Cancellation registry; resume path with interrupt id; restart recovery test (kill process, resume thread).

## Step 10 — Credential resolver client

Service JWT/assertion to control-plane; wire into Chat/HTTP nodes.

## Step 11 — Human Approval / Review

`WorkflowInterrupt`; emit `execution.waiting`; **no** auto-approve.

## Step 12 — HTTP action + SSRF

Full algorithm from LLD; negative tests for localhost/metadata/private ranges.

## Step 13 — RAG

Ingest/delete live in **`services/rag`** (dedicated worker on `aiw.ingestion.commands.v1`).  
Execution-engine implements `rag.retrieve@1` with mandatory ownership filters (read-only copy of retrieve SQL). Isolation + idempotent ingest + no-active-on-partial-fail tests.

## Step 14 — For-each / Collect

Bounds, concurrency, partial failure, stable item keys.

## Step 15 — Task worker framework

Dedicated queue/consumer; budgets; item checkpoints; progress coalescing; artifact upload; parent resume contract.

## Step 16 — Domain executors

Momentum (deterministic), deep research (citations/budgets), cleanup plan/execute (plan hash + connectors).

## Step 17 — Hardening

DLQ, metrics, OTel context on messages, retention hooks, non-root image, dual entrypoint docs.

---

## Verification

```powershell
uv run ruff check .
uv run pyright
uv run pytest --cov=ai_workflow --cov-fail-under=80
```

Integration: Testcontainers for Postgres/RabbitMQ/MinIO as slices require.

## Definition of done for a slice

- [ ] Feature tests green
- [ ] Contract fixtures still pass
- [ ] Redaction verified for new payloads
- [ ] Idempotent under redelivery
- [ ] Marked complete in [FEATURES.md](./FEATURES.md)

## Honest baseline note

The runtime is the custom walker plus PostgreSQL checkpointer (`ee.workflow_checkpoints`, `thread_id = run_id`). Do not introduce LangGraph. Bind the registry to catalog manifests; human nodes use `WorkflowInterrupt` with no auto-approve stub. Authoritative design: [LLD.md](./LLD.md) in this folder.
