package com.example.aiworkflow.dataset.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

public final class DatasetDtos {

    private DatasetDtos() {}

    public record CreateDatasetRequest(
            @NotBlank @Size(max = 255) String name, JsonNode embeddingConfig) {}

    public record DatasetResponse(
            UUID datasetId,
            UUID projectId,
            String name,
            JsonNode embeddingConfig,
            Instant createdAt,
            Instant updatedAt) {}

    public record CreateUploadRequest(
            @NotBlank @Size(max = 512) String originalName,
            @NotBlank @Size(max = 128) String mediaType,
            @NotNull @Min(1) Long sizeBytes) {}

    public record UploadIntentResponse(
            UUID documentId,
            String objectKey,
            String uploadUrl,
            Map<String, String> headers,
            Instant expiresAt) {}

    public record ConfirmDocumentRequest(
            @NotNull UUID documentId,
            @NotBlank @Pattern(regexp = "^[a-f0-9]{64}$") String contentHash) {}

    public record DocumentResponse(
            UUID documentId,
            UUID datasetId,
            String originalName,
            String mediaType,
            long sizeBytes,
            String contentHash,
            int version,
            String status,
            String errorCode,
            Integer chunkCount,
            Instant createdAt,
            Instant updatedAt) {}

    public record DownloadIntentResponse(UUID documentId, String objectKey, String downloadUrl, Instant expiresAt) {}
}
