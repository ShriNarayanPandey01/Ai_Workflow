# RAG Service — Agent Guide

Python 3.12+ document ingestion and vector storage service. Responsible for downloading document artifacts, text extraction, semantic chunking, generating vector embeddings, and managing `rag.*` schema storage.

---

## 1. Authoritative Documentation Map (Reference Method)

Before modifying code in this service, refer to the authoritative documents below:

| Document | Path | Purpose & When to Read |
|---|---|---|
| **RAG Service Design** | [design/rag/README.md](../../design/rag/README.md) | **Primary technical blueprint**: Ingestion pipeline flow, chunking strategy, Gemini embeddings, `rag.*` DDL & pgvector indexes, and idempotency inbox protocol. |
| **System High-Level Design** | [design/HLD.md](../../design/HLD.md) | **System topology**: Cross-service interaction flows, MinIO download intents, RabbitMQ broker topology, and service boundaries. |
| **Shared Contracts** | [contracts/README.md](../../contracts/README.md) | **Canonical JSON schemas**: Ingestion commands (`document.ingest.v1`, `document.delete.v1`) and event schemas (`document.ingestion.*.v1`). |
| **Local Run Guide** | [README.md](./README.md) | Local environment startup, boundaries, process roles, and tests. |

---

## 2. Core Architectural Invariants & Boundaries

1. **Schema Ownership (`rag.*`)**:
   - Owns `rag.rag_document_versions`, `rag.rag_chunks`, and vector indexes (`ivfflat` / cosine similarity).
   - Only this service executes vector schema migrations and writes vector chunks.
   - Never writes to `public.*` or `ee.*`.
2. **Private Service**:
   - Never exposed to browsers or public networks.
   - Communicates solely via RabbitMQ commands (`aiw.ingestion.commands.v1`), events (`aiw.events.v1`), and MinIO object storage.
3. **Workflow Retrieval Separation**:
   - `services/rag` handles **ingestion and deletion**.
   - During workflow execution, the `rag.retrieve@1` node runs **in-process inside `execution-engine`** directly querying `rag.*` in read-only mode to eliminate network hops.
   - A copy of the retriever lives under `src/ai_workflow_rag/store/retriever.py` for testing and administrative queries; keep query logic aligned with `execution-engine`.
4. **Idempotent Ingestion**:
   - All inbound commands (`document.ingest`, `document.delete`) must be deduplicated using `rag.worker_inbox`. Duplicate deliveries must acknowledge without re-running embedding compute.
5. **Two Process Roles**:
   - `rag-api`: FastAPI health (`/actuator/health/liveness`) and readiness probes (`/actuator/health/readiness`).
   - `rag-worker`: Asynchronous consumer on queue `aiw.ingestion.commands.v1`.

---

## 3. Package Layout

```text
src/ai_workflow_rag/
├── api/           # FastAPI health & readiness probes
├── config/        # Environment settings and logging configuration
├── health/        # Database and broker probe checks
├── messaging/     # RabbitMQ topology, envelope codecs, inbox deduplication
├── pipeline/      # Document download, text extraction, semantic chunking, and embedding
├── providers/     # Gemini gemini-embedding-001 embeddings
├── security/      # Presigned download intent verification
├── store/         # pgvector schema queries and document store
└── worker/        # Entrypoint for rag-worker background process
```

---

## 4. Development & Verification Commands

Run from `services/rag`:

```powershell
# Sync dependencies
uv sync

# Run tests
uv run pytest
```
