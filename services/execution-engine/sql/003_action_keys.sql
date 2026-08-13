CREATE TABLE IF NOT EXISTS ee.action_execution_keys (
    run_id UUID NOT NULL,
    node_id UUID NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    fingerprint TEXT NOT NULL,
    response JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, node_id, attempt)
);

CREATE INDEX IF NOT EXISTS idx_action_keys_run ON ee.action_execution_keys (run_id);
