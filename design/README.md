# Design Docs — Backend Services

Developer-facing design pack for building the **AI Workflow Platform** backend services. Frontend/web is intentionally out of scope here.

## What we are building

A visual AI workflow platform where authenticated users create, validate, publish, trigger, monitor, pause, and resume workflows.

| Layer | Technology | Role |
| --- | --- | --- |
| Control plane | Java 21 + Spring Boot | Sole public API, identity, workflows, credentials, triggers, run read models |
| Execution plane | Python + FastAPI + durable walker | Interpret and run workflows, retrieve RAG, heavy tasks |
| RAG worker | Python (`services/rag`) | Document ingest/delete and vector writes |
| Broker | RabbitMQ | Durable commands and events (at-least-once) |
| Database | PostgreSQL + pgvector | Platform records, checkpoints, vectors (separate schemas) |
| Objects | MinIO | Documents and large artifacts |

Canonical product and system docs live in **this folder**. Wire formats live under [`contracts/`](../contracts/). Use this pack for day-to-day implementation.

## Document map

| Doc | Use when |
| --- | --- |
| [00-system-overview.md](./00-system-overview.md) | You need the big picture and service boundaries |
| [01-service-interactions.md](./01-service-interactions.md) | You need to know how services talk and who owns a flow |
| [02-shared-contracts.md](./02-shared-contracts.md) | You touch workflow JSON, manifests, or message payloads |
| [03-messaging.md](./03-messaging.md) | You publish/consume RabbitMQ commands or events |
| [04-data-ownership.md](./04-data-ownership.md) | You add tables, schemas, or object keys |
| [05-workflow-wiring.md](./05-workflow-wiring.md) | You need edges, ports, input bindings, or data flow between nodes |
| [control-plane/](./control-plane/) | You implement `services/control-plane` |
| [execution-engine/](./execution-engine/) | You implement `services/execution-engine` |
| [HLD.md](./HLD.md) / [LLD.md](./LLD.md) / [plan.md](./plan.md) | Product architecture, APIs, delivery phases |

Ingest/delete is `services/rag` (`rag-worker`). There is no separate rag design pack; see [01-service-interactions.md](./01-service-interactions.md) and `services/rag/README.md`.

## Service packs

### Control plane (`services/control-plane`)

| Doc | Purpose |
| --- | --- |
| [README](./control-plane/README.md) | Entry point and boundaries |
| [LLD](./control-plane/LLD.md) | Packages, services, tables, APIs, algorithms |
| [FEATURES](./control-plane/FEATURES.md) | Feature checklist with acceptance criteria |
| [BUILD-GUIDE](./control-plane/BUILD-GUIDE.md) | Ordered vertical slices to implement |

### Execution engine (`services/execution-engine`)

| Doc | Purpose |
| --- | --- |
| [README](./execution-engine/README.md) | Entry point, process roles |
| [LLD](./execution-engine/LLD.md) | Modules, runtime, nodes, messaging, storage |
| [FEATURES](./execution-engine/FEATURES.md) | Feature checklist with acceptance criteria |
| [BUILD-GUIDE](./execution-engine/BUILD-GUIDE.md) | Ordered vertical slices to implement |

## Hard rules (do not violate)

1. **Browser talks only to Spring.** Python is never public.
2. **Contract-first.** JSON Schema in `contracts/` wins over prose when shapes disagree.
3. **Separate schema ownership.** Never write into another service’s tables.
4. **Secrets by reference.** Credential IDs in graphs/messages; plaintext only via internal resolve.
5. **At-least-once safe.** Every command/event handler is idempotent.
6. **No arbitrary code/cycles.** Conditions are ASTs; loops are explicit and bounded.
7. **Dual validation.** Java and Python both reject invalid graphs before run.

## Sources of truth

| Concern | Source |
| --- | --- |
| Product scope / phases | `design/plan.md` |
| System architecture | `design/HLD.md`, `design/LLD.md` |
| Public HTTP API | `design/LLD.md` §6.3–6.4 |
| Wire formats | `contracts/**` |
| This pack | Target design for backend developers |
