package com.example.aiworkflow.execution.application;

import com.example.aiworkflow.approval.persistence.ApprovalRequestEntity;
import com.example.aiworkflow.approval.persistence.ApprovalRequestRepository;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.dataset.application.DocumentProjector;
import com.example.aiworkflow.execution.persistence.ExecutionEntity;
import com.example.aiworkflow.execution.persistence.ExecutionEventEntity;
import com.example.aiworkflow.execution.persistence.ExecutionEventRepository;
import com.example.aiworkflow.execution.persistence.ExecutionRepository;
import com.example.aiworkflow.execution.persistence.NodeExecutionEntity;
import com.example.aiworkflow.execution.persistence.NodeExecutionRepository;
import com.example.aiworkflow.messaging.MessagingNames;
import com.example.aiworkflow.messaging.inbox.ConsumedMessageEntity;
import com.example.aiworkflow.messaging.inbox.ConsumedMessageRepository;
import com.example.aiworkflow.task.application.ArtifactProjectionService;
import com.example.aiworkflow.task.application.TaskProjector;
import com.fasterxml.jackson.databind.JsonNode;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ExecutionProjector {

    private static final Logger log = LoggerFactory.getLogger(ExecutionProjector.class);

    private final ConsumedMessageRepository inbox;
    private final ExecutionRepository executions;
    private final ExecutionEventRepository events;
    private final NodeExecutionRepository nodes;
    private final ApprovalRequestRepository approvals;
    private final DocumentProjector documents;
    private final TaskProjector tasks;
    private final ArtifactProjectionService artifacts;
    private final ExecutionSseHub sse;
    private final Clock clock;

    public ExecutionProjector(
            ConsumedMessageRepository inbox,
            ExecutionRepository executions,
            ExecutionEventRepository events,
            NodeExecutionRepository nodes,
            ApprovalRequestRepository approvals,
            DocumentProjector documents,
            TaskProjector tasks,
            ArtifactProjectionService artifacts,
            ExecutionSseHub sse,
            Clock clock) {
        this.inbox = inbox;
        this.executions = executions;
        this.events = events;
        this.nodes = nodes;
        this.approvals = approvals;
        this.documents = documents;
        this.tasks = tasks;
        this.artifacts = artifacts;
        this.sse = sse;
        this.clock = clock;
    }

    public enum Result {
        APPLIED,
        DUPLICATE,
        UNKNOWN,
        INVALID
    }

    @Transactional
    public Result apply(JsonNode envelope) {
        UUID messageId = UUID.fromString(envelope.path("message_id").asText());
        ConsumedMessageEntity.Key key = new ConsumedMessageEntity.Key(MessagingNames.CONSUMER_NAME, messageId);
        if (inbox.existsById(key)) {
            return Result.DUPLICATE;
        }
        String type = envelope.path("message_type").asText();
        if (type.startsWith("document.")) {
            documents.apply(envelope);
            remember(messageId);
            return Result.APPLIED;
        }
        if (type.startsWith("task.")) {
            tasks.apply(envelope);
            remember(messageId);
            return Result.APPLIED;
        }
        if (!type.startsWith("execution.") && !type.startsWith("node.")) {
            return Result.UNKNOWN;
        }
        if (!envelope.path("sequence").isInt()) {
            return Result.INVALID;
        }
        UUID runId = UUID.fromString(envelope.path("subject").path("run_id").asText());
        ExecutionEntity run = executions.findById(runId).orElse(null);
        if (run == null) {
            throw new ProblemException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "Run not found");
        }
        int sequence = envelope.path("sequence").asInt();
        if (events.existsByExecutionIdAndSequence(runId, sequence) || events.findByMessageId(messageId).isPresent()) {
            remember(messageId);
            return Result.DUPLICATE;
        }
        JsonNode payload = envelope.path("payload").deepCopy();
        JsonRedactor.redact(payload);
        Instant now = clock.instant();
        ExecutionEventEntity stored = new ExecutionEventEntity();
        stored.setId(UUID.randomUUID());
        stored.setExecutionId(runId);
        stored.setSequence(sequence);
        stored.setEventType(type);
        stored.setPayloadJson(payload.toString());
        stored.setMessageId(messageId);
        stored.setOccurredAt(Instant.parse(envelope.path("occurred_at").asText()));
        stored.setCreatedAt(now);
        events.save(stored);
        run.setLastSequence(Math.max(run.getLastSequence(), sequence));
        applyLifecycle(run, type, payload, envelope, now);
        run.setUpdatedAt(now);
        executions.save(run);
        remember(messageId);
        sse.notify(stored, run);
        return Result.APPLIED;
    }

    private void applyLifecycle(ExecutionEntity run, String type, JsonNode payload, JsonNode envelope, Instant now) {
        switch (type) {
            case "execution.queued" -> transition(run, "QUEUED");
            case "execution.started" -> {
                transition(run, "RUNNING");
                if (run.getStartedAt() == null) {
                    run.setStartedAt(now);
                }
                run.setWaitingReason(null);
                run.setInterruptId(null);
            }
            case "execution.waiting" -> {
                transition(run, "WAITING");
                String reason = payload.path("waiting_reason").asText();
                run.setWaitingReason(reason);
                if (payload.hasNonNull("interrupt_id")) {
                    run.setInterruptId(UUID.fromString(payload.get("interrupt_id").asText()));
                }
                if ("HUMAN".equals(reason)) {
                    persistApproval(run, payload, envelope, now);
                }
            }
            case "execution.completed" -> {
                transition(run, "SUCCEEDED");
                run.setOutputJson(payload.path("outputs").toString());
                run.setFinishedAt(now);
                run.setWaitingReason(null);
                run.setInterruptId(null);
            }
            case "execution.failed" -> {
                String status = payload.path("status").asText("FAILED");
                transition(run, status);
                run.setErrorCode(payload.path("error").path("code").asText(null));
                run.setFinishedAt(now);
                run.setWaitingReason(null);
                run.setInterruptId(null);
            }
            case "execution.cancelled" -> {
                transition(run, "CANCELLED");
                run.setFinishedAt(now);
                run.setWaitingReason(null);
                run.setInterruptId(null);
            }
            case "node.started", "node.completed", "node.failed" -> upsertNode(run.getId(), envelope, payload, now);
            default -> log.debug("ignored event type {}", type);
        }
    }

    private void persistApproval(ExecutionEntity run, JsonNode payload, JsonNode envelope, Instant now) {
        UUID interruptId = UUID.fromString(payload.path("interrupt_id").asText());
        if (approvals.findByInterruptId(interruptId).isPresent()) {
            return;
        }
        ApprovalRequestEntity row = new ApprovalRequestEntity();
        JsonNode engineApprovalId = payload.get("approval_id");
        if (engineApprovalId != null && engineApprovalId.isTextual() && !engineApprovalId.asText().isBlank()) {
            row.setId(UUID.fromString(engineApprovalId.asText()));
        } else {
            row.setId(UUID.randomUUID());
        }
        row.setExecutionId(run.getId());
        row.setWorkspaceId(run.getWorkspaceId());
        row.setProjectId(run.getProjectId());
        JsonNode nodeId = payload.get("node_id");
        if (nodeId != null && nodeId.isTextual()) {
            row.setNodeId(UUID.fromString(nodeId.asText()));
        } else if (envelope.path("subject").path("node_id").isTextual()) {
            row.setNodeId(UUID.fromString(envelope.path("subject").path("node_id").asText()));
        }
        row.setInterruptId(interruptId);
        row.setStatus("PENDING");
        row.setRequestJson(payload.path("approval_request").toString());
        row.setCreatedAt(now);
        row.setUpdatedAt(now);
        approvals.save(row);
    }

    private void upsertNode(UUID runId, JsonNode envelope, JsonNode payload, Instant now) {
        UUID nodeId = UUID.fromString(envelope.path("subject").path("node_id").asText());
        int attempt = payload.path("attempt").asInt(1);
        NodeExecutionEntity node = nodes.findByExecutionIdAndNodeIdAndAttempt(runId, nodeId, attempt)
                .orElseGet(() -> {
                    NodeExecutionEntity created = new NodeExecutionEntity();
                    created.setId(UUID.randomUUID());
                    created.setExecutionId(runId);
                    created.setNodeId(nodeId);
                    created.setAttempt(attempt);
                    created.setStatus("RUNNING");
                    return created;
                });
        String type = envelope.path("message_type").asText();
        if ("node.started".equals(type)) {
            node.setStatus("RUNNING");
            node.setStartedAt(now);
            if (payload.has("inputs")) {
                node.setInputJson(payload.get("inputs").toString());
            }
        } else if ("node.completed".equals(type)) {
            node.setStatus("SUCCEEDED");
            node.setFinishedAt(now);
            if (payload.has("outputs")) {
                node.setOutputJson(payload.get("outputs").toString());
            }
            ExecutionEntity run = executions.findById(runId).orElse(null);
            if (run != null) {
                artifacts.persistRefs(
                        run.getWorkspaceId(),
                        run.getProjectId(),
                        runId,
                        null,
                        payload.get("artifact_refs"),
                        now);
            }
        } else {
            node.setStatus("FAILED");
            node.setFinishedAt(now);
            if (payload.has("error")) {
                node.setErrorJson(payload.get("error").toString());
            }
        }
        nodes.save(node);
    }

    private void transition(ExecutionEntity run, String target) {
        if (run.getStatus().equals(target)) {
            return;
        }
        if (!ExecutionStateMachine.isLegal(run.getStatus(), target)) {
            run.setQuarantined(true);
            log.warn("illegal transition run={} from={} to={}", run.getId(), run.getStatus(), target);
            return;
        }
        run.setStatus(target);
    }

    private void remember(UUID messageId) {
        ConsumedMessageEntity consumed = new ConsumedMessageEntity();
        consumed.setConsumerName(MessagingNames.CONSUMER_NAME);
        consumed.setMessageId(messageId);
        consumed.setConsumedAt(clock.instant());
        inbox.save(consumed);
    }
}
