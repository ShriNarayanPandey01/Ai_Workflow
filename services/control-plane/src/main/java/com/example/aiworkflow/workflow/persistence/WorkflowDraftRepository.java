package com.example.aiworkflow.workflow.persistence;

import java.time.Instant;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface WorkflowDraftRepository extends JpaRepository<WorkflowDraftEntity, UUID> {

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query(
            """
            update WorkflowDraftEntity d
            set d.revision = d.revision + 1,
                d.definitionJson = :definitionJson,
                d.updatedBy = :updatedBy,
                d.updatedAt = :updatedAt
            where d.workflowId = :workflowId and d.revision = :revision
            """)
    int updateIfRevision(
            @Param("workflowId") UUID workflowId,
            @Param("revision") int revision,
            @Param("definitionJson") String definitionJson,
            @Param("updatedBy") UUID updatedBy,
            @Param("updatedAt") Instant updatedAt);

    @Query(
            value = "SELECT COUNT(*) > 0 FROM workflow_drafts WHERE definition_json::text LIKE CONCAT('%', :credentialId, '%')",
            nativeQuery = true)
    boolean definitionReferencesCredential(@Param("credentialId") String credentialId);
}
