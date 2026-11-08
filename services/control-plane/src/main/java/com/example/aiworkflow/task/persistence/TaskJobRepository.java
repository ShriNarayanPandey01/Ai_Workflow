package com.example.aiworkflow.task.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TaskJobRepository extends JpaRepository<TaskJobEntity, UUID> {

    List<TaskJobEntity> findByExecutionIdAndProjectIdOrderByCreatedAtDesc(UUID executionId, UUID projectId);

    Optional<TaskJobEntity> findByIdAndProjectId(UUID id, UUID projectId);
}
