package com.example.aiworkflow.execution.persistence;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ExecutionRepository extends JpaRepository<ExecutionEntity, UUID> {

    Optional<ExecutionEntity> findByIdAndProjectId(UUID id, UUID projectId);

    Optional<ExecutionEntity> findByProjectIdAndIdempotencyKey(UUID projectId, String idempotencyKey);

    @Query(
            """
            SELECT e FROM ExecutionEntity e
            WHERE e.projectId = :projectId
              AND (:afterCreatedAt IS NULL OR e.createdAt < :afterCreatedAt
                OR (e.createdAt = :afterCreatedAt AND e.id < :afterId))
            ORDER BY e.createdAt DESC, e.id DESC
            """)
    List<ExecutionEntity> listPage(
            @Param("projectId") UUID projectId,
            @Param("afterCreatedAt") Instant afterCreatedAt,
            @Param("afterId") UUID afterId);

    @Query(
            value = "SELECT COUNT(*) > 0 FROM executions WHERE definition_json::text LIKE CONCAT('%', :credentialId, '%')",
            nativeQuery = true)
    boolean definitionReferencesCredential(@Param("credentialId") String credentialId);
}
