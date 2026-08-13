package com.example.aiworkflow.execution.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface NodeExecutionRepository extends JpaRepository<NodeExecutionEntity, UUID> {

    List<NodeExecutionEntity> findByExecutionIdOrderByStartedAtAsc(UUID executionId);

    Optional<NodeExecutionEntity> findByExecutionIdAndNodeIdAndAttempt(UUID executionId, UUID nodeId, int attempt);
}
