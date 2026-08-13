# Execution Engine — Features

This list is what we build in `services/execution-engine`.

Read it like a checklist:
1. Pick a feature (F1 → F16 in order when possible).
2. Build only what that feature lists.
3. Mark it done only when every “Done when” check passes.

Related docs:
- How to build step-by-step → [BUILD-GUIDE.md](./BUILD-GUIDE.md)
- Technical details → [LLD.md](./LLD.md)
- How we talk to other services → [../01-service-interactions.md](../01-service-interactions.md)

---

## Quick map

| ID | Feature | In one sentence |
| --- | --- | --- |
| F1 | Settings and health | Load config safely; expose health checks |
| F2 | Contracts | Accept/reject the same JSON as Java |
| F3 | Registry | Map each node type to one executor |
| F4 | Redaction and state | Hide secrets; keep run state tidy |
| F5 | Input → Output runtime | Smallest real workflow that can run |
| F6 | Start + events | Listen on RabbitMQ; report progress |
| F7 | Control nodes | Branch, merge, and bounded loops |
| F8 | AI nodes | Prompt + chat model calls |
| F9 | Resume / cancel | Survive restarts; stop runs safely |
| F10 | Credentials | Fetch secrets from control plane |
| F11 | Human approval | Pause for a person, then continue |
| F12 | HTTP action | Safe outbound HTTP requests |
| F13 | RAG | Ingest documents; retrieve chunks |
| F14 | For-each / collect | Process a list with limits |
| F15 | Durable tasks | Long jobs with progress and artifacts |
| F16 | Domain tasks | Market screen, research, cleanup |

---

## F1 — Settings and health

**Why:** Every other feature needs config. Bad secrets must never be printed.

**What to build**
- Typed settings object (Pydantic) from env vars
- Platform limits (`AIW_MAX_GRAPH_NODES`, `AIW_MAX_LOOP_ITERATIONS`, `AIW_MAX_RUN_SECONDS`, task limits, etc.)
- FastAPI app with:
  - `GET /actuator/health/liveness` → process alive
  - `GET /actuator/health/readiness` → DB + RabbitMQ OK (for workers)

**Where in code**
- `config/settings.py`
- `api/` (health routes)

**Done when**
- [x] Missing required env var fails startup and names the variable (never the value)
- [x] Liveness does not require DB/broker
- [x] Readiness fails when Postgres or RabbitMQ is down

---

## F2 — Contracts and fixtures

**Why:** Java and Python must agree on workflow JSON and message shapes.

**What to build**
- Validators/models for:
  - workflow definition
  - condition AST
  - message envelope
  - command and event payloads
- Run the shared fixtures under `contracts/fixtures/`

**Where in code**
- `contracts/`

**Done when**
- [x] Every `fixtures/valid/*` file is accepted
- [x] Every `fixtures/invalid/*` file is rejected (runtime-only caps are skipped at schema layer and covered by runner tests)
- [x] Python `tests/contracts/test_fixture_conformance.py` is the shared pass/fail harness; the control plane does not yet run these fixtures

---

## F3 — Registry

**Why:** New nodes should plug in without rewriting the engine.

**What to build**
- `NodeExecutor` protocol (normal nodes)
- `DurableTaskExecutor` protocol (long-running tasks)
- Registry: `type@majorVersion` → manifest + executor + parsed `default_bindings`
- Startup checks that nothing is missing or duplicated

**Where in code**
- `nodes/base.py`, `tasks/base.py`
- `nodes/registry.py` (or `runtime/registry.py`)

**Done when**
- [x] Two executors for the same type → process refuses to start
- [x] Catalog node with no executor → process refuses to start
- [x] Executor with no catalog manifest → process refuses to start

---

## F4 — Redaction and state

**Why:** Secrets must not leak into events, logs, or test snapshots.

**What to build**
- One redaction helper used everywhere before publish/log
- `WorkflowState` with namespaced outputs per node id
- Size limits so huge payloads do not blow up RabbitMQ/SSE

**Where in code**
- `security/redaction.py`
- `runtime/state.py`

**Done when**
- [x] Credential values / auth headers never appear after redaction
- [x] Node outputs are stored under that node’s id (no global name clashes)
- [x] Oversized values are truncated or moved to artifact refs (policy)

---

## F5 — Minimal runtime (Input → Output)

**Why:** Prove the engine can compile and run the smallest useful graph.

**What to build**
- Graph compiler (neutral definition → runnable graph)
- **Binding resolver**: explicit `input_bindings` or inferred pass-through from edges ([../05-workflow-wiring.md](../05-workflow-wiring.md))
- Nodes: `data.input@1`, `data.output@1`
- PostgreSQL checkpointer with `thread_id = run_id` (`ee.workflow_checkpoints`)
- Durable custom walker (not LangGraph)

**Where in code**
- `runtime/runner.py`, `runtime/bindings.py`, `runtime/checkpoint.py`
- `nodes/data/` (input/output)

**Done when**
- [x] A simple Input → Output workflow runs in tests (pass-through inferred from edge when `input_bindings` omitted)
- [x] A checkpoint is written for that run
- [x] Output matches the mapped input

---

## F6 — Messaging: start + events

**Why:** Control plane starts runs over RabbitMQ; UI needs ordered status.

**What to build**
- Consume `execution.start`
- Inbox table/check by `message_id` (ignore duplicates)
- Publish events with sequence `1, 2, 3...` per run
- Ack the RabbitMQ message only after durable work is saved

**Events to emit (minimum)**
- `execution.started`
- `node.started` / `node.completed` / `node.failed`
- `execution.completed` (success) or `execution.failed`

**Where in code**
- `messaging/`
- `worker/execution_worker.py`

**Done when**
- [x] Same `execution.start` delivered twice → only one real run
- [x] Events are ordered and reach the broker
- [x] Worker crash before ack → safe redelivery (idempotent)

---

## F7 — Control nodes

**Why:** Real workflows need branches and bounded loops.

**What to build**

| Node | What it does |
| --- | --- |
| `control.condition@1` | Evaluate a safe condition AST; pick a branch |
| `control.merge@1` | Combine mapped fields from branches |
| `control.loop@1` | Run `body` until exit condition or `maxIterations`; then `done` |

**Rules**
- No `eval` / arbitrary code
- No unlimited loops
- Loop must actually re-enter the body (not a counter stub)

**Done when**
- [x] Shared conditional and loop fixtures run correctly
- [x] Unbounded / illegal cycles are rejected
- [x] Hitting `maxIterations` stops safely (per policy)

---

## F8 — AI nodes

**Why:** Core product value — prompt building and model calls.

**What to build**

| Node | What it does |
| --- | --- |
| `ai.prompt-template@1` | Fill variables into a prompt (no code execution) |
| `ai.chat-model@1` | Call an OpenAI-compatible chat API |

**Testing tip:** Use a fake provider first; add real HTTP later.

**Done when**
- [x] Missing required template variables fail with a clear error
- [x] Chat node returns text + usage metadata (tokens/cost fields as designed)
- [x] Retries only for rate limits / selected transient errors

---

## F9 — Resume / cancel

**Why:** Workers die; users cancel; runs must not get stuck forever.

**What to build**
- Handle `execution.resume`
- Handle `execution.cancel`
- Cooperative cancel: check before each node and after awaits
- Resume from latest checkpoint after process restart

**Done when**
- [x] Kill worker mid-run → new worker resumes same `run_id`
- [x] Cancel moves run to cancelled (terminal)
- [x] Late results from cancelled calls do not continue the graph

---

## F10 — Credentials client

**Why:** Secrets live in the control plane. Workers must not store them in env for every provider.

**What to build**
- Internal HTTP client to:
  `POST /internal/v1/executions/{runId}/credentials:resolve`
- Service authentication (service JWT / shared internal auth)
- Pass secrets into the node call only; then drop them

**Done when**
- [x] Chat/HTTP nodes get secrets for the call lifetime only
- [x] Secrets never appear in logs or events
- [x] Missing/undeclared slots fail safely (no silent empty key)

---

## F11 — Human interrupts

**Why:** Some steps need a person to approve or edit before continuing.

**What to build**

| Node | Behavior |
| --- | --- |
| `human.approval@1` | Pause; wait for approve/reject |
| `human.review@1` | Pause; wait for edited value |

**Rules**
- Exactly **one** interrupt per node invocation
- Emit `execution.waiting` with reason `HUMAN`
- Resume only via matching `execution.resume`

**Done when**
- [x] No auto-approve stub left
- [x] Run stays waiting across worker restart
- [x] Wrong/missing decision does not resume

---

## F12 — HTTP action

**Why:** Workflows call external APIs, but must not attack internal networks (SSRF).

**What to build**
- Node `action.http-request@1`
- Allow only HTTP/HTTPS and configured methods
- DNS/IP checks; block private/link-local/metadata addresses
- Re-check every redirect target
- Timeouts, max response size, header redaction
- Stable execution key so retries do not double-call when possible

**Done when**
- [x] Requests to localhost / private IPs are blocked in tests
- [x] Redirect to private IP is blocked
- [x] Duplicate delivery does not create a second side effect when key exists

---

## F13 — RAG ingest + retrieve

**Why:** Workflows answer from project documents.

**What to build**
- **RAG microservice** (`services/rag`): commands `document.ingest`, `document.delete`; pipeline download → extract → chunk → embed → save vectors
- **Execution-engine**: node `rag.retrieve@1` (query → top chunks) with a **read-only copy** of retrieve/store code against the same `rag` schema

**Rules**
- Always filter by workspace + project + dataset + active version
- Partial vector writes must never become “active”
- Only the RAG service writes vectors; execution-engine is read-only on `rag.*`

**Done when (execution-engine retrieve)**
- [x] Project A cannot retrieve Project B data

**Done when (rag-worker ingest — owned by `services/rag`, not this checklist’s runtime)**
- [x] Same ingest command twice is idempotent (rag-worker)
- [x] Failed mid-ingest does not leave an active bad index (rag-worker)

---

## F14 — For-each / collect

**Why:** Process a list of items without exploding the system.

**What to build**

| Node | Role |
| --- | --- |
| `control.for-each@1` | Run a subflow per item (bounded size + concurrency) |
| `control.collect@1` | Gather successes/failures/skipped into one result |

**Config ideas**
- `maxItems`, `concurrency`, item timeout
- `failFast` vs continue-on-error

**Done when**
- [x] More items than the platform cap is rejected or truncated per policy
- [x] Each item has a stable key (restart-safe)
- [x] Collect output includes counts and failure summaries

---

## F15 — Durable task framework

**Why:** Research/cleanup jobs are too long for a normal node call.

**What to build**
- Separate `task-worker` process
- Commands: `task.start`, `task.cancel`
- Per-item checkpoints, progress events, budgets (time, calls, tokens, bytes)
- Large results stored in MinIO as artifacts (events carry refs only)
- Parent run waits with reason `TASK`, then resumes with typed result

**Done when**
- [x] Parent enters `WAITING` with reason `TASK`
- [x] Restart skips already completed items
- [x] Cancel stops between items / at await points
- [x] Oversized output is an artifact reference, not a huge queue message

---

## F16 — Domain tasks

**Why:** Product-specific heavy features on top of F15.

**What to build**

| Feature | Nodes | Must guarantee |
| --- | --- | --- |
| Market data | `market.price-history@1` | Freshness/coverage metadata |
| Momentum screen | `market.momentum-screen@1` | Deterministic score + `asOf`; **no trades** |
| Deep research | `research.deep-research@1` | Sources, citations, budgets |
| Cleanup | `action.cleanup-plan@1`, `action.cleanup-execute@1` | Dry-run plan hash; execute only unchanged approved plan |

**Done when**
- [ ] Same market inputs → same ranking (formula version recorded)
- [ ] Research claims map to source ids; unsupported claims flagged
- [ ] Cleanup cannot run without matching plan hash + approval path
- [ ] No shell / arbitrary filesystem cleanup path exists

---

## What we will NOT build here

- Public HTTP API to start/run workflows (browser uses control plane only)
- Writing Spring/control-plane tables
- Loading untrusted plugins or user-supplied Python
- Placing brokerage orders
- Generic “delete anything on the host” cleanup
- Frontend UI

---

## Catalog rule (important)

Only register node types that exist in `contracts/nodes/catalog/`.

If you add a new node:
1. Add the catalog JSON
2. Add fixtures if needed
3. Add the executor in the same change

Do not keep long-lived custom node types that are missing from the catalog.
