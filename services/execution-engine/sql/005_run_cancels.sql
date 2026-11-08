CREATE TABLE IF NOT EXISTS ee.run_cancels (
    run_id UUID PRIMARY KEY,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
