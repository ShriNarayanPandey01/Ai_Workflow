package com.example.aiworkflow.task.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.aiworkflow.config.AiwProperties;
import com.example.aiworkflow.execution.application.ExecutionService;
import com.example.aiworkflow.execution.persistence.ExecutionEntity;
import com.example.aiworkflow.messaging.envelope.EnvelopeFactory;
import com.example.aiworkflow.messaging.outbox.OutboxWriter;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.storage.FakeObjectStore;
import com.example.aiworkflow.task.persistence.ArtifactRepository;
import com.example.aiworkflow.task.persistence.TaskItemRepository;
import com.example.aiworkflow.task.persistence.TaskJobEntity;
import com.example.aiworkflow.task.persistence.TaskJobRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class TaskServiceCancelTest {

    @Mock
    ProjectService projects;

    @Mock
    ExecutionService executions;

    @Mock
    TaskJobRepository tasks;

    @Mock
    TaskItemRepository items;

    @Mock
    ArtifactRepository artifacts;

    @Mock
    OutboxWriter outbox;

    private TaskService service;
    private final ObjectMapper mapper = new ObjectMapper();
    private final Clock clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);
    private final UUID userId = UUID.randomUUID();
    private final UUID projectId = UUID.randomUUID();
    private final UUID taskId = UUID.randomUUID();
    private final UUID runId = UUID.randomUUID();

    @BeforeEach
    void setup() {
        AiwProperties properties = new AiwProperties(
                new AiwProperties.Jwt("development-only-jwt-secret-must-be-at-least-32-bytes", Duration.ofMinutes(10)),
                new AiwProperties.Refresh(
                        "development-only-refresh-hash-secret",
                        Duration.ofDays(30),
                        "aiw_refresh",
                        false,
                        "/api/v1/auth"),
                new AiwProperties.Contracts("../../contracts"),
                new AiwProperties.Limits(500, 100, 86400, 10000),
                new AiwProperties.Auth(20),
                new AiwProperties.Credentials("development-only-credential-kek-must-be-32b", "v1"),
                new AiwProperties.ServiceJwt(
                        "development-only-jwt-secret-must-be-at-least-32-bytes", Duration.ofMinutes(5), "control-plane"),
                new AiwProperties.Messaging(false, Duration.ofSeconds(2), 20),
                new AiwProperties.Storage(
                        false, "http://localhost:9000", "aiw", "aiw", "aiwsecret", "us-east-1", true, Duration.ofMinutes(15)));
        service = new TaskService(
                projects,
                executions,
                tasks,
                items,
                artifacts,
                new FakeObjectStore(clock),
                new EnvelopeFactory(mapper),
                outbox,
                properties,
                mapper,
                clock);
    }

    @Test
    void cancel_emitsTaskCancelAndParentExecutionCancel() {
        TaskJobEntity job = new TaskJobEntity();
        job.setId(taskId);
        job.setProjectId(projectId);
        job.setExecutionId(runId);
        job.setStatus("RUNNING");
        when(tasks.findByIdAndProjectId(taskId, projectId)).thenReturn(Optional.of(job));
        ExecutionEntity run = new ExecutionEntity();
        run.setId(runId);
        run.setWorkspaceId(UUID.randomUUID());
        run.setProjectId(projectId);
        run.setWorkflowId(UUID.randomUUID());
        run.setStatus("RUNNING");
        when(executions.requireRun(userId, projectId, runId)).thenReturn(run);
        service.cancel(userId, projectId, taskId);
        ArgumentCaptor<String> type = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<JsonNode> envelope = ArgumentCaptor.forClass(JsonNode.class);
        verify(outbox).enqueue(eq("task"), eq(taskId), type.capture(), envelope.capture());
        assertThat(type.getValue()).isEqualTo("task.cancel");
        assertThat(envelope.getValue().path("payload").path("reason").asText()).isEqualTo("user_requested");
        assertThat(envelope.getValue().path("subject").path("task_id").asText()).isEqualTo(taskId.toString());
        verify(executions).cancelIfActive(userId, projectId, runId);
        verify(outbox, never()).enqueue(eq("task"), any(), eq("task.start"), any());
    }
}
