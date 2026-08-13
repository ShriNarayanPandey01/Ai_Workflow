package com.example.aiworkflow.messaging.inbox;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;
import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

@Entity
@Table(name = "consumed_messages")
@IdClass(ConsumedMessageEntity.Key.class)
public class ConsumedMessageEntity {

    @Id
    @Column(name = "consumer_name")
    private String consumerName;

    @Id
    @Column(name = "message_id")
    private UUID messageId;

    @Column(name = "consumed_at", nullable = false)
    private Instant consumedAt;

    public String getConsumerName() {
        return consumerName;
    }

    public void setConsumerName(String consumerName) {
        this.consumerName = consumerName;
    }

    public UUID getMessageId() {
        return messageId;
    }

    public void setMessageId(UUID messageId) {
        this.messageId = messageId;
    }

    public Instant getConsumedAt() {
        return consumedAt;
    }

    public void setConsumedAt(Instant consumedAt) {
        this.consumedAt = consumedAt;
    }

    public static class Key implements Serializable {
        private String consumerName;
        private UUID messageId;

        public Key() {}

        public Key(String consumerName, UUID messageId) {
            this.consumerName = consumerName;
            this.messageId = messageId;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) {
                return true;
            }
            if (!(o instanceof Key key)) {
                return false;
            }
            return Objects.equals(consumerName, key.consumerName) && Objects.equals(messageId, key.messageId);
        }

        @Override
        public int hashCode() {
            return Objects.hash(consumerName, messageId);
        }
    }
}
