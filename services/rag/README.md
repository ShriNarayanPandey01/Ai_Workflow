# RAG Service

**Code:** `services/rag`  
**Stack:** Python 3.12+, FastAPI (health), aio-pika, asyncpg + pgvector, httpx, uv

## Purpose

Owns document ingest/delete: download → extract → chunk → embed → activate vectors in the `rag` PostgreSQL schema. Publishes `document.ingestion.*` events. Never exposed to browsers.

Embeddings use Gemini `gemini-embedding-001` with 1536 dimensions. After changing an embedding model, re-ingest existing documents before retrieval: vectors from different models cannot be compared, even when they have the same dimension.

Workflow retrieval (`rag.retrieve@1`) runs **in-process in execution-engine** against the same `rag` schema (read-only). A matching retrieve/read-side copy lives here for tests and future admin use — keep both copies in sync.

## Process roles

| Process | Role |
| --- | --- |
| `rag-api` | Liveness/readiness only |
| `rag-worker` | Consume `document.ingest` / `document.delete` on `aiw.ingestion.commands.v1` |

## Boundaries

**Does**

- Idempotent ingest/delete with inbox dedupe
- Vector schema migrations (`rag.*`)
- Scoped chunk storage with ownership columns
- Emit ingestion lifecycle events

**Does not**

- Run workflows or consume `execution.*`
- Write Spring platform tables
- Serve browser APIs
