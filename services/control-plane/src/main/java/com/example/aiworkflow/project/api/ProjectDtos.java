package com.example.aiworkflow.project.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.UUID;

public final class ProjectDtos {

    private ProjectDtos() {}

    public record CreateProjectRequest(
            @NotBlank @Size(max = 255) String name, @Size(max = 4000) String description) {}

    public record PatchProjectRequest(@Size(max = 255) String name, @Size(max = 4000) String description) {}

    public record ProjectResponse(
            UUID projectId, UUID workspaceId, String name, String description, Instant createdAt, Instant updatedAt) {}
}
