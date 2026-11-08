package com.example.aiworkflow.execution.application;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.example.aiworkflow.dataset.application.DocumentProjector;
import com.example.aiworkflow.dataset.persistence.DocumentRepository;
import com.example.aiworkflow.execution.persistence.ExecutionEntity;
import com.example.aiworkflow.execution.persistence.ExecutionEventRepository;
import com.example.aiworkflow.execution.persistence.ExecutionRepository;
import com.example.aiworkflow.execution.persistence.NodeExecutionRepository;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.project.persistence.ProjectEntity;
import com.example.aiworkflow.task.application.TaskProjector;
import com.example.aiworkflow.task.persistence.TaskItemRepository;
import com.example.aiworkflow.task.persistence.TaskJobRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@ExtendWith(MockitoExtension.class)
class ExecutionResilienceTest {

    @Mock
    ExecutionRepository executions;

    @Mock
    ExecutionEventRepository events;

    @Mock
    NodeExecutionRepository nodes;

    @Mock
    ProjectService projects;

    @Mock
    ExecutionSseHub sse;

    private final ObjectMapper mapper = new ObjectMapper();
    private final Clock clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);

    private ExecutionService executionService;

    @BeforeEach
    void setup() {
        executionService = new ExecutionService(
                projects,
                null,
                null,
                null,
                executions,
                nodes,
                events,
                null,
                null,
                null,
                null,
                sse,
                null,
                null,
                mapper,
                clock);
    }

    @Test
    void stream_givenInvalidNonNumericLastEventId_defaultsToZeroWithoutCrashing() {
        UUID userId = UUID.randomUUID();
        UUID projectId = UUID.randomUUID();
        UUID runId = UUID.randomUUID();

        ExecutionEntity entity = new ExecutionEntity();
        entity.setId(runId);
        entity.setProjectId(projectId);
        entity.setStatus("RUNNING");

        when(projects.requireMember(userId, projectId)).thenReturn(new ProjectEntity());
        when(executions.findByIdAndProjectId(runId, projectId)).thenReturn(Optional.of(entity));
        when(events.findByExecutionIdAndSequenceGreaterThanOrderBySequenceAsc(runId, 0)).thenReturn(List.of());
        when(sse.subscribe(runId)).thenReturn(mock(SseEmitter.class));

        assertThatCode(() -> executionService.stream(userId, projectId, runId, "invalid-event-id-uuid-string"))
                .doesNotThrowAnyException();
    }

    @Test
    void documentProjector_givenEmptyOrInvalidDocumentId_doesNotThrow() {
        DocumentRepository documentRepo = mock(DocumentRepository.class);
        DocumentProjector projector = new DocumentProjector(documentRepo, clock);

        ObjectNode envelope = mapper.createObjectNode();
        envelope.put("message_type", "document.ingestion.started");
        envelope.putObject("payload").put("document_id", "");
        envelope.putObject("subject");

        assertThatCode(() -> projector.apply(envelope)).doesNotThrowAnyException();
    }

    @Test
    void taskProjector_givenEmptyOrInvalidTaskId_doesNotThrow() {
        TaskJobRepository jobs = mock(TaskJobRepository.class);
        TaskItemRepository items = mock(TaskItemRepository.class);
        TaskProjector projector = new TaskProjector(jobs, items, executions, null, clock);

        ObjectNode envelope = mapper.createObjectNode();
        envelope.put("message_type", "task.progress");
        envelope.putObject("payload").put("task_id", "");
        envelope.putObject("subject");

        assertThatCode(() -> projector.apply(envelope)).doesNotThrowAnyException();
    }
}
