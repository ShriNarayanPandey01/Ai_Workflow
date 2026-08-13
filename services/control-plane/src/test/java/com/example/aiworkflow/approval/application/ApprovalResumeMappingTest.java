package com.example.aiworkflow.approval.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.aiworkflow.approval.api.ApprovalDtos.DecisionRequest;
import com.example.aiworkflow.approval.persistence.ApprovalRequestEntity;
import com.example.aiworkflow.approval.persistence.ApprovalRequestRepository;
import com.example.aiworkflow.audit.application.AuditService;
import com.example.aiworkflow.auth.persistence.WorkspaceMembershipRepository;
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
class ApprovalResumeMappingTest {

    @Mock
    ApprovalRequestRepository approvals;

    @Mock
    ProjectService projects;

    @Mock
    ExecutionService executions;

    @Mock
    WorkspaceMembershipRepository memberships;

    @Mock
    OutboxWriter outbox;

    @Mock
    AuditService audit;

    private ApprovalService service;
    private final ObjectMapper mapper = new ObjectMapper();
    private final Clock clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);

    @BeforeEach
    void setup() {
        service = new ApprovalService(
                approvals,
                projects,
                executions,
                memberships,
                new EnvelopeFactory(mapper),
                outbox,
                audit,
                mapper,
                clock);
    }

    @Test
    void resumeDecision_mapsApproveToEngineShape() {
        ObjectNode payload = mapper.createObjectNode();
        payload.set("data", mapper.createObjectNode().put("note", "ok"));
        JsonNode resume = service.resumeDecision("APPROVE", payload);
        assertThat(resume.path("decision").asText()).isEqualTo("approved");
        assertThat(resume.path("data").path("note").asText()).isEqualTo("ok");
    }

    @Test
    void resumeDecision_mapsRejectToEngineShape() {
        assertThat(service.resumeDecision("REJECT", null).path("decision").asText()).isEqualTo("rejected");
    }

    @Test
    void decide_enqueuesApprovedResume() {
        UUID userId = UUID.randomUUID();
        UUID projectId = UUID.randomUUID();
        UUID runId = UUID.randomUUID();
        UUID approvalId = UUID.randomUUID();
        ExecutionEntity run = new ExecutionEntity();
        run.setId(runId);
        run.setWorkspaceId(UUID.randomUUID());
        run.setProjectId(projectId);
        run.setWorkflowId(UUID.randomUUID());
        run.setStatus("WAITING");
        run.setWaitingReason("HUMAN");
        when(executions.requireRun(userId, projectId, runId)).thenReturn(run);
        ApprovalRequestEntity row = new ApprovalRequestEntity();
        row.setId(approvalId);
        row.setExecutionId(runId);
        row.setInterruptId(UUID.randomUUID());
        row.setStatus("PENDING");
        when(approvals.findByIdAndExecutionId(approvalId, runId)).thenReturn(Optional.of(row));
        ObjectNode payload = mapper.createObjectNode();
        payload.set("data", mapper.createObjectNode().put("note", "ok"));
        service.decide(userId, projectId, runId, approvalId, new DecisionRequest("APPROVE", payload));
        ArgumentCaptor<JsonNode> envelope = ArgumentCaptor.forClass(JsonNode.class);
        verify(outbox).enqueue(eq("execution"), eq(runId), eq("execution.resume"), envelope.capture());
        assertThat(envelope.getValue().path("payload").path("decision").path("decision").asText())
                .isEqualTo("approved");
        assertThat(row.getDecisionJson()).contains("APPROVE");
    }
}
