package com.example.aiworkflow.execution.api;

import com.example.aiworkflow.common.pagination.CursorPage;
import com.example.aiworkflow.execution.application.ExecutionService;
import com.example.aiworkflow.security.CurrentUser;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
public class ExecutionController {

    private final ExecutionService executions;
    private final CurrentUser currentUser;

    public ExecutionController(ExecutionService executions, CurrentUser currentUser) {
        this.executions = executions;
        this.currentUser = currentUser;
    }

    @PostMapping("/api/v1/projects/{projectId}/workflows/{workflowId}/executions")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ExecutionDtos.StartExecutionResponse start(
            @PathVariable UUID projectId,
            @PathVariable UUID workflowId,
            @Valid @RequestBody ExecutionDtos.StartExecutionRequest request) {
        return executions.start(currentUser.requireUserId(), projectId, workflowId, request);
    }

    @GetMapping("/api/v1/projects/{projectId}/executions")
    public CursorPage<ExecutionDtos.ExecutionSummary> list(
            @PathVariable UUID projectId,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "20") int limit) {
        return executions.list(currentUser.requireUserId(), projectId, cursor, limit);
    }

    @GetMapping("/api/v1/projects/{projectId}/executions/{runId}")
    public ExecutionDtos.ExecutionDetail get(@PathVariable UUID projectId, @PathVariable UUID runId) {
        return executions.get(currentUser.requireUserId(), projectId, runId);
    }

    @PostMapping("/api/v1/projects/{projectId}/executions/{runId}/cancel")
    public ExecutionDtos.ExecutionSummary cancel(@PathVariable UUID projectId, @PathVariable UUID runId) {
        return executions.cancel(currentUser.requireUserId(), projectId, runId);
    }

    @GetMapping(path = "/api/v1/projects/{projectId}/executions/{runId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter events(
            @PathVariable UUID projectId,
            @PathVariable UUID runId,
            @RequestHeader(value = "Last-Event-ID", required = false) String lastEventId) {
        return executions.stream(currentUser.requireUserId(), projectId, runId, lastEventId);
    }
}
