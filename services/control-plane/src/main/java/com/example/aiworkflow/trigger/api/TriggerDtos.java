package com.example.aiworkflow.trigger.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.UUID;

public final class TriggerDtos {

    private TriggerDtos() {}

    public record CreateTriggerRequest(
            @NotBlank String type,
            @NotBlank @Size(max = 255) String name,
            @NotNull UUID workflowVersionId,
            JsonNode config) {}

    public record PatchTriggerRequest(String status, UUID workflowVersionId, JsonNode config) {}

    public record TriggerResponse(
            UUID triggerId,
            UUID workflowId,
            UUID workflowVersionId,
            String type,
            String name,
            String status,
            JsonNode config,
            UUID publicId,
            String secret,
            Instant createdAt,
            Instant updatedAt) {}
}
