package com.example.aiworkflow.project.persistence;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ProjectRepository extends JpaRepository<ProjectEntity, UUID> {

    @Query(
            """
            select p from ProjectEntity p
            where p.workspaceId = :workspaceId
              and (:cursorCreatedAt is null
                   or p.createdAt < :cursorCreatedAt
                   or (p.createdAt = :cursorCreatedAt and p.id < :cursorId))
            order by p.createdAt desc, p.id desc
            """)
    List<ProjectEntity> listPage(
            @Param("workspaceId") UUID workspaceId,
            @Param("cursorCreatedAt") Instant cursorCreatedAt,
            @Param("cursorId") UUID cursorId,
            org.springframework.data.domain.Pageable pageable);
}
