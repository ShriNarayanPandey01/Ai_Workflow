package com.example.aiworkflow.workflow.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface WorkflowVersionRepository extends JpaRepository<WorkflowVersionEntity, UUID> {

    List<WorkflowVersionEntity> findByWorkflowIdOrderByVersionNumberDesc(UUID workflowId);

    Optional<WorkflowVersionEntity> findByWorkflowIdAndVersionNumber(UUID workflowId, int versionNumber);

    Optional<WorkflowVersionEntity> findByIdAndWorkflowId(UUID id, UUID workflowId);

    @Query(
            value = "SELECT COUNT(*) > 0 FROM workflow_versions WHERE definition_json::text LIKE CONCAT('%', :credentialId, '%')",
            nativeQuery = true)
    boolean definitionReferencesCredential(@Param("credentialId") String credentialId);
}
