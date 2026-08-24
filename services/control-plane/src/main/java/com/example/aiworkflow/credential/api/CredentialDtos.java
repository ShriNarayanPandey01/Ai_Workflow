package com.example.aiworkflow.credential.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public final class CredentialDtos {

    private CredentialDtos() {}

    public record CreateCredentialRequest(
            @NotBlank @Size(max = 64) String type,
            @NotBlank @Size(max = 255) String name,
            @NotNull JsonNode data) {}

    public record UpdateCredentialRequest(
            @Size(max = 255) String name, JsonNode data) {}

    public record CredentialResponse(
            UUID credentialId,
            UUID projectId,
            String type,
            String name,
            String maskedHint,
            String keyId,
            Instant createdAt,
            Instant updatedAt) {}

    public record ResolveRequest(UUID nodeId, List<String> slots, UUID workflowVersionId) {}

    public record ResolveResponse(
            UUID runId,
            UUID nodeId,
            @com.fasterxml.jackson.annotation.JsonProperty("credentials") JsonNode credentials) {

        @com.fasterxml.jackson.annotation.JsonProperty("secrets")
        public JsonNode secrets() {
            return credentials;
        }
    }
}
