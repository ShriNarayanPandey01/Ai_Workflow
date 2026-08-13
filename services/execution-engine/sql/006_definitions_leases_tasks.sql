-- Durable definition store, run leases, and task checkpoints.

CREATE TABLE IF NOT EXISTS ee.workflow_definitions (
    definition_hash TEXT PRIMARY KEY,
    document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE ee.workflow_checkpoints
    ADD COLUMN IF NOT EXISTS definition_hash TEXT;

CREATE TABLE IF NOT EXISTS ee.run_leases (
    run_id UUID PRIMARY KEY,
    owner TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_run_leases_expires_at ON ee.run_leases (expires_at);

CREATE TABLE IF NOT EXISTS ee.task_checkpoints (
    task_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    node_id UUID NOT NULL,
    task_type TEXT NOT NULL,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_checkpoints_run_id ON ee.task_checkpoints (run_id);
