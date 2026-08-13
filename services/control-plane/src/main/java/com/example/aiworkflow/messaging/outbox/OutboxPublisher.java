package com.example.aiworkflow.messaging.outbox;

import com.example.aiworkflow.config.AiwProperties;
import com.example.aiworkflow.messaging.MessagingNames;
import com.example.aiworkflow.observability.AiwMetrics;
import jakarta.persistence.EntityManager;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
@ConditionalOnProperty(prefix = "aiw.messaging", name = "enabled", havingValue = "true")
public class OutboxPublisher {

    private static final Logger log = LoggerFactory.getLogger(OutboxPublisher.class);

    private final EntityManager entityManager;
    private final OutboxMessageRepository outbox;
    private final RabbitTemplate rabbitTemplate;
    private final AiwProperties properties;
    private final AiwMetrics metrics;
    private final Clock clock;

    public OutboxPublisher(
            EntityManager entityManager,
            OutboxMessageRepository outbox,
            RabbitTemplate rabbitTemplate,
            AiwProperties properties,
            AiwMetrics metrics,
            Clock clock) {
        this.entityManager = entityManager;
        this.outbox = outbox;
        this.rabbitTemplate = rabbitTemplate;
        this.properties = properties;
        this.metrics = metrics;
        this.clock = clock;
    }

    @Scheduled(fixedDelayString = "#{T(java.time.Duration).parse('${aiw.messaging.publish-interval:PT2S}').toMillis()}")
    @Transactional
    public void publishBatch() {
        Instant now = clock.instant();
        int batch = properties.messaging().publishBatchSize();
        List<?> claimed = entityManager
                .createNativeQuery(
                        """
                        SELECT id FROM outbox_messages
                        WHERE status = 'PENDING' AND available_at <= :now
                        ORDER BY created_at
                        LIMIT :batch
                        FOR UPDATE SKIP LOCKED
                        """)
                .setParameter("now", now)
                .setParameter("batch", batch)
                .getResultList();
        for (Object rawId : claimed) {
            UUID id = rawId instanceof UUID uuid ? uuid : UUID.fromString(rawId.toString());
            OutboxMessageEntity row = outbox.findById(id).orElse(null);
            if (row == null) {
                continue;
            }
            try {
                Boolean confirmed = rabbitTemplate.invoke(ops -> {
                    ops.convertAndSend(MessagingNames.COMMANDS_EXCHANGE, row.getRoutingKey(), row.getPayloadJson());
                    return ops.waitForConfirms(5_000);
                });
                if (!Boolean.TRUE.equals(confirmed)) {
                    throw new IllegalStateException("broker did not confirm publish");
                }
                row.setStatus("PUBLISHED");
                row.setPublishedAt(clock.instant());
                row.setLastError(null);
                metrics.incrementOutboxPublished();
            } catch (RuntimeException ex) {
                int attempts = row.getAttempts() + 1;
                row.setAttempts(attempts);
                long backoffSeconds = Math.min(300, (long) Math.pow(2, Math.min(attempts, 8)));
                row.setAvailableAt(clock.instant().plus(Duration.ofSeconds(backoffSeconds)));
                row.setLastError(ex.getMessage() == null ? "publish failed" : ex.getMessage());
                log.warn("outbox publish failed id={} attempts={}", id, attempts);
            }
        }
    }
}
