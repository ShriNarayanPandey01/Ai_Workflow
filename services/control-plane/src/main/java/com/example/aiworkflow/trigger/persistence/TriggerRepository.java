package com.example.aiworkflow.trigger.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TriggerRepository extends JpaRepository<TriggerEntity, UUID> {

    List<TriggerEntity> findByWorkflowIdOrderByCreatedAtDesc(UUID workflowId);

    Optional<TriggerEntity> findByIdAndWorkflowId(UUID id, UUID workflowId);

    Optional<TriggerEntity> findByPublicId(UUID publicId);
}
