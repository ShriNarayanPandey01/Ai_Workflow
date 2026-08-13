package com.example.aiworkflow.auth.persistence;

import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface WorkspaceMembershipRepository
        extends JpaRepository<WorkspaceMembershipEntity, WorkspaceMembershipId> {

    boolean existsByIdWorkspaceIdAndIdUserId(UUID workspaceId, UUID userId);
}
