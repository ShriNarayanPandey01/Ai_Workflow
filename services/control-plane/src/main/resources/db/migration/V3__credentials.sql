CREATE TABLE credentials (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    project_id UUID NOT NULL REFERENCES projects (id),
    type VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    ciphertext BYTEA NOT NULL,
    nonce BYTEA NOT NULL,
    key_id VARCHAR(64) NOT NULL,
    masked_hint VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_credentials_project_name ON credentials (project_id, name);
CREATE INDEX ix_credentials_project_type ON credentials (project_id, type);
CREATE UNIQUE INDEX uq_credentials_nonce ON credentials (nonce);
