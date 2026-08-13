package com.example.aiworkflow.task.persistence;

import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ArtifactRepository extends JpaRepository<ArtifactEntity, UUID> {

    Optional<ArtifactEntity> findByIdAndProjectId(UUID id, UUID projectId);
}
