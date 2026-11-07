# Execution Engine (F1–F6)

Python execution plane for the AI Workflow Platform.

## Project layout

```text
services/execution-engine/
├── pyproject.toml
├── README.md
├── Dockerfile
├── .env.example
├── scripts/                  # ops entrypoints (added when needed)
├── sql/                      # database migrations
├── src/
│   └── ai_workflow/          # installable package (src layout)
│       ├── api/
│       │   ├── app.py        # create_app() factory
│       │   ├── deps.py       # FastAPI dependencies
│       │   └── routes/       # APIRouter modules
│       ├── config/
│       │   └── settings.py
│       └── health/
│           └── checks.py     # postgres/rabbit probes (no HTTP)
└── tests/                    # mirrors src package structure
    ├── conftest.py
    ├── api/routes/
    └── config/
```

New packages from the LLD (`contracts/`, `nodes/`, `runtime/`, `messaging/`, `worker/`, etc.) are added **only when their feature is implemented** — no empty stub folders.

### F3 packages (registry)

```text
src/ai_workflow/
├── contracts/
│   ├── common/types.py
│   ├── nodes/manifest.py, catalog_loader.py
│   ├── workflow/          # stub for F2
│   └── messaging/         # stub for F2
├── nodes/base.py          # NodeExecutor protocol
├── tasks/base.py          # DurableTaskExecutor protocol
└── runtime/registry.py    # build_runtime_registry()
```

Catalog manifests load from repo-root `contracts/nodes/catalog/` (`AIW_CONTRACTS_ROOT` override).

### F4 — State and redaction

- `runtime/state.py` — `WorkflowState` with namespaced `node_outputs`
- `security/redaction.py` — redact secrets before checkpoint snapshots

### F5 — In-process runner

Run a linear Input → Output workflow without RabbitMQ:

```python
from ai_workflow.runtime.registry.bootstrap import build_runner_registry
from ai_workflow.runtime.engine.engine import run_workflow

registry = build_runner_registry(contracts_root)
result = await run_workflow(definition, {"order_id": "ord-1"}, registry=registry)
# result.output == {"order_id": "ord-1"}
```

Uses `InMemoryCheckpointer` by default (`thread_id = run_id`). For durable runs, use `PostgresCheckpointer` via the execution worker (F6).

### F6 — Durable execution (Postgres + RabbitMQ)

Docker Compose at repo root provides Postgres, RabbitMQ, `execution-worker`, and `execution-api`:

```powershell
# from repo root
docker compose up -d postgres rabbitmq execution-worker
```

The worker:

1. Applies SQL migrations from `sql/` (`ee.workflow_checkpoints`, `ee.worker_inbox`, `ee.run_sequences`)
2. Consumes `execution.start` from `aiw.execution.commands.v1`
3. Deduplicates by `message_id` via `ee.worker_inbox`
4. Runs workflows with `PostgresCheckpointer` and publishes ordered events to `aiw.events.v1`

Live e2e (control-plane mimic over real Postgres + RabbitMQ; workers run in-process). Covers F5–F12 and F14–F16 except RAG: bindings, merge, loop, live chat, approval/review (including reject and invalid resume), HTTP/SSRF, for-each/collect (including over-cap), cancel, duplicate start, and durable research/cleanup-plan. Excludes `rag.retrieve` and unimplemented market nodes.

```powershell
docker compose up -d postgres rabbitmq
docker compose stop execution-worker task-worker
cd services/execution-engine
# Requires BASETEN_API_KEY in .env (script forces AIW_FAKE_LLM=false)
uv run python scripts/trigger_full_features_workflow.py
uv run python scripts/trigger_combo_workflow.py
```

Do not leave Compose `execution-worker` / `task-worker` running: the script starts in-process consumers and needs exclusive access to the command/result queues.

Integration tests (`pytest -m integration`) require local Postgres on `localhost:5432`.

## F1 — Settings and health

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (for Postgres + RabbitMQ readiness checks against real services)

### Setup

```powershell
cd services/execution-engine
copy .env.example .env
uv sync --extra dev
```

Settings load from `services/execution-engine/.env` via **python-dotenv** on startup (`load_settings()`). Process environment variables take precedence over `.env` values.

Required environment variables:

| Variable | Purpose |
| --- | --- |
| `AIW_DATABASE_URL` | PostgreSQL connection string |
| `AIW_RABBITMQ_URL` | RabbitMQ AMQP URL |
| `AIW_SERVICE_ROLE` | Process role (`execution-api`, `execution-worker`, etc.) |

Platform limits (`AIW_MAX_*`) have defaults; see `.env.example`.

### Run checks

```powershell
uv run ruff check .
uv run pyright
uv run pytest
```

### Run API locally

```powershell
# from repo root
docker compose up -d postgres rabbitmq

cd services/execution-engine
uv run uvicorn ai_workflow.api.app:create_app --factory --host 0.0.0.0 --port 8080
```

Endpoints:

- `GET /actuator/health/liveness` — process alive (no DB/broker required)
- `GET /actuator/health/readiness` — Postgres + RabbitMQ must be reachable

Or via docker-compose (port 8088):

```powershell
docker compose up -d execution-api
curl http://localhost:8088/actuator/health/liveness
curl http://localhost:8088/actuator/health/readiness
```
