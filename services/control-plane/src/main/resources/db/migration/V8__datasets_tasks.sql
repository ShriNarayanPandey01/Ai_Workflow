CREATE TABLE datasets (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    project_id UUID NOT NULL REFERENCES projects (id),
    name VARCHAR(255) NOT NULL,
    embedding_config_json JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_datasets_project_name ON datasets (project_id, name);
CREATE INDEX ix_datasets_project ON datasets (project_id);

CREATE TABLE documents (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    project_id UUID NOT NULL REFERENCES projects (id),
    dataset_id UUID NOT NULL REFERENCES datasets (id),
    object_key VARCHAR(1024) NOT NULL,
    original_name VARCHAR(512),
    media_type VARCHAR(128) NOT NULL,
    size_bytes BIGINT NOT NULL,
    content_hash VARCHAR(64),
    version INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(128),
    chunk_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_documents_object_key ON documents (object_key);
CREATE INDEX ix_documents_dataset_status ON documents (dataset_id, status);

CREATE TABLE task_jobs (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    project_id UUID NOT NULL REFERENCES projects (id),
    execution_id UUID NOT NULL REFERENCES executions (id),
    node_id UUID,
    task_type VARCHAR(128),
    status VARCHAR(32) NOT NULL,
    waiting_reason VARCHAR(16),
    stage VARCHAR(128),
    total_items INTEGER NOT NULL DEFAULT 0,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    skipped_items INTEGER NOT NULL DEFAULT 0,
    percent NUMERIC,
    usage_json JSONB,
    warnings_json JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_task_jobs_execution_task ON task_jobs (execution_id, id);
CREATE INDEX ix_task_jobs_project_status ON task_jobs (project_id, status);
CREATE INDEX ix_task_jobs_execution ON task_jobs (execution_id);

CREATE TABLE task_items (
    id UUID PRIMARY KEY,
    task_job_id UUID NOT NULL REFERENCES task_jobs (id),
    item_key VARCHAR(256) NOT NULL,
    status VARCHAR(32) NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    result_json JSONB,
    error_json JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_task_items_job_key ON task_items (task_job_id, item_key);
CREATE INDEX ix_task_items_job_status ON task_items (task_job_id, status);

CREATE TABLE artifacts (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    project_id UUID NOT NULL REFERENCES projects (id),
    execution_id UUID REFERENCES executions (id),
    task_job_id UUID REFERENCES task_jobs (id),
    kind VARCHAR(64) NOT NULL,
    object_key VARCHAR(1024) NOT NULL,
    media_type VARCHAR(128),
    size_bytes BIGINT,
    sha256 VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_artifacts_object_key ON artifacts (object_key);
CREATE INDEX ix_artifacts_project ON artifacts (project_id, created_at DESC);
