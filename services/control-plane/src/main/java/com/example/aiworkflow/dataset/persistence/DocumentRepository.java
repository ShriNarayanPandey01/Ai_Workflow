package com.example.aiworkflow.dataset.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DocumentRepository extends JpaRepository<DocumentEntity, UUID> {

    List<DocumentEntity> findByDatasetIdOrderByCreatedAtDesc(UUID datasetId);

    Optional<DocumentEntity> findByIdAndDatasetId(UUID id, UUID datasetId);

    Optional<DocumentEntity> findByIdAndProjectId(UUID id, UUID projectId);
}
