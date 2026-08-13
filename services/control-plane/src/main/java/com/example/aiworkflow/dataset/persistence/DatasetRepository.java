package com.example.aiworkflow.dataset.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DatasetRepository extends JpaRepository<DatasetEntity, UUID> {

    List<DatasetEntity> findByProjectIdOrderByCreatedAtDesc(UUID projectId);

    Optional<DatasetEntity> findByIdAndProjectId(UUID id, UUID projectId);

    boolean existsByProjectIdAndName(UUID projectId, String name);
}
