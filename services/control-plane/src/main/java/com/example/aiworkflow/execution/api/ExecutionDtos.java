package com.example.aiworkflow.execution.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public final class ExecutionDtos {

    private ExecutionDtos() {}

    public record StartExecutionRequest(
            @NotBlank String mode,
            @NotNull JsonNode input,
            @NotBlank @Size(max = 256) String idempotencyKey,
            UUID workflowVersionId) {}

    public record StartExecutionResponse(UUID runId) {}

    public record ExecutionSummary(
            UUID runId,
            UUID workflowId,
            UUID workflowVersionId,
            String mode,
            String status,
            String waitingReason,
            Instant createdAt,
            Instant updatedAt) {}

    public record NodeExecutionView(
            UUID nodeId, int attempt, String status, JsonNode input, JsonNode output, JsonNode error) {}

    public record ExecutionDetail(
            UUID runId,
            UUID projectId,
            UUID workflowId,
            UUID workflowVersionId,
            String mode,
            String status,
            String waitingReason,
            UUID interruptId,
            JsonNode input,
            JsonNode output,
            int lastSequence,
            String errorCode,
            Instant createdAt,
            Instant updatedAt,
            List<NodeExecutionView> nodes) {}
}
