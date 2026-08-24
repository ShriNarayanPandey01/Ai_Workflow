# AI Workflow Platform — Architecture & Design Pack

Welcome to the authoritative engineering documentation for the **AI Workflow Platform**.

This pack defines the complete system architecture, public APIs, execution runtime, data ownership boundaries, and messaging topology for all platform services.

---

## 🗺️ System Document Map

```
design/
├── README.md                      # Index, Golden Invariants & Navigation (This file)
├── HLD.md                         # Complete System High-Level Design
│                                  # (Topology, Interactions, Data Ownership, Messaging, Wiring)
├── control-plane/
│   ├── LLD.md                     # Authoritative Control Plane LLD (Spring Boot, APIs, DDL, Security)
│   └── FEATURES.md                # Control Plane Feature Specs & Acceptance Criteria
├── execution-engine/
│   ├── LLD.md                     # Authoritative Execution Engine LLD (Walker, Checkpoints, Tasks, Nodes)
│   └── FEATURES.md                # Execution Engine Feature Specs & Acceptance Criteria
└── rag/
    └── README.md                  # RAG Worker, Ingestion Pipeline & pgvector Specs
```

| Document | Purpose & Scope | Primary Audience |
|---|---|---|
| 🏛️ **[HLD.md](./HLD.md)** | **System High-Level Design:** Container topology, cross-service sequence flows, RabbitMQ messaging topology, PostgreSQL schema ownership, hybrid graph wiring, and SSRF security. | All Engineers & Architects |
| ☕ **[control-plane/LLD.md](./control-plane/LLD.md)** | **Control Plane Low-Level Design:** Java 21 / Spring Boot vertical slices, REST endpoints (`/api/v1/**`), Flyway DDL (`public.*`), Quartz clustered scheduler, Outbox publisher, and SSE streaming projector. | Backend (Java) Engineers |
| 📋 **[control-plane/FEATURES.md](./control-plane/FEATURES.md)** | **Control Plane Acceptance Criteria:** Feature-by-feature acceptance criteria and test invariants for the control plane. | Java Engineers & QA |
| 🐍 **[execution-engine/LLD.md](./execution-engine/LLD.md)** | **Execution Engine Low-Level Design:** Python 3.12+ custom DAG walker, `ee.workflow_checkpoints` state machine, distributed run leases, 6-pass semantic validator, durable task workers, and SSRF filtering. | Backend (Python) Engineers |
| 📋 **[execution-engine/FEATURES.md](./execution-engine/FEATURES.md)** | **Execution Engine Acceptance Criteria:** Feature-by-feature acceptance criteria and test invariants for the execution plane. | Python Engineers & QA |
| 🔍 **[rag/README.md](./rag/README.md)** | **RAG Service Design:** Ingestion pipeline (`rag-worker`), text extraction, chunking, OpenAI embeddings, and `rag.*` pgvector storage. | Python / AI Engineers |
| 📜 **[`contracts/`](../contracts/)** | **Canonical JSON Schemas:** Single source of truth for workflow definitions, node manifests, broker commands, and event payloads. | All Engineers |

---

## 🛡️ The 7 Golden Architectural Invariants

1. **Single Public Backend:** The browser communicates *exclusively* with the Spring Boot Control Plane (`/api/v1`, `/hooks/v1`). Python workers, databases, RabbitMQ, and MinIO are strictly private.
2. **Contract-First Authority:** JSON Schemas in `contracts/` win over prose when shapes disagree.
3. **Strict Schema Ownership:** Each service writes *only* to its owned database schema:
   - `public.*` &rarr; Control Plane (Flyway)
   - `ee.*` &rarr; Execution Engine (`ee.workflow_checkpoints`, `ee.worker_inbox`, `ee.run_leases`)
   - `rag.*` &rarr; RAG Service (`rag.rag_document_versions`, `rag.rag_chunks`)
4. **Secrets by Reference:** Persisted graphs and broker messages carry *credential IDs*, never secret values. Workers resolve credentials on-demand via the Control Plane against the run's frozen definition snapshot.
5. **At-Least-Once Delivery & Idempotency:** All RabbitMQ commands and event projectors use database-backed idempotency tables and transaction outbox/inbox guarantees.
6. **AST-Driven Control Flow:** Conditions use a validated Abstract Syntax Tree (AST); loops are explicit, bounded, and budgeted. No arbitrary code execution (`eval`/`exec`).
7. **Dual-Validation Defense:** Graphs are validated by both the Control Plane (pre-publish / pre-run) and the Execution Plane (pre-execution).
