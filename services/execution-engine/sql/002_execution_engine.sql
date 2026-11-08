CREATE SCHEMA IF NOT EXISTS ee;

CREATE TABLE IF NOT EXISTS ee.schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ee.workflow_checkpoints (
    thread_id UUID PRIMARY KEY,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ee.worker_inbox (
    message_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    message_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_worker_inbox_run_id ON ee.worker_inbox (run_id);

CREATE TABLE IF NOT EXISTS ee.run_sequences (
    run_id UUID PRIMARY KEY,
    last_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence >= 0)
);
