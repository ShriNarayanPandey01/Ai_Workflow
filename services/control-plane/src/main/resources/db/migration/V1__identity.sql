CREATE TABLE users (
    id UUID PRIMARY KEY,
    email_normalized VARCHAR(320) NOT NULL,
    password_hash TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_users_email_normalized ON users (email_normalized);
CREATE INDEX ix_users_status ON users (status);

CREATE TABLE workspaces (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    owner_user_id UUID NOT NULL REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_workspaces_personal_owner ON workspaces (owner_user_id) WHERE kind = 'PERSONAL';

CREATE TABLE workspace_memberships (
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    user_id UUID NOT NULL REFERENCES users (id),
    role VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX ix_workspace_memberships_user ON workspace_memberships (user_id);

CREATE TABLE projects (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces (id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_projects_workspace_name ON projects (workspace_id, name);

CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users (id),
    family_id UUID NOT NULL,
    token_hash VARCHAR(128) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    replaced_by_id UUID REFERENCES refresh_tokens (id),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX uq_refresh_tokens_hash ON refresh_tokens (token_hash);
CREATE INDEX ix_refresh_tokens_family ON refresh_tokens (family_id);
CREATE INDEX ix_refresh_tokens_expires ON refresh_tokens (expires_at);
