package com.example.aiworkflow.workflow.application;

import com.example.aiworkflow.common.pagination.CursorPage;
import com.example.aiworkflow.common.pagination.Cursors;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.project.persistence.ProjectEntity;
import com.example.aiworkflow.workflow.api.WorkflowDtos.CreateWorkflowRequest;
import com.example.aiworkflow.workflow.api.WorkflowDtos.DraftResponse;
import com.example.aiworkflow.workflow.api.WorkflowDtos.PutDraftRequest;
import com.example.aiworkflow.workflow.api.WorkflowDtos.WorkflowSummary;
import com.example.aiworkflow.workflow.persistence.WorkflowDraftEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowDraftRepository;
import com.example.aiworkflow.workflow.persistence.WorkflowEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowRepository;
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
public class WorkflowDraftService {

    private final ProjectService projects;
    private final WorkflowRepository workflows;
    private final WorkflowDraftRepository drafts;
    private final ObjectMapper objectMapper;
    private final Clock clock;

    public WorkflowDraftService(
            ProjectService projects,
            WorkflowRepository workflows,
            WorkflowDraftRepository drafts,
            ObjectMapper objectMapper,
            Clock clock) {
        this.projects = projects;
        this.workflows = workflows;
        this.drafts = drafts;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    @Transactional
    public WorkflowSummary create(UUID userId, UUID projectId, CreateWorkflowRequest request) {
        ProjectEntity project = projects.requireMember(userId, projectId);
        Instant now = clock.instant();
        UUID workflowId = UUID.randomUUID();
        WorkflowEntity workflow = new WorkflowEntity();
        workflow.setId(workflowId);
        workflow.setWorkspaceId(project.getWorkspaceId());
        workflow.setProjectId(project.getId());
        workflow.setName(request.name());
        workflow.setDescription(request.description());
        workflow.setLatestVersion(0);
        workflow.setCreatedAt(now);
        workflow.setUpdatedAt(now);
        workflows.save(workflow);

        WorkflowDraftEntity draft = new WorkflowDraftEntity();
        draft.setWorkflowId(workflowId);
        draft.setRevision(1);
        draft.setDefinitionJson(defaultDefinition(workflowId, request.name()));
        draft.setUpdatedBy(userId);
        draft.setCreatedAt(now);
        draft.setUpdatedAt(now);
        drafts.save(draft);
        return toSummary(workflow);
    }

    @Transactional(readOnly = true)
    public CursorPage<WorkflowSummary> list(UUID userId, UUID projectId, String cursor, int limit) {
        projects.requireMember(userId, projectId);
        Cursors.Key key = cursor == null ? null : Cursors.decode(cursor);
        List<WorkflowEntity> rows = workflows.listPage(
                projectId, key == null ? null : key.createdAt(), key == null ? null : key.id());
        int capped = Math.min(Math.max(limit, 1), 100);
        List<WorkflowEntity> page = rows.size() > capped ? rows.subList(0, capped) : rows;
        String next = rows.size() > capped
                ? Cursors.encode(page.getLast().getCreatedAt(), page.getLast().getId())
                : null;
        return new CursorPage<>(page.stream().map(WorkflowDraftService::toSummary).toList(), next);
    }

    @Transactional(readOnly = true)
    public WorkflowSummary get(UUID userId, UUID projectId, UUID workflowId) {
        return toSummary(requireWorkflow(userId, projectId, workflowId));
    }

    @Transactional(readOnly = true)
    public DraftResponse getDraft(UUID userId, UUID projectId, UUID workflowId) {
        requireWorkflow(userId, projectId, workflowId);
        WorkflowDraftEntity draft = drafts.findById(workflowId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "DRAFT_NOT_FOUND", "Draft not found"));
        return toDraft(draft);
    }

    @Transactional
    public DraftResponse putDraft(UUID userId, UUID projectId, UUID workflowId, PutDraftRequest request) {
        WorkflowEntity workflow = requireWorkflow(userId, projectId, workflowId);
        JsonNode definition = request.definition();
        if (definition.isObject()) {
            ((ObjectNode) definition).put("workflow_id", workflowId.toString());
            if (definition.path("name").asText("").isBlank()) {
                ((ObjectNode) definition).put("name", workflow.getName());
            }
        }
        String json;
        try {
            json = objectMapper.writeValueAsString(definition);
        } catch (Exception ex) {
            throw new ProblemException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "Invalid definition JSON");
        }
        Instant now = clock.instant();
        int updated = drafts.updateIfRevision(workflowId, request.baseRevision(), json, userId, now);
        if (updated == 0) {
            throw new ProblemException(HttpStatus.CONFLICT, "DRAFT_CONFLICT", "Stale draft revision");
        }
        workflow.setUpdatedAt(now);
        workflows.save(workflow);
        return getDraft(userId, projectId, workflowId);
    }

    public WorkflowEntity requireWorkflow(UUID userId, UUID projectId, UUID workflowId) {
        projects.requireMember(userId, projectId);
        return workflows
                .findByIdAndProjectId(workflowId, projectId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "WORKFLOW_NOT_FOUND", "Workflow not found"));
    }

    private DraftResponse toDraft(WorkflowDraftEntity draft) {
        try {
            return new DraftResponse(
                    draft.getWorkflowId(),
                    draft.getRevision(),
                    objectMapper.readTree(draft.getDefinitionJson()),
                    draft.getUpdatedAt());
        } catch (Exception ex) {
            throw new IllegalStateException("Stored draft is not valid JSON");
        }
    }

    private static WorkflowSummary toSummary(WorkflowEntity workflow) {
        return new WorkflowSummary(
                workflow.getId(),
                workflow.getProjectId(),
                workflow.getName(),
                workflow.getDescription(),
                workflow.getLatestVersion(),
                workflow.getCreatedAt(),
                workflow.getUpdatedAt());
    }

    private String defaultDefinition(UUID workflowId, String name) {
        UUID inputId = UUID.randomUUID();
        return """
                {
                  "schema_version": "1.0",
                  "workflow_id": "%s",
                  "name": %s,
                  "input_schema": {"type": "object"},
                  "output_schema": {"type": "object"},
                  "nodes": [{
                    "id": "%s",
                    "type": "data.input@1",
                    "position": {"x": 0, "y": 0},
                    "config": {}
                  }],
                  "edges": [],
                  "execution_policy": {
                    "timeout_seconds": 300,
                    "max_node_executions": 50,
                    "max_parallel_nodes": 4,
                    "max_fan_out_items": 100,
                    "max_task_seconds": 600,
                    "max_provider_calls": 100,
                    "max_artifact_bytes": 10485760,
                    "max_estimated_cost": null,
                    "default_retry": {
                      "max_attempts": 3,
                      "initial_backoff_ms": 500,
                      "max_backoff_ms": 10000,
                      "multiplier": 2,
                      "jitter": true
                    }
                  }
                }
                """
                .formatted(workflowId, jsonString(name), inputId);
    }

    private String jsonString(String value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception ex) {
            return "\"workflow\"";
        }
    }
}
