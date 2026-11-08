# RAG Service — Architecture & Design

**Code Location:** `services/rag`  
**Stack:** Python 3.12+, FastAPI (health probes), `aio-pika`, `asyncpg` + `pgvector`, `httpx`, `uv`

---

## 1. Purpose & Responsibilities

The **RAG Service** (`rag-worker`) owns asynchronous document ingestion and deletion:
1. **Download:** Fetches uploaded source files from MinIO via short-lived download intents.
2. **Extraction & Chunking:** Extracts text (PDF, text, markdown) and splits into semantic chunks with overlap.
3. **Embeddings:** Generates document and retrieval-query vectors with Gemini `gemini-embedding-001` (1536 dimensions, retrieval task types).
   Existing chunks created with another model must be re-ingested; same-sized vectors from different models are not compatible.
4. **Vector Storage:** Persists document metadata and embeddings into the dedicated `rag` PostgreSQL schema.
5. **Lifecycle Events:** Publishes `document.ingestion.started`, `document.ingestion.completed`, and `document.ingestion.failed` events to `aiw.events.v1`.

> [!NOTE]
> **Workflow Retrieval:** Workflow node execution (`rag.retrieve@1`) runs **in-process in the Execution Engine** against the `rag` schema in read-only mode for sub-millisecond query performance.

---

## 2. Process Roles

| Process | Entry Point | Responsibility |
|---|---|---|
| `rag-api` | `src/ai_workflow_rag/api/app.py` | FastAPI liveness (`/health`) and readiness (`/ready`) probes only. Never serves public traffic. |
| `rag-worker` | `src/ai_workflow_rag/worker/main.py` | Consumes `document.ingest` and `document.delete` commands from RabbitMQ queue `aiw.ingestion.commands.v1`. |

---

## 3. Database Schema (`rag.*`)

```sql
-- Document Versions Table
CREATE TABLE IF NOT EXISTS rag.rag_document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    version INT NOT NULL,
    workspace_id UUID NOT NULL,
    project_id UUID NOT NULL,
    status VARCHAR(50) NOT NULL, -- 'PENDING', 'INDEXED', 'FAILED', 'DELETED'
    chunk_count INT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Document Vector Chunks Table
CREATE TABLE IF NOT EXISTS rag.rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id UUID NOT NULL REFERENCES rag.rag_document_versions(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL,
    project_id UUID NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding vector(1536), -- pgvector cosine similarity
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_project ON rag.rag_chunks(workspace_id, project_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding ON rag.rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

## 4. Message Ingestion Protocol

- **Queue:** `aiw.ingestion.commands.v1`
- **Exchange:** `aiw.commands.v1`
- **Routing Keys:** `document.ingest.v1`, `document.delete.v1`

### Idempotency:
- Every message is claimed in `rag.worker_inbox` prior to processing.
- Duplicate message IDs result in an immediate ACK with no redundant compute.
- Deletions mark versions as `DELETED` and purge associated vector chunks atomically.
