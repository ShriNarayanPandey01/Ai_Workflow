package com.example.aiworkflow.approval.api;

import com.example.aiworkflow.approval.application.ApprovalService;
import com.example.aiworkflow.security.CurrentUser;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ApprovalController {

    private final ApprovalService approvals;
    private final CurrentUser currentUser;

    public ApprovalController(ApprovalService approvals, CurrentUser currentUser) {
        this.approvals = approvals;
        this.currentUser = currentUser;
    }

    @GetMapping("/api/v1/approvals")
    public List<ApprovalDtos.ApprovalResponse> list(@RequestParam(required = false) UUID projectId) {
        return approvals.list(currentUser.requireUserId(), projectId);
    }

    @PostMapping("/api/v1/projects/{projectId}/executions/{runId}/approvals/{approvalId}/decision")
    public ApprovalDtos.ApprovalResponse decide(
            @PathVariable UUID projectId,
            @PathVariable UUID runId,
            @PathVariable UUID approvalId,
            @Valid @RequestBody ApprovalDtos.DecisionRequest request) {
        return approvals.decide(currentUser.requireUserId(), projectId, runId, approvalId, request);
    }
}
