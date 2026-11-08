CREATE TABLE executions (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    project_id UUID NOT NULL REFERENCES projects (id),
    workflow_id UUID NOT NULL REFERENCES workflows (id),
    workflow_version_id UUID REFERENCES workflow_versions (id),
    mode VARCHAR(16) NOT NULL,
    status VARCHAR(32) NOT NULL,
    waiting_reason VARCHAR(16),
    interrupt_id UUID,
    input_json JSONB NOT NULL,
    output_json JSONB,
    definition_json JSONB NOT NULL,
    draft_revision INTEGER,
    idempotency_key VARCHAR(256) NOT NULL,
    last_sequence INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(128),
    quarantined BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_executions_project_idempotency ON executions (project_id, idempotency_key);
CREATE INDEX ix_executions_project_created ON executions (project_id, created_at DESC);
CREATE INDEX ix_executions_status_updated ON executions (status, updated_at);

CREATE TABLE node_executions (
    id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES executions (id),
    node_id UUID NOT NULL,
    attempt INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    input_json JSONB,
    output_json JSONB,
    error_json JSONB,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    estimated_cost NUMERIC
);

CREATE UNIQUE INDEX uq_node_executions_run_node_attempt ON node_executions (execution_id, node_id, attempt);
CREATE INDEX ix_node_executions_run_status ON node_executions (execution_id, status);

CREATE TABLE execution_events (
    id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES executions (id),
    sequence INTEGER NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    payload_json JSONB NOT NULL,
    message_id UUID NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_execution_events_run_sequence ON execution_events (execution_id, sequence);
CREATE UNIQUE INDEX uq_execution_events_message_id ON execution_events (message_id);
CREATE INDEX ix_execution_events_run_sequence ON execution_events (execution_id, sequence);

CREATE TABLE approval_requests (
    id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES executions (id),
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    project_id UUID NOT NULL REFERENCES projects (id),
    node_id UUID,
    interrupt_id UUID NOT NULL,
    status VARCHAR(32) NOT NULL,
    request_json JSONB,
    decision_json JSONB,
    resolved_by UUID REFERENCES users (id),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_approval_requests_interrupt ON approval_requests (interrupt_id);
CREATE INDEX ix_approval_requests_pending ON approval_requests (status, created_at);
CREATE INDEX ix_approval_requests_execution ON approval_requests (execution_id);
