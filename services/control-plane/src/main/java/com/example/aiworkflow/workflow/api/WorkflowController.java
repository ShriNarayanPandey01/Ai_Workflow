package com.example.aiworkflow.workflow.api;

import com.example.aiworkflow.common.pagination.CursorPage;
import com.example.aiworkflow.security.CurrentUser;
import com.example.aiworkflow.workflow.application.WorkflowDraftService;
import com.example.aiworkflow.workflow.application.WorkflowPublicationService;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/projects/{projectId}/workflows")
public class WorkflowController {

    private final WorkflowDraftService drafts;
    private final WorkflowPublicationService publication;
    private final CurrentUser currentUser;

    public WorkflowController(
            WorkflowDraftService drafts, WorkflowPublicationService publication, CurrentUser currentUser) {
        this.drafts = drafts;
        this.publication = publication;
        this.currentUser = currentUser;
    }

    @GetMapping
    public CursorPage<WorkflowDtos.WorkflowSummary> list(
            @PathVariable UUID projectId,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "20") int limit) {
        return drafts.list(currentUser.requireUserId(), projectId, cursor, limit);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public WorkflowDtos.WorkflowSummary create(
            @PathVariable UUID projectId, @Valid @RequestBody WorkflowDtos.CreateWorkflowRequest request) {
        return drafts.create(currentUser.requireUserId(), projectId, request);
    }

    @GetMapping("/{workflowId}")
    public WorkflowDtos.WorkflowSummary get(@PathVariable UUID projectId, @PathVariable UUID workflowId) {
        return drafts.get(currentUser.requireUserId(), projectId, workflowId);
    }

    @GetMapping("/{workflowId}/draft")
    public WorkflowDtos.DraftResponse getDraft(@PathVariable UUID projectId, @PathVariable UUID workflowId) {
        return drafts.getDraft(currentUser.requireUserId(), projectId, workflowId);
    }

    @PutMapping("/{workflowId}/draft")
    public WorkflowDtos.DraftResponse putDraft(
            @PathVariable UUID projectId,
            @PathVariable UUID workflowId,
            @Valid @RequestBody WorkflowDtos.PutDraftRequest request) {
        return drafts.putDraft(currentUser.requireUserId(), projectId, workflowId, request);
    }

    @PostMapping("/{workflowId}/validate")
    public WorkflowDtos.ValidateResponse validate(@PathVariable UUID projectId, @PathVariable UUID workflowId) {
        return publication.validate(currentUser.requireUserId(), projectId, workflowId);
    }

    @PostMapping("/{workflowId}/publish")
    @ResponseStatus(HttpStatus.CREATED)
    public WorkflowDtos.VersionDetail publish(@PathVariable UUID projectId, @PathVariable UUID workflowId) {
        return publication.publish(currentUser.requireUserId(), projectId, workflowId);
    }

    @GetMapping("/{workflowId}/versions")
    public List<WorkflowDtos.VersionSummary> versions(@PathVariable UUID projectId, @PathVariable UUID workflowId) {
        return publication.listVersions(currentUser.requireUserId(), projectId, workflowId);
    }

    @GetMapping("/{workflowId}/versions/{version}")
    public WorkflowDtos.VersionDetail version(
            @PathVariable UUID projectId, @PathVariable UUID workflowId, @PathVariable int version) {
        return publication.getVersion(currentUser.requireUserId(), projectId, workflowId, version);
    }
}
