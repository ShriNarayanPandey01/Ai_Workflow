package com.example.aiworkflow.credential.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface CredentialRepository extends JpaRepository<CredentialEntity, UUID> {

    List<CredentialEntity> findByProjectIdOrderByCreatedAtDesc(UUID projectId);

    Optional<CredentialEntity> findByIdAndProjectId(UUID id, UUID projectId);

    boolean existsByProjectIdAndName(UUID projectId, String name);

    boolean existsByProjectIdAndNameAndIdNot(UUID projectId, String name, UUID id);
}
