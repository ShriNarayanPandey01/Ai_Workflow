package com.example.aiworkflow.auth.persistence;

import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface WorkspaceRepository extends JpaRepository<WorkspaceEntity, UUID> {

    Optional<WorkspaceEntity> findByOwnerUserIdAndKind(UUID ownerUserId, String kind);
}
