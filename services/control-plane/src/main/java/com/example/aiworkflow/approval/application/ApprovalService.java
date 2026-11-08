package com.example.aiworkflow.approval.application;

import com.example.aiworkflow.approval.api.ApprovalDtos.ApprovalResponse;
import com.example.aiworkflow.approval.api.ApprovalDtos.DecisionRequest;
import com.example.aiworkflow.approval.persistence.ApprovalRequestEntity;
import com.example.aiworkflow.approval.persistence.ApprovalRequestRepository;
import com.example.aiworkflow.audit.application.AuditService;
import com.example.aiworkflow.auth.persistence.WorkspaceMembershipRepository;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.execution.application.ExecutionService;
import com.example.aiworkflow.execution.persistence.ExecutionEntity;
import com.example.aiworkflow.messaging.envelope.EnvelopeFactory;
import com.example.aiworkflow.messaging.outbox.OutboxWriter;
import com.example.aiworkflow.project.application.ProjectService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ApprovalService {

    private final ApprovalRequestRepository approvals;
    private final ProjectService projects;
    private final ExecutionService executions;
    private final WorkspaceMembershipRepository memberships;
    private final EnvelopeFactory envelopes;
    private final OutboxWriter outbox;
    private final AuditService audit;
    private final ObjectMapper objectMapper;
    private final Clock clock;

    public ApprovalService(
            ApprovalRequestRepository approvals,
            ProjectService projects,
            ExecutionService executions,
            WorkspaceMembershipRepository memberships,
            EnvelopeFactory envelopes,
            OutboxWriter outbox,
            AuditService audit,
            ObjectMapper objectMapper,
            Clock clock) {
        this.approvals = approvals;
        this.projects = projects;
        this.executions = executions;
        this.memberships = memberships;
        this.envelopes = envelopes;
        this.outbox = outbox;
        this.audit = audit;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public List<ApprovalResponse> list(UUID userId, UUID projectId) {
        List<ApprovalRequestEntity> rows;
        if (projectId != null) {
            projects.requireMember(userId, projectId);
            rows = approvals.findByProjectIdAndStatusOrderByCreatedAtDesc(projectId, "PENDING");
        } else {
            rows = approvals.findByStatusOrderByCreatedAtDesc("PENDING").stream()
                    .filter(row -> memberships.existsByIdWorkspaceIdAndIdUserId(row.getWorkspaceId(), userId))
                    .toList();
        }
        List<ApprovalResponse> result = new ArrayList<>();
        for (ApprovalRequestEntity row : rows) {
            result.add(toResponse(row));
        }
        return result;
    }

    @Transactional
    public ApprovalResponse decide(UUID userId, UUID projectId, UUID runId, UUID approvalId, DecisionRequest request) {
        ExecutionEntity run = executions.requireRun(userId, projectId, runId);
        ApprovalRequestEntity approval = approvals
                .findByIdAndExecutionId(approvalId, runId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "APPROVAL_NOT_FOUND", "Approval not found"));
        if (!"PENDING".equals(approval.getStatus())) {
            throw new ProblemException(HttpStatus.CONFLICT, "APPROVAL_RESOLVED", "Approval already resolved");
        }
        if ("TASK".equals(run.getWaitingReason())) {
            throw new ProblemException(HttpStatus.CONFLICT, "TASK_WAIT", "Cannot resume TASK waits from approvals");
        }
        if (!"WAITING".equals(run.getStatus()) || !"HUMAN".equals(run.getWaitingReason())) {
            throw new ProblemException(HttpStatus.CONFLICT, "RUN_NOT_WAITING_HUMAN", "Run is not waiting for a human decision");
        }
        if (request == null || request.decision() == null || request.decision().isBlank()) {
            throw new ProblemException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "decision is required");
        }
        String decision = request.decision().trim().toUpperCase();
        if (!decision.equals("APPROVE") && !decision.equals("REJECT") && !decision.equals("EDIT")) {
            throw new ProblemException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "decision must be APPROVE, REJECT, or EDIT");
        }
        Instant now = clock.instant();
        ObjectNode recorded = objectMapper.createObjectNode();
        recorded.put("decision", decision);
        if (request.payload() != null) {
            recorded.set("payload", request.payload());
        }
        approval.setStatus(decision.equals("REJECT") ? "REJECTED" : "APPROVED");
        approval.setDecisionJson(recorded.toString());
        approval.setResolvedBy(userId);
        approval.setResolvedAt(now);
        approval.setUpdatedAt(now);

        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("waiting_reason", "HUMAN");
        payload.put("interrupt_id", approval.getInterruptId().toString());
        payload.put("approval_id", approval.getId().toString());
        payload.putNull("task_id");
        payload.set("decision", resumeDecision(decision, request.payload()));
        JsonNode envelope = envelopes.command(
                "execution.resume",
                run.getWorkspaceId(),
                run.getProjectId(),
                run.getWorkflowId(),
                run.getWorkflowVersionId(),
                run.getId(),
                run.getId(),
                null,
                "resume:" + approval.getId(),
                payload,
                now);
        outbox.enqueue("execution", run.getId(), "execution.resume", envelope);
        audit.record(
                userId,
                run.getWorkspaceId(),
                run.getProjectId(),
                "approval.decision",
                "approval",
                approval.getId(),
                "{\"decision\":\"" + decision + "\"}");
        return toResponse(approval);
    }

    /**
     * Execution-engine human.approval expects decision.decision in {approved, rejected};
     * human.review expects the EDIT payload (including value) as the decision object.
     */
    ObjectNode resumeDecision(String decision, JsonNode requestPayload) {
        if ("EDIT".equals(decision)) {
            if (requestPayload != null && requestPayload.isObject()) {
                return requestPayload.deepCopy();
            }
            return objectMapper.createObjectNode();
        }
        ObjectNode resume = objectMapper.createObjectNode();
        resume.put("decision", "REJECT".equals(decision) ? "rejected" : "approved");
        if (requestPayload != null && !requestPayload.isNull()) {
            if (requestPayload.has("data")) {
                resume.set("data", requestPayload.get("data"));
            } else if (requestPayload.isObject() && requestPayload.size() > 0) {
                resume.set("data", requestPayload);
            }
        }
        return resume;
    }

    private ApprovalResponse toResponse(ApprovalRequestEntity row) {
        return new ApprovalResponse(
                row.getId(),
                row.getExecutionId(),
                row.getProjectId(),
                row.getNodeId(),
                row.getInterruptId(),
                row.getStatus(),
                parse(row.getRequestJson()),
                parse(row.getDecisionJson()),
                row.getCreatedAt());
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
