package com.example.aiworkflow.trigger.api;

import com.example.aiworkflow.trigger.application.TriggerService;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class WebhookController {

    private final TriggerService triggers;

    public WebhookController(TriggerService triggers) {
        this.triggers = triggers;
    }

    @PostMapping("/hooks/v1/{publicId}/{secret}")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, UUID> handle(
            @PathVariable UUID publicId,
            @PathVariable String secret,
            @org.springframework.web.bind.annotation.RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
            @RequestBody(required = false) JsonNode body) {
        UUID runId = triggers.handleWebhook(publicId, secret, body, idempotencyKey);
        return Map.of("runId", runId);
    }
}
