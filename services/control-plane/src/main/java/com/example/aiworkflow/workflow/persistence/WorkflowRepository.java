package com.example.aiworkflow.workflow.persistence;

import jakarta.persistence.LockModeType;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface WorkflowRepository extends JpaRepository<WorkflowEntity, UUID> {

    Optional<WorkflowEntity> findByIdAndProjectId(UUID id, UUID projectId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select w from WorkflowEntity w where w.id = :id")
    Optional<WorkflowEntity> lockById(@Param("id") UUID id);

    @Query(
            """
            select w from WorkflowEntity w
            where w.projectId = :projectId
              and (:cursorCreatedAt is null
                   or w.createdAt < :cursorCreatedAt
                   or (w.createdAt = :cursorCreatedAt and w.id < :cursorId))
            order by w.createdAt desc, w.id desc
            """)
    List<WorkflowEntity> listPage(
            @Param("projectId") UUID projectId,
            @Param("cursorCreatedAt") Instant cursorCreatedAt,
            @Param("cursorId") UUID cursorId);
}
