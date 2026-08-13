package com.example.aiworkflow.workflow.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public final class WorkflowDtos {

    private WorkflowDtos() {}

    public record CreateWorkflowRequest(
            @NotBlank @Size(max = 255) String name, @Size(max = 4000) String description) {}

    public record PutDraftRequest(@NotNull @Min(1) Integer baseRevision, @NotNull JsonNode definition) {}

    public record WorkflowSummary(
            UUID workflowId,
            UUID projectId,
            String name,
            String description,
            int latestVersion,
            Instant createdAt,
            Instant updatedAt) {}

    public record DraftResponse(UUID workflowId, int revision, JsonNode definition, Instant updatedAt) {}

    public record ValidateResponse(boolean valid, List<Object> errors) {}

    public record VersionSummary(
            UUID versionId, int versionNumber, String definitionHash, Instant publishedAt) {}

    public record VersionDetail(
            UUID versionId,
            UUID workflowId,
            int versionNumber,
            String definitionHash,
            JsonNode definition,
            Instant publishedAt) {}
}
