package com.example.aiworkflow.task.application;

import com.example.aiworkflow.execution.persistence.ExecutionEntity;
import com.example.aiworkflow.execution.persistence.ExecutionRepository;
import com.example.aiworkflow.task.persistence.TaskItemEntity;
import com.example.aiworkflow.task.persistence.TaskItemRepository;
import com.example.aiworkflow.task.persistence.TaskJobEntity;
import com.example.aiworkflow.task.persistence.TaskJobRepository;
import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Service;

@Service
public class TaskProjector {

    private final TaskJobRepository tasks;
    private final TaskItemRepository items;
    private final ExecutionRepository executions;
    private final ArtifactProjectionService artifacts;
    private final Clock clock;

    public TaskProjector(
            TaskJobRepository tasks,
            TaskItemRepository items,
            ExecutionRepository executions,
            ArtifactProjectionService artifacts,
            Clock clock) {
        this.tasks = tasks;
        this.items = items;
        this.executions = executions;
        this.artifacts = artifacts;
        this.clock = clock;
    }

    public void apply(JsonNode envelope) {
        String type = envelope.path("message_type").asText();
        JsonNode payload = envelope.path("payload");
        JsonNode subject = envelope.path("subject");
        String rawTaskId = payload.path("task_id").asText();
        if (rawTaskId.isBlank()) {
            rawTaskId = subject.path("task_id").asText();
        }
        if (rawTaskId.isBlank()) {
            return;
        }
        UUID taskId;
        try {
            taskId = UUID.fromString(rawTaskId);
        } catch (IllegalArgumentException ex) {
            return;
        }
        Instant now = clock.instant();
        switch (type) {
            case "task.progress" -> applyProgress(envelope, payload, taskId, now);
            case "task.item.completed" -> applyItem(envelope, payload, taskId, now);
            case "task.completed" -> applyCompleted(envelope, payload, taskId, now);
            case "task.failed" -> applyFailed(envelope, payload, taskId, now);
            default -> {
            }
        }
    }

    private void applyProgress(JsonNode envelope, JsonNode payload, UUID taskId, Instant now) {
        TaskJobEntity job = upsert(envelope, taskId, now);
        job.setStatus(payload.path("status").asText(job.getStatus()));
        if (payload.hasNonNull("stage")) {
            job.setStage(payload.path("stage").asText());
        }
        JsonNode progress = payload.path("progress");
        if (progress.isObject()) {
            job.setTotalItems(progress.path("total").asInt(job.getTotalItems()));
            job.setCompletedItems(progress.path("completed").asInt(job.getCompletedItems()));
            job.setFailedItems(progress.path("failed").asInt(job.getFailedItems()));
            job.setSkippedItems(progress.path("skipped").asInt(job.getSkippedItems()));
            if (progress.has("percent")) {
                job.setPercent(BigDecimal.valueOf(progress.path("percent").asDouble()));
            }
        }
        if (payload.has("usage")) {
            job.setUsageJson(payload.get("usage").toString());
        }
        if (payload.has("warnings")) {
            job.setWarningsJson(payload.get("warnings").toString());
        }
        job.setUpdatedAt(now);
        tasks.save(job);
    }

    private void applyItem(JsonNode envelope, JsonNode payload, UUID taskId, Instant now) {
        TaskJobEntity job = upsert(envelope, taskId, now);
        String itemKey = payload.path("item_key").asText();
        TaskItemEntity item = items.findByTaskJobIdAndItemKey(taskId, itemKey).orElseGet(() -> {
            TaskItemEntity created = new TaskItemEntity();
            created.setId(UUID.randomUUID());
            created.setTaskJobId(taskId);
            created.setItemKey(itemKey);
            created.setCreatedAt(now);
            return created;
        });
        item.setStatus(payload.path("status").asText());
        item.setAttempt(payload.path("attempt").asInt(1));
        if (payload.has("result_summary")) {
            item.setResultJson(payload.get("result_summary").toString());
        }
        if (payload.has("error_summary")) {
            item.setErrorJson(payload.get("error_summary").toString());
        }
        item.setUpdatedAt(now);
        items.save(item);
        job.setUpdatedAt(now);
        tasks.save(job);
    }

    private void applyCompleted(JsonNode envelope, JsonNode payload, UUID taskId, Instant now) {
        TaskJobEntity job = upsert(envelope, taskId, now);
        job.setStatus(payload.path("status").asText("SUCCEEDED"));
        if (payload.has("usage")) {
            job.setUsageJson(payload.get("usage").toString());
        }
        if (payload.has("warnings")) {
            job.setWarningsJson(payload.get("warnings").toString());
        }
        job.setUpdatedAt(now);
        tasks.save(job);
        artifacts.persistRefs(
                job.getWorkspaceId(),
                job.getProjectId(),
                job.getExecutionId(),
                job.getId(),
                payload.get("artifact_refs"),
                now);
    }

    private void applyFailed(JsonNode envelope, JsonNode payload, UUID taskId, Instant now) {
        TaskJobEntity job = upsert(envelope, taskId, now);
        job.setStatus(payload.path("status").asText("FAILED"));
        job.setUpdatedAt(now);
        tasks.save(job);
    }

    private TaskJobEntity upsert(JsonNode envelope, UUID taskId, Instant now) {
        return tasks.findById(taskId).orElseGet(() -> {
            JsonNode subject = envelope.path("subject");
            JsonNode tenant = envelope.path("tenant");
            TaskJobEntity created = new TaskJobEntity();
            created.setId(taskId);
            UUID runId = UUID.fromString(subject.path("run_id").asText());
            ExecutionEntity run = executions.findById(runId).orElse(null);
            created.setExecutionId(runId);
            created.setWorkspaceId(
                    run != null
                            ? run.getWorkspaceId()
                            : UUID.fromString(tenant.path("workspace_id").asText()));
            created.setProjectId(
                    run != null ? run.getProjectId() : UUID.fromString(tenant.path("project_id").asText()));
            if (subject.path("node_id").isTextual()) {
                created.setNodeId(UUID.fromString(subject.path("node_id").asText()));
            }
            created.setStatus("QUEUED");
            created.setCreatedAt(now);
            created.setUpdatedAt(now);
            return created;
        });
    }
}
