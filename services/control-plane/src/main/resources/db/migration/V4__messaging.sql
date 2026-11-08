CREATE TABLE outbox_messages (
    id UUID PRIMARY KEY,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id UUID NOT NULL,
    message_type VARCHAR(128) NOT NULL,
    routing_key VARCHAR(128) NOT NULL,
    payload_json JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_outbox_status_available ON outbox_messages (status, available_at);

CREATE TABLE consumed_messages (
    consumer_name VARCHAR(64) NOT NULL,
    message_id UUID NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (consumer_name, message_id)
);

CREATE INDEX ix_consumed_messages_consumed_at ON consumed_messages (consumed_at);
