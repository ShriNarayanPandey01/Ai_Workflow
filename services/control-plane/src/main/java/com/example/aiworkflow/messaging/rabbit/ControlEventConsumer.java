package com.example.aiworkflow.messaging.rabbit;

import com.example.aiworkflow.execution.application.ExecutionProjector;
import com.example.aiworkflow.messaging.MessagingNames;
import com.example.aiworkflow.messaging.envelope.EnvelopeValidator;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "aiw.messaging", name = "enabled", havingValue = "true")
public class ControlEventConsumer {

    private static final Logger log = LoggerFactory.getLogger(ControlEventConsumer.class);

    private final EnvelopeValidator envelopes;
    private final ExecutionProjector projector;

    public ControlEventConsumer(EnvelopeValidator envelopes, ExecutionProjector projector) {
        this.envelopes = envelopes;
        this.projector = projector;
    }

    @RabbitListener(queues = MessagingNames.CONTROL_EVENTS_QUEUE, ackMode = "AUTO")
    public void onMessage(Message message) {
        String body = new String(message.getBody());
        JsonNode envelope;
        try {
            envelope = envelopes.parse(body);
        } catch (RuntimeException ex) {
            log.warn("poison message: not json");
            nackToDlq();
            return;
        }
        List<String> errors = envelopes.validate(envelope);
        String type = envelope.path("message_type").asText("");
        if (!errors.isEmpty() || type.isBlank()) {
            log.warn("poison envelope type={} errors={}", type, errors.size());
            nackToDlq();
            return;
        }
        ExecutionProjector.Result result = projector.apply(envelope);
        if (result == ExecutionProjector.Result.UNKNOWN || result == ExecutionProjector.Result.INVALID) {
            log.warn("quarantine/unknown message type={}", type);
            nackToDlq();
        }
    }

    private static void nackToDlq() {
        throw new org.springframework.amqp.AmqpRejectAndDontRequeueException("dlq");
    }
}
