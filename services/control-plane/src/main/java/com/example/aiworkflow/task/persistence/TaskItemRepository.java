package com.example.aiworkflow.task.persistence;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface TaskItemRepository extends JpaRepository<TaskItemEntity, UUID> {

    Optional<TaskItemEntity> findByTaskJobIdAndItemKey(UUID taskJobId, String itemKey);

    @Query(
            """
            SELECT i FROM TaskItemEntity i
            WHERE i.taskJobId = :taskJobId
              AND (:afterCreatedAt IS NULL OR i.createdAt < :afterCreatedAt
                OR (i.createdAt = :afterCreatedAt AND i.id < :afterId))
            ORDER BY i.createdAt DESC, i.id DESC
            """)
    List<TaskItemEntity> listPage(
            @Param("taskJobId") UUID taskJobId,
            @Param("afterCreatedAt") Instant afterCreatedAt,
            @Param("afterId") UUID afterId,
            org.springframework.data.domain.Pageable pageable);
}
