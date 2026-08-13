package com.example.aiworkflow.messaging.outbox;

import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface OutboxMessageRepository extends JpaRepository<OutboxMessageEntity, UUID> {

    List<OutboxMessageEntity> findByMessageType(String messageType);
}
