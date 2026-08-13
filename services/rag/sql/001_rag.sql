-- RAG vector schema (owned by services/rag).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS rag;

CREATE TABLE IF NOT EXISTS rag.worker_inbox (
    message_id UUID PRIMARY KEY,
    document_id UUID NOT NULL,
    message_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_worker_inbox_document_id
    ON rag.worker_inbox (document_id);

CREATE TABLE IF NOT EXISTS rag.rag_document_versions (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL,
    project_id UUID NOT NULL,
    dataset_id UUID NOT NULL,
    document_id UUID NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[a-f0-9]{64}$'),
    status TEXT NOT NULL CHECK (status IN ('ingesting', 'ready', 'failed', 'inactive')),
    media_type TEXT NOT NULL,
    original_name TEXT,
    chunking_config_hash TEXT NOT NULL,
    embedding_config_hash TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version)
);

CREATE INDEX IF NOT EXISTS idx_rag_versions_ownership
    ON rag.rag_document_versions (workspace_id, project_id, dataset_id, document_id);

CREATE INDEX IF NOT EXISTS idx_rag_versions_dataset_status
    ON rag.rag_document_versions (dataset_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_versions_ready_hash
    ON rag.rag_document_versions (document_id, version, content_hash)
    WHERE status = 'ready';

CREATE TABLE IF NOT EXISTS rag.rag_chunks (
    id UUID PRIMARY KEY,
    document_version_id UUID NOT NULL REFERENCES rag.rag_document_versions (id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL,
    project_id UUID NOT NULL,
    dataset_id UUID NOT NULL,
    document_id UUID NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0 CHECK (token_count >= 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_version_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_ownership
    ON rag.rag_chunks (workspace_id, project_id, dataset_id, document_id);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_version
    ON rag.rag_chunks (document_version_id);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw
    ON rag.rag_chunks
    USING hnsw (embedding vector_cosine_ops);
