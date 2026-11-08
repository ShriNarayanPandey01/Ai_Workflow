package com.example.aiworkflow.task.application;

import com.example.aiworkflow.storage.ObjectKeys;
import com.example.aiworkflow.task.persistence.ArtifactEntity;
import com.example.aiworkflow.task.persistence.ArtifactRepository;
import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class ArtifactProjectionService {

    private final ArtifactRepository artifacts;

    public ArtifactProjectionService(ArtifactRepository artifacts) {
        this.artifacts = artifacts;
    }

    public void persistRefs(
            UUID workspaceId,
            UUID projectId,
            UUID executionId,
            UUID taskJobId,
            JsonNode refs,
            Instant now) {
        if (refs == null || !refs.isArray()) {
            return;
        }
        for (JsonNode ref : refs) {
            UUID artifactId = UUID.fromString(ref.asText());
            if (artifacts.existsById(artifactId)) {
                continue;
            }
            ArtifactEntity row = new ArtifactEntity();
            row.setId(artifactId);
            row.setWorkspaceId(workspaceId);
            row.setProjectId(projectId);
            row.setExecutionId(executionId);
            row.setTaskJobId(taskJobId);
            row.setKind("generated");
            row.setObjectKey(ObjectKeys.artifact(workspaceId, projectId, artifactId));
            row.setCreatedAt(now);
            artifacts.save(row);
        }
    }
}
