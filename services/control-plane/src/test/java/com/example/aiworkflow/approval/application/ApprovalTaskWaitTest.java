package com.example.aiworkflow.approval.application;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

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
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ApprovalTaskWaitTest {

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

    @Test
    void decide_doesNotResumeTaskWaits() {
        ObjectMapper mapper = new ObjectMapper();
        Clock clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);
        ApprovalService service = new ApprovalService(
                approvals,
                projects,
                executions,
                memberships,
                new EnvelopeFactory(mapper),
                outbox,
                audit,
                mapper,
                clock);
        UUID userId = UUID.randomUUID();
        UUID projectId = UUID.randomUUID();
        UUID runId = UUID.randomUUID();
        UUID approvalId = UUID.randomUUID();
        ExecutionEntity run = new ExecutionEntity();
        run.setId(runId);
        run.setWaitingReason("TASK");
        run.setStatus("WAITING");
        when(executions.requireRun(userId, projectId, runId)).thenReturn(run);
        ApprovalRequestEntity row = new ApprovalRequestEntity();
        row.setId(approvalId);
        row.setExecutionId(runId);
        row.setStatus("PENDING");
        when(approvals.findByIdAndExecutionId(approvalId, runId)).thenReturn(Optional.of(row));
        assertThatThrownBy(() ->
                        service.decide(userId, projectId, runId, approvalId, new DecisionRequest("APPROVE", mapper.createObjectNode())))
                .isInstanceOf(ProblemException.class)
                .extracting(ex -> ((ProblemException) ex).code())
                .isEqualTo("TASK_WAIT");
        verify(outbox, never()).enqueue(eq("execution"), any(), eq("execution.resume"), any());
    }
}
