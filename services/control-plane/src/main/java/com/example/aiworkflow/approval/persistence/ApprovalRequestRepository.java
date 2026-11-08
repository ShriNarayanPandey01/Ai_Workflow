package com.example.aiworkflow.approval.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ApprovalRequestRepository extends JpaRepository<ApprovalRequestEntity, UUID> {

    Optional<ApprovalRequestEntity> findByInterruptId(UUID interruptId);

    Optional<ApprovalRequestEntity> findByIdAndExecutionId(UUID id, UUID executionId);

    List<ApprovalRequestEntity> findByProjectIdAndStatusOrderByCreatedAtDesc(UUID projectId, String status);

    List<ApprovalRequestEntity> findByStatusOrderByCreatedAtDesc(String status);
}
