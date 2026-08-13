package com.example.aiworkflow.execution.application;

import com.example.aiworkflow.audit.application.AuditService;
import com.example.aiworkflow.common.pagination.CursorPage;
import com.example.aiworkflow.common.pagination.Cursors;
import com.example.aiworkflow.common.problem.ProblemError;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.execution.api.ExecutionDtos.ExecutionDetail;
import com.example.aiworkflow.execution.api.ExecutionDtos.ExecutionSummary;
import com.example.aiworkflow.execution.api.ExecutionDtos.NodeExecutionView;
import com.example.aiworkflow.execution.api.ExecutionDtos.StartExecutionRequest;
import com.example.aiworkflow.execution.api.ExecutionDtos.StartExecutionResponse;
import com.example.aiworkflow.execution.persistence.ExecutionEntity;
import com.example.aiworkflow.execution.persistence.ExecutionEventEntity;
import com.example.aiworkflow.execution.persistence.ExecutionEventRepository;
import com.example.aiworkflow.execution.persistence.ExecutionRepository;
import com.example.aiworkflow.execution.persistence.NodeExecutionEntity;
import com.example.aiworkflow.execution.persistence.NodeExecutionRepository;
import com.example.aiworkflow.messaging.envelope.EnvelopeFactory;
import com.example.aiworkflow.messaging.outbox.OutboxWriter;
import com.example.aiworkflow.observability.AiwMetrics;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.project.persistence.ProjectEntity;
import com.example.aiworkflow.workflow.application.WorkflowDraftService;
import com.example.aiworkflow.workflow.application.WorkflowValidationService;
import com.example.aiworkflow.workflow.application.validation.ContractSchemaValidator;
import com.example.aiworkflow.workflow.persistence.WorkflowDraftEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowDraftRepository;
import com.example.aiworkflow.workflow.persistence.WorkflowEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowVersionEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowVersionRepository;
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
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Service
public class ExecutionService {

    private final ProjectService projects;
    private final WorkflowDraftService drafts;
    private final WorkflowDraftRepository draftRepository;
    private final WorkflowVersionRepository versions;
    private final ExecutionRepository executions;
    private final NodeExecutionRepository nodes;
    private final ExecutionEventRepository events;
    private final WorkflowValidationService validation;
    private final ContractSchemaValidator schemas;
    private final EnvelopeFactory envelopes;
    private final OutboxWriter outbox;
    private final ExecutionSseHub sse;
    private final AuditService audit;
    private final AiwMetrics metrics;
    private final ObjectMapper objectMapper;
    private final Clock clock;

    public ExecutionService(
            ProjectService projects,
            WorkflowDraftService drafts,
            WorkflowDraftRepository draftRepository,
            WorkflowVersionRepository versions,
            ExecutionRepository executions,
            NodeExecutionRepository nodes,
            ExecutionEventRepository events,
            WorkflowValidationService validation,
            ContractSchemaValidator schemas,
            EnvelopeFactory envelopes,
            OutboxWriter outbox,
            ExecutionSseHub sse,
            AuditService audit,
            AiwMetrics metrics,
            ObjectMapper objectMapper,
            Clock clock) {
        this.projects = projects;
        this.drafts = drafts;
        this.draftRepository = draftRepository;
        this.versions = versions;
        this.executions = executions;
        this.nodes = nodes;
        this.events = events;
        this.validation = validation;
        this.schemas = schemas;
        this.envelopes = envelopes;
        this.outbox = outbox;
        this.sse = sse;
        this.audit = audit;
        this.metrics = metrics;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    @Transactional
    public StartExecutionResponse start(UUID userId, UUID projectId, UUID workflowId, StartExecutionRequest request) {
        ProjectEntity project = projects.requireMember(userId, projectId);
        WorkflowEntity workflow = drafts.requireWorkflow(userId, projectId, workflowId);
        return new StartExecutionResponse(enqueue(
                userId,
                project,
                workflow,
                request.mode(),
                request.input(),
                request.idempotencyKey(),
                request.workflowVersionId(),
                "test".equalsIgnoreCase(request.mode()) ? "test" : "manual",
                null));
    }

    @Transactional
    public UUID startFromTrigger(
            UUID actorUserId,
            ProjectEntity project,
            WorkflowEntity workflow,
            UUID workflowVersionId,
            JsonNode input,
            String idempotencyKey,
            String triggerType,
            UUID triggerId) {
        return enqueue(
                actorUserId, project, workflow, "published", input, idempotencyKey, workflowVersionId, triggerType, triggerId);
    }

    private UUID enqueue(
            UUID actorUserId,
            ProjectEntity project,
            WorkflowEntity workflow,
            String mode,
            JsonNode input,
            String idempotencyKey,
            UUID workflowVersionId,
            String triggerType,
            UUID triggerId) {
        String normalizedMode = mode == null ? "" : mode.trim().toLowerCase();
        if (!normalizedMode.equals("draft") && !normalizedMode.equals("published")) {
            throw new ProblemException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "mode must be draft or published");
        }
        return executions
                .findByProjectIdAndIdempotencyKey(project.getId(), idempotencyKey)
                .map(ExecutionEntity::getId)
                .orElseGet(() -> createRun(
                        actorUserId,
                        project,
                        workflow,
                        normalizedMode,
                        input,
                        idempotencyKey,
                        workflowVersionId,
                        triggerType,
                        triggerId));
    }

    private UUID createRun(
            UUID actorUserId,
            ProjectEntity project,
            WorkflowEntity workflow,
            String mode,
            JsonNode input,
            String idempotencyKey,
            UUID workflowVersionId,
            String triggerType,
            UUID triggerId) {
        Instant now = clock.instant();
        JsonNode definition;
        Integer draftRevision = null;
        UUID versionId = null;
        if ("draft".equals(mode)) {
            WorkflowDraftEntity draft = draftRepository
                    .findById(workflow.getId())
                    .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "DRAFT_NOT_FOUND", "Draft not found"));
            definition = parse(draft.getDefinitionJson());
            if (definition instanceof ObjectNode objectNode) {
                objectNode.putNull("workflow_version_id");
            }
            validation.parseAndValidateOrThrow(definition.toString());
            draftRevision = draft.getRevision();
        } else {
            WorkflowVersionEntity version = resolvePublished(workflow.getId(), workflowVersionId);
            definition = parse(version.getDefinitionJson());
            versionId = version.getId();
        }
        validateInput(definition.path("input_schema"), input);
        UUID runId = UUID.randomUUID();
        ExecutionEntity run = new ExecutionEntity();
        run.setId(runId);
        run.setWorkspaceId(project.getWorkspaceId());
        run.setProjectId(project.getId());
        run.setWorkflowId(workflow.getId());
        run.setWorkflowVersionId(versionId);
        run.setMode(mode);
        run.setStatus("QUEUED");
        run.setInputJson(input.toString());
        run.setDefinitionJson(definition.toString());
        run.setDraftRevision(draftRevision);
        run.setIdempotencyKey(idempotencyKey);
        run.setLastSequence(0);
        run.setQuarantined(false);
        run.setCreatedAt(now);
        run.setUpdatedAt(now);
        executions.save(run);

        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("mode", mode);
        payload.set("definition", definition);
        payload.set("input", input);
        if ("draft".equals(mode)) {
            payload.put("draft_revision", draftRevision);
        } else {
            payload.putNull("draft_revision");
        }
        ObjectNode trigger = payload.putObject("trigger");
        trigger.put("type", "draft".equals(mode) ? "test" : triggerType);
        if (triggerId == null) {
            trigger.putNull("trigger_id");
        } else {
            trigger.put("trigger_id", triggerId.toString());
        }
        JsonNode envelope = envelopes.command(
                "execution.start",
                project.getWorkspaceId(),
                project.getId(),
                workflow.getId(),
                versionId,
                runId,
                runId,
                null,
                idempotencyKey,
                payload,
                now);
        outbox.enqueue("execution", runId, "execution.start", envelope);
        audit.record(actorUserId, project.getWorkspaceId(), project.getId(), "execution.start", "execution", runId, null);
        metrics.incrementRunsStarted();
        return runId;
    }

    @Transactional(readOnly = true)
    public CursorPage<ExecutionSummary> list(UUID userId, UUID projectId, String cursor, int limit) {
        projects.requireMember(userId, projectId);
        Cursors.Key key = cursor == null ? null : Cursors.decode(cursor);
        List<ExecutionEntity> rows = executions.listPage(
                projectId, key == null ? null : key.createdAt(), key == null ? null : key.id());
        int capped = Math.min(Math.max(limit, 1), 100);
        List<ExecutionEntity> page = rows.size() > capped ? rows.subList(0, capped) : rows;
        String next = rows.size() > capped
                ? Cursors.encode(page.getLast().getCreatedAt(), page.getLast().getId())
                : null;
        return new CursorPage<>(page.stream().map(ExecutionService::toSummary).toList(), next);
    }

    @Transactional(readOnly = true)
    public ExecutionDetail get(UUID userId, UUID projectId, UUID runId) {
        ExecutionEntity run = requireRun(userId, projectId, runId);
        List<NodeExecutionView> nodeViews = nodes.findByExecutionIdOrderByStartedAtAsc(runId).stream()
                .map(this::toNode)
                .toList();
        return toDetail(run, nodeViews);
    }

    @Transactional
    public ExecutionSummary cancel(UUID userId, UUID projectId, UUID runId) {
        ExecutionEntity run = requireRun(userId, projectId, runId);
        if (ExecutionStateMachine.isTerminal(run.getStatus())) {
            throw new ProblemException(HttpStatus.CONFLICT, "RUN_NOT_CANCELLABLE", "Run is already terminal");
        }
        if (!ExecutionStateMachine.isLegal(run.getStatus(), "CANCELLING")) {
            throw new ProblemException(HttpStatus.CONFLICT, "RUN_NOT_CANCELLABLE", "Run cannot be cancelled");
        }
        Instant now = clock.instant();
        run.setStatus("CANCELLING");
        run.setUpdatedAt(now);
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("reason", "user_requested");
        payload.put("requested_by", userId.toString());
        JsonNode envelope = envelopes.command(
                "execution.cancel",
                run.getWorkspaceId(),
                run.getProjectId(),
                run.getWorkflowId(),
                run.getWorkflowVersionId(),
                run.getId(),
                run.getId(),
                null,
                "cancel:" + run.getId(),
                payload,
                now);
        outbox.enqueue("execution", run.getId(), "execution.cancel", envelope);
        audit.record(userId, run.getWorkspaceId(), run.getProjectId(), "execution.cancel", "execution", run.getId(), null);
        return toSummary(run);
    }

    @Transactional
    public void cancelIfActive(UUID userId, UUID projectId, UUID runId) {
        ExecutionEntity run = requireRun(userId, projectId, runId);
        if (ExecutionStateMachine.isTerminal(run.getStatus()) || "CANCELLING".equals(run.getStatus())) {
            return;
        }
        cancel(userId, projectId, runId);
    }

    @Transactional(readOnly = true)
    public SseEmitter stream(UUID userId, UUID projectId, UUID runId, String lastEventId) {
        ExecutionEntity run = requireRun(userId, projectId, runId);
        int after = 0;
        if (lastEventId != null && !lastEventId.isBlank()) {
            after = Integer.parseInt(lastEventId);
        }
        List<ExecutionEventEntity> replay =
                events.findByExecutionIdAndSequenceGreaterThanOrderBySequenceAsc(runId, after);
        SseEmitter emitter = sse.subscribe(runId);
        sse.sendReplay(emitter, replay);
        if (ExecutionStateMachine.isTerminal(run.getStatus()) && replay.isEmpty()) {
            emitter.complete();
        } else if (ExecutionStateMachine.isTerminal(run.getStatus())) {
            emitter.complete();
        }
        return emitter;
    }

    public ExecutionEntity requireRun(UUID userId, UUID projectId, UUID runId) {
        projects.requireMember(userId, projectId);
        return executions
                .findByIdAndProjectId(runId, projectId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "Run not found"));
    }

    private WorkflowVersionEntity resolvePublished(UUID workflowId, UUID workflowVersionId) {
        if (workflowVersionId != null) {
            return versions
                    .findByIdAndWorkflowId(workflowVersionId, workflowId)
                    .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "VERSION_NOT_FOUND", "Version not found"));
        }
        return versions.findByWorkflowIdOrderByVersionNumberDesc(workflowId).stream()
                .findFirst()
                .orElseThrow(() -> new ProblemException(HttpStatus.CONFLICT, "WORKFLOW_NOT_PUBLISHED", "Workflow has no published version"));
    }

    private void validateInput(JsonNode inputSchema, JsonNode input) {
        if (inputSchema == null || inputSchema.isMissingNode() || inputSchema.isNull()) {
            return;
        }
        List<String> errors = schemas.validateAgainst(inputSchema, input);
        if (!errors.isEmpty()) {
            throw new ProblemException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "INPUT_INVALID",
                    "Run input is invalid",
                    List.of(ProblemError.of("INPUT_INVALID", errors.getFirst())));
        }
    }

    private JsonNode parse(String json) {
        try {
            return objectMapper.readTree(json);
        } catch (Exception ex) {
            throw new ProblemException(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Invalid stored definition");
        }
    }

    private static ExecutionSummary toSummary(ExecutionEntity run) {
        return new ExecutionSummary(
                run.getId(),
                run.getWorkflowId(),
                run.getWorkflowVersionId(),
                run.getMode(),
                run.getStatus(),
                run.getWaitingReason(),
                run.getCreatedAt(),
                run.getUpdatedAt());
    }

    private ExecutionDetail toDetail(ExecutionEntity run, List<NodeExecutionView> nodeViews) {
        return new ExecutionDetail(
                run.getId(),
                run.getProjectId(),
                run.getWorkflowId(),
                run.getWorkflowVersionId(),
                run.getMode(),
                run.getStatus(),
                run.getWaitingReason(),
                run.getInterruptId(),
                parseQuiet(run.getInputJson()),
                parseQuiet(run.getOutputJson()),
                run.getLastSequence(),
                run.getErrorCode(),
                run.getCreatedAt(),
                run.getUpdatedAt(),
                nodeViews);
    }

    private NodeExecutionView toNode(NodeExecutionEntity node) {
        return new NodeExecutionView(
                node.getNodeId(),
                node.getAttempt(),
                node.getStatus(),
                parseQuiet(node.getInputJson()),
                parseQuiet(node.getOutputJson()),
                parseQuiet(node.getErrorJson()));
    }

    private JsonNode parseQuiet(String json) {
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
