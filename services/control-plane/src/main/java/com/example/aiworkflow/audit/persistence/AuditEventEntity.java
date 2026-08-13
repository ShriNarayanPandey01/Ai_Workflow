package com.example.aiworkflow.audit.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "audit_events")
public class AuditEventEntity {

    @Id
    private UUID id;

    @Column(name = "actor_user_id")
    private UUID actorUserId;

    @Column(name = "workspace_id")
    private UUID workspaceId;

    @Column(name = "project_id")
    private UUID projectId;

    @Column(nullable = false)
    private String action;

    @Column(name = "resource_type", nullable = false)
    private String resourceType;

    @Column(name = "resource_id")
    private UUID resourceId;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "details_json", columnDefinition = "jsonb")
    private String detailsJson;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    public UUID getId() {
        return id;
    }

    public void setId(UUID id) {
        this.id = id;
    }

    public void setActorUserId(UUID actorUserId) {
        this.actorUserId = actorUserId;
    }

    public void setWorkspaceId(UUID workspaceId) {
        this.workspaceId = workspaceId;
    }

    public void setProjectId(UUID projectId) {
        this.projectId = projectId;
    }

    public void setAction(String action) {
        this.action = action;
    }

    public void setResourceType(String resourceType) {
        this.resourceType = resourceType;
    }

    public void setResourceId(UUID resourceId) {
        this.resourceId = resourceId;
    }

    public void setDetailsJson(String detailsJson) {
        this.detailsJson = detailsJson;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }
}
