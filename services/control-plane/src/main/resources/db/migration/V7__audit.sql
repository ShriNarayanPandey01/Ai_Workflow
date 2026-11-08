CREATE TABLE audit_events (
    id UUID PRIMARY KEY,
    actor_user_id UUID,
    workspace_id UUID,
    project_id UUID,
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id UUID,
    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_audit_workspace_created ON audit_events (workspace_id, created_at DESC);
CREATE INDEX ix_audit_resource ON audit_events (resource_type, resource_id);
