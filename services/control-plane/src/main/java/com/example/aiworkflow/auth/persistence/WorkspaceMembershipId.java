package com.example.aiworkflow.auth.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import java.io.Serializable;
import java.util.Objects;
import java.util.UUID;

@Embeddable
public class WorkspaceMembershipId implements Serializable {

    @Column(name = "workspace_id")
    private UUID workspaceId;

    @Column(name = "user_id")
    private UUID userId;

    public WorkspaceMembershipId() {}

    public WorkspaceMembershipId(UUID workspaceId, UUID userId) {
        this.workspaceId = workspaceId;
        this.userId = userId;
    }

    public UUID getWorkspaceId() {
        return workspaceId;
    }

    public void setWorkspaceId(UUID workspaceId) {
        this.workspaceId = workspaceId;
    }

    public UUID getUserId() {
        return userId;
    }

    public void setUserId(UUID userId) {
        this.userId = userId;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) {
            return true;
        }
        if (!(o instanceof WorkspaceMembershipId that)) {
            return false;
        }
        return Objects.equals(workspaceId, that.workspaceId) && Objects.equals(userId, that.userId);
    }

    @Override
    public int hashCode() {
        return Objects.hash(workspaceId, userId);
    }
}
