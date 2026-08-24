package com.example.aiworkflow.task.application;

import com.example.aiworkflow.common.pagination.CursorPage;
import com.example.aiworkflow.common.pagination.Cursors;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.config.AiwProperties;
import com.example.aiworkflow.execution.application.ExecutionService;
import com.example.aiworkflow.execution.persistence.ExecutionEntity;
import com.example.aiworkflow.messaging.envelope.EnvelopeFactory;
import com.example.aiworkflow.messaging.outbox.OutboxWriter;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.storage.ObjectStore;
import com.example.aiworkflow.storage.PresignedObject;
import com.example.aiworkflow.task.api.TaskDtos.ArtifactDownloadResponse;
import com.example.aiworkflow.task.api.TaskDtos.TaskCancelResponse;
import com.example.aiworkflow.task.api.TaskDtos.TaskDetail;
import com.example.aiworkflow.task.api.TaskDtos.TaskItemView;
import com.example.aiworkflow.task.api.TaskDtos.TaskSummary;
import com.example.aiworkflow.task.persistence.ArtifactEntity;
import com.example.aiworkflow.task.persistence.ArtifactRepository;
import com.example.aiworkflow.task.persistence.TaskItemEntity;
import com.example.aiworkflow.task.persistence.TaskItemRepository;
import com.example.aiworkflow.task.persistence.TaskJobEntity;
import com.example.aiworkflow.task.persistence.TaskJobRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TaskService {

    private final ProjectService projects;
    private final ExecutionService executions;
    private final TaskJobRepository tasks;
    private final TaskItemRepository items;
    private final ArtifactRepository artifacts;
    private final ObjectStore objectStore;
    private final EnvelopeFactory envelopes;
    private final OutboxWriter outbox;
    private final AiwProperties properties;
    private final ObjectMapper objectMapper;
    private final Clock clock;

    public TaskService(
            ProjectService projects,
            ExecutionService executions,
            TaskJobRepository tasks,
            TaskItemRepository items,
            ArtifactRepository artifacts,
            ObjectStore objectStore,
            EnvelopeFactory envelopes,
            OutboxWriter outbox,
            AiwProperties properties,
            ObjectMapper objectMapper,
            Clock clock) {
        this.projects = projects;
        this.executions = executions;
        this.tasks = tasks;
        this.items = items;
        this.artifacts = artifacts;
        this.objectStore = objectStore;
        this.envelopes = envelopes;
        this.outbox = outbox;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public List<TaskSummary> listForRun(UUID userId, UUID projectId, UUID runId) {
        executions.requireRun(userId, projectId, runId);
        return tasks.findByExecutionIdAndProjectIdOrderByCreatedAtDesc(runId, projectId).stream()
                .map(TaskService::toSummary)
                .toList();
    }

    @Transactional(readOnly = true)
    public TaskDetail get(UUID userId, UUID projectId, UUID taskId) {
        return toDetail(requireTask(userId, projectId, taskId));
    }

    @Transactional(readOnly = true)
    public CursorPage<TaskItemView> listItems(UUID userId, UUID projectId, UUID taskId, String cursor, int limit) {
        requireTask(userId, projectId, taskId);
        Cursors.Key key = cursor == null ? null : Cursors.decode(cursor);
        int capped = Math.min(Math.max(limit, 1), 100);
        List<TaskItemEntity> rows = items.listPage(
                taskId,
                key == null ? null : key.createdAt(),
                key == null ? null : key.id(),
                org.springframework.data.domain.PageRequest.of(0, capped + 1));
        List<TaskItemEntity> page = rows.size() > capped ? rows.subList(0, capped) : rows;
        String next = rows.size() > capped
                ? Cursors.encode(page.getLast().getCreatedAt(), page.getLast().getId())
                : null;
        return new CursorPage<>(page.stream().map(this::toItem).toList(), next);
    }

    @Transactional
    public TaskCancelResponse cancel(UUID userId, UUID projectId, UUID taskId) {
        TaskJobEntity task = requireTask(userId, projectId, taskId);
        ExecutionEntity run = executions.requireRun(userId, projectId, task.getExecutionId());
        Instant now = clock.instant();
        task.setStatus("CANCELLING");
        task.setUpdatedAt(now);
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("task_id", taskId.toString());
        payload.put("reason", "user_requested");
        JsonNode envelope = envelopes.taskCommand(
                "task.cancel",
                run.getWorkspaceId(),
                run.getProjectId(),
                run.getWorkflowId(),
                run.getWorkflowVersionId(),
                run.getId(),
                task.getNodeId(),
                taskId,
                run.getId(),
                "task-cancel:" + taskId,
                payload,
                now);
        outbox.enqueue("task", taskId, "task.cancel", envelope);
        executions.cancelIfActive(userId, projectId, run.getId());
        return new TaskCancelResponse(taskId, task.getStatus());
    }

    @Transactional(readOnly = true)
    public ArtifactDownloadResponse download(UUID userId, UUID projectId, UUID artifactId) {
        projects.requireMember(userId, projectId);
        ArtifactEntity artifact = artifacts
                .findByIdAndProjectId(artifactId, projectId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "ARTIFACT_NOT_FOUND", "Artifact not found"));
        PresignedObject signed =
                objectStore.presignGet(artifact.getObjectKey(), properties.storage().presignTtl());
        return new ArtifactDownloadResponse(
                artifact.getId(), artifact.getObjectKey(), signed.url(), signed.expiresAt());
    }

    private TaskJobEntity requireTask(UUID userId, UUID projectId, UUID taskId) {
        projects.requireMember(userId, projectId);
        return tasks.findByIdAndProjectId(taskId, projectId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "TASK_NOT_FOUND", "Task not found"));
    }

    private static TaskSummary toSummary(TaskJobEntity job) {
        return new TaskSummary(
                job.getId(),
                job.getExecutionId(),
                job.getNodeId(),
                job.getTaskType(),
                job.getStatus(),
                job.getStage(),
                job.getTotalItems(),
                job.getCompletedItems(),
                job.getFailedItems(),
                job.getSkippedItems(),
                job.getPercent(),
                job.getCreatedAt(),
                job.getUpdatedAt());
    }

    private TaskDetail toDetail(TaskJobEntity job) {
        return new TaskDetail(
                job.getId(),
                job.getExecutionId(),
                job.getNodeId(),
                job.getTaskType(),
                job.getStatus(),
                job.getWaitingReason(),
                job.getStage(),
                job.getTotalItems(),
                job.getCompletedItems(),
                job.getFailedItems(),
                job.getSkippedItems(),
                job.getPercent(),
                parse(job.getUsageJson()),
                parse(job.getWarningsJson()),
                job.getCreatedAt(),
                job.getUpdatedAt());
    }

    private TaskItemView toItem(TaskItemEntity item) {
        return new TaskItemView(
                item.getId(),
                item.getItemKey(),
                item.getStatus(),
                item.getAttempt(),
                parse(item.getResultJson()),
                parse(item.getErrorJson()),
                item.getCreatedAt());
    }

    private JsonNode parse(String json) {
        if (json == null) {
            return null;
        }
        try {
            return objectMapper.readTree(json);
        } catch (Exception ex) {
            return objectMapper.nullNode();
        }
    }
}
