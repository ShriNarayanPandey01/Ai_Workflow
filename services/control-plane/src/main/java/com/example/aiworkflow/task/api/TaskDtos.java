package com.example.aiworkflow.task.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public final class TaskDtos {

    private TaskDtos() {}

    public record TaskSummary(
            UUID taskId,
            UUID runId,
            UUID nodeId,
            String taskType,
            String status,
            String stage,
            int totalItems,
            int completedItems,
            int failedItems,
            int skippedItems,
            BigDecimal percent,
            Instant createdAt,
            Instant updatedAt) {}

    public record TaskDetail(
            UUID taskId,
            UUID runId,
            UUID nodeId,
            String taskType,
            String status,
            String waitingReason,
            String stage,
            int totalItems,
            int completedItems,
            int failedItems,
            int skippedItems,
            BigDecimal percent,
            JsonNode usage,
            JsonNode warnings,
            Instant createdAt,
            Instant updatedAt) {}

    public record TaskItemView(
            UUID itemId, String itemKey, String status, int attempt, JsonNode result, JsonNode error, Instant createdAt) {}

    public record ArtifactDownloadResponse(UUID artifactId, String objectKey, String downloadUrl, Instant expiresAt) {}

    public record TaskCancelResponse(UUID taskId, String status) {}
}
