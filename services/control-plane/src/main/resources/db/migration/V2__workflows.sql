CREATE TABLE workflows (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    project_id UUID NOT NULL REFERENCES projects (id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    latest_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_workflows_project_name ON workflows (project_id, name);

CREATE TABLE workflow_drafts (
    workflow_id UUID PRIMARY KEY REFERENCES workflows (id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    definition_json JSONB NOT NULL,
    updated_by UUID NOT NULL REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE workflow_versions (
    id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflows (id),
    version_number INTEGER NOT NULL,
    definition_json JSONB NOT NULL,
    definition_hash VARCHAR(64) NOT NULL,
    published_by UUID NOT NULL REFERENCES users (id),
    published_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (workflow_id, version_number)
);
