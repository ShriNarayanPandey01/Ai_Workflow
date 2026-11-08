## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

---

## 5. System Documentation Map (Reference Method)

All authoritative system architecture, specifications, and low-level designs reside in dedicated markdown files. When working on any part of the platform, consult the relevant authoritative documents:

| Document | Path | Scope & Purpose |
|---|---|---|
| **System High-Level Design** | [design/HLD.md](design/HLD.md) | **Global Architecture**: System topology, cross-service interactions, RabbitMQ exchange/queue bindings, schema ownership, and SSRF security. |
| **Architecture Index** | [design/README.md](design/README.md) | **Index & Invariants**: Navigation across all design packs and the 7 Golden Architectural Invariants. |
| **Shared Contracts** | [contracts/README.md](contracts/README.md) | **Canonical Contracts**: JSON Schema authority, broker routing keys, identifiers, and casing rules (`camelCase` vs `snake_case`). |
| **Contract Fixtures** | [contracts/fixtures/README.md](contracts/fixtures/README.md) | **Cross-Language Test Fixtures**: Valid/invalid JSON definitions and semantic validation rules. |
| **Control Plane LLD** | [design/control-plane/LLD.md](design/control-plane/LLD.md) | **Java 21 / Spring Boot**: Vertical slices, REST endpoints (`/api/v1/**`), Flyway migrations, Quartz scheduler, Outbox/Inbox. |
| **Control Plane Features** | [design/control-plane/FEATURES.md](design/control-plane/FEATURES.md) | **Control Plane Acceptance Criteria**: F1–F16 feature specs, RBAC rules, versioning semantics, and test invariants. |
| **Java Production Rules** | [.agents/rules/java-production.md](.agents/rules/java-production.md) | **Java Standards**: DTO records, constructor injection, no JPA entities in controllers, custom executors. |
| **Execution Engine LLD** | [design/execution-engine/LLD.md](design/execution-engine/LLD.md) | **Python Execution Plane**: Custom DAG walker/interpreter, `ee.workflow_checkpoints`, distributed run leases, semantic validator. |
| **Execution Engine Features** | [design/execution-engine/FEATURES.md](design/execution-engine/FEATURES.md) | **Execution Plane Acceptance Criteria**: F1–F16 execution criteria, checkpointer semantics, retry, pause/resume, and loop caps. |
| **Python Execution Rules** | [.agents/rules/execution-engine.md](.agents/rules/execution-engine.md) | **Python Standards**: No LangGraph rule, async-first I/O, Pydantic v2, SSRF protection, process role boundaries. |
| **RAG Service Design** | [design/rag/README.md](design/rag/README.md) | **RAG Pipeline**: MinIO download, chunking, Gemini embeddings, `rag.*` pgvector storage, and inbox deduplication. |
| **Web Frontend Guide** | [apps/web/README.md](apps/web/README.md) | **React / Vite Workbench**: Development server, proxy configuration (`/api` -> `8080`), and UI build commands. |

---

## 6. Sub-Service Agent Guides

Each service and application contains its own scoped `AGENTS.md` guide with localized instructions, package layouts, commands, and rules:

| Component | Path | Language / Stack | Primary Role |
|---|---|---|---|
| **Control Plane** | [services/control-plane/AGENTS.md](services/control-plane/AGENTS.md) | Java 21 / Spring Boot | Sole public REST API (`/api/v1`), identity, projects, catalog, Quartz scheduler, transactional outbox. |
| **Execution Engine** | [services/execution-engine/AGENTS.md](services/execution-engine/AGENTS.md) | Python 3.12+ / asyncpg / aio-pika | Custom DAG walker, state checkpoints (`ee.*`), command worker, heavy task worker, SSRF guards. |
| **RAG Service** | [services/rag/AGENTS.md](services/rag/AGENTS.md) | Python 3.12+ / pgvector / aio-pika | Private document ingestion, extraction, chunking, embeddings, and vector storage (`rag.*`). |
| **Web Frontend** | [apps/web/AGENTS.md](apps/web/AGENTS.md) | React 19 / TypeScript / Vite | Graph canvas builder (`@xyflow/react`), run inspector, approvals, and credential UI. |

---

## 7. The 7 Golden Architectural Invariants

Every agent working on this codebase must adhere strictly to these platform invariants:

1. **Single Public Backend**: The browser communicates *exclusively* with the Spring Boot Control Plane (`/api/v1`, `/hooks/v1`). Python workers, databases, RabbitMQ, and MinIO are strictly private.
2. **Contract-First Authority**: JSON Schemas in `contracts/` win over prose or implementation code when shapes disagree.
3. **Strict Schema Ownership**: Each service writes *only* to its owned database schema:
   - `public.*` &rarr; Control Plane (Flyway)
   - `ee.*` &rarr; Execution Engine (`ee.workflow_checkpoints`, `ee.worker_inbox`, `ee.run_leases`)
   - `rag.*` &rarr; RAG Service (`rag.rag_document_versions`, `rag.rag_chunks`)
4. **Secrets by Reference**: Persisted graphs and broker messages carry credential IDs, never secret values. Resolving secrets happens on-demand via the Control Plane against frozen snapshots.
5. **At-Least-Once Delivery & Idempotency**: All RabbitMQ commands and event projectors use database-backed idempotency tables and transaction outbox/inbox guarantees.
6. **AST-Driven Control Flow**: Conditions use a validated Abstract Syntax Tree (AST); loops are explicit, bounded, and budgeted. No arbitrary code execution (`eval`/`exec`).
7. **Dual-Validation Defense**: Graphs are validated by both the Control Plane (pre-publish / pre-run) and the Execution Plane (pre-execution).
