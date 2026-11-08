-- Keep the latest revision even after unpausing so delayed messages cannot
-- reactivate an earlier pause request.
CREATE TABLE IF NOT EXISTS ee.run_pause_requests (
    run_id UUID PRIMARY KEY,
    pause_id UUID NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0),
    requested BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
