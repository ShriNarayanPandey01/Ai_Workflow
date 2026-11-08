package com.example.aiworkflow.execution.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ExecutionEventRepository extends JpaRepository<ExecutionEventEntity, UUID> {

    List<ExecutionEventEntity> findByExecutionIdAndSequenceGreaterThanOrderBySequenceAsc(UUID executionId, int sequence);

    Optional<ExecutionEventEntity> findByMessageId(UUID messageId);

    boolean existsByExecutionIdAndSequence(UUID executionId, int sequence);
}
