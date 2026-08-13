package com.example.aiworkflow.approval.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import java.time.Instant;
import java.util.UUID;

public final class ApprovalDtos {

    private ApprovalDtos() {}

    public record ApprovalResponse(
            UUID approvalId,
            UUID runId,
            UUID projectId,
            UUID nodeId,
            UUID interruptId,
            String status,
            JsonNode request,
            JsonNode decision,
            Instant createdAt) {}

    public record DecisionRequest(@NotBlank String decision, JsonNode payload) {}
}
