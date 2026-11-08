package com.example.aiworkflow.messaging.outbox;

import com.example.aiworkflow.messaging.MessagingNames;
import com.fasterxml.jackson.databind.JsonNode;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class OutboxWriter {

    private final OutboxMessageRepository outbox;
    private final Clock clock;

    public OutboxWriter(OutboxMessageRepository outbox, Clock clock) {
        this.outbox = outbox;
        this.clock = clock;
    }

    public void enqueue(String aggregateType, UUID aggregateId, String messageType, JsonNode envelope) {
        if ("task.start".equals(messageType)) {
            throw new IllegalStateException("control plane must not publish task.start");
        }
        Instant now = clock.instant();
        OutboxMessageEntity row = new OutboxMessageEntity();
        row.setId(UUID.randomUUID());
        row.setAggregateType(aggregateType);
        row.setAggregateId(aggregateId);
        row.setMessageType(messageType);
        row.setRoutingKey(MessagingNames.routingKey(messageType));
        row.setPayloadJson(envelope.toString());
        row.setStatus("PENDING");
        row.setAttempts(0);
        row.setAvailableAt(now);
        row.setCreatedAt(now);
        outbox.save(row);
    }
}
