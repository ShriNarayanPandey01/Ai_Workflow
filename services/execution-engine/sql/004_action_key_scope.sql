-- Re-key action execution keys on an opaque action_key string so idempotency can
-- be scoped per for-each item (…:<item_key>) instead of colliding on the shared
-- (run_id, node_id, attempt) tuple. The old primary key becomes a plain index.
ALTER TABLE ee.action_execution_keys
    ADD COLUMN IF NOT EXISTS action_key TEXT;

-- Backfill existing rows with the legacy attempt-scoped key shape.
UPDATE ee.action_execution_keys
SET action_key = run_id::text || ':' || node_id::text || ':' || attempt::text
WHERE action_key IS NULL;

ALTER TABLE ee.action_execution_keys
    ALTER COLUMN action_key SET NOT NULL;

ALTER TABLE ee.action_execution_keys
    DROP CONSTRAINT IF EXISTS action_execution_keys_pkey;

ALTER TABLE ee.action_execution_keys
    ADD CONSTRAINT action_execution_keys_pkey PRIMARY KEY (action_key);
