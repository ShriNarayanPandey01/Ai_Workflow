package com.example.aiworkflow.messaging.inbox;

import org.springframework.data.jpa.repository.JpaRepository;

public interface ConsumedMessageRepository extends JpaRepository<ConsumedMessageEntity, ConsumedMessageEntity.Key> {}
