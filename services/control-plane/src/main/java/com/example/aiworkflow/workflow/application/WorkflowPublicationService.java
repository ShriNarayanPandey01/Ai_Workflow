package com.example.aiworkflow.workflow.application;

import com.example.aiworkflow.audit.application.AuditService;
import com.example.aiworkflow.common.problem.ProblemError;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.workflow.api.WorkflowDtos.ValidateResponse;
import com.example.aiworkflow.workflow.api.WorkflowDtos.VersionDetail;
import com.example.aiworkflow.workflow.api.WorkflowDtos.VersionSummary;
import com.example.aiworkflow.workflow.persistence.WorkflowDraftEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowDraftRepository;
import com.example.aiworkflow.workflow.persistence.WorkflowEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowRepository;
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

@Service
public class WorkflowPublicationService {

    private final WorkflowDraftService drafts;
    private final WorkflowRepository workflows;
    private final WorkflowDraftRepository draftRepository;
    private final WorkflowVersionRepository versions;
    private final WorkflowValidationService validation;
    private final DefinitionHasher hasher;
    private final ObjectMapper objectMapper;
    private final AuditService audit;
    private final Clock clock;

    public WorkflowPublicationService(
            WorkflowDraftService drafts,
            WorkflowRepository workflows,
            WorkflowDraftRepository draftRepository,
            WorkflowVersionRepository versions,
            WorkflowValidationService validation,
            DefinitionHasher hasher,
            ObjectMapper objectMapper,
            AuditService audit,
            Clock clock) {
        this.drafts = drafts;
        this.workflows = workflows;
        this.draftRepository = draftRepository;
        this.versions = versions;
        this.validation = validation;
        this.hasher = hasher;
        this.objectMapper = objectMapper;
        this.audit = audit;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public ValidateResponse validate(UUID userId, UUID projectId, UUID workflowId) {
        drafts.requireWorkflow(userId, projectId, workflowId);
        JsonNode definition = currentDraft(workflowId);
        List<ProblemError> errors = validation.validate(definition);
        if (errors.isEmpty()) {
            return new ValidateResponse(true, List.of());
        }
        throw new ProblemException(
                HttpStatus.UNPROCESSABLE_ENTITY, "WORKFLOW_INVALID", "Workflow validation failed", errors);
    }

    @Transactional
    public VersionDetail publish(UUID userId, UUID projectId, UUID workflowId) {
        drafts.requireWorkflow(userId, projectId, workflowId);
        WorkflowEntity locked = workflows
                .lockById(workflowId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "WORKFLOW_NOT_FOUND", "Workflow not found"));
        JsonNode definition = currentDraft(workflowId);
        validation.parseAndValidateOrThrow(definition.toString());
        Instant now = clock.instant();
        int next = locked.getLatestVersion() + 1;
        UUID versionId = UUID.randomUUID();
        if (definition instanceof ObjectNode objectNode) {
            objectNode.put("workflow_version_id", versionId.toString());
            objectNode.put("workflow_id", workflowId.toString());
        }
        String json;
        try {
            json = objectMapper.writeValueAsString(definition);
        } catch (Exception ex) {
            throw new IllegalStateException("Unable to serialize published definition");
        }
        WorkflowVersionEntity version = new WorkflowVersionEntity();
        version.setId(versionId);
        version.setWorkflowId(workflowId);
        version.setVersionNumber(next);
        version.setDefinitionJson(json);
        version.setDefinitionHash(hasher.sha256(definition));
        version.setPublishedBy(userId);
        version.setPublishedAt(now);
        version.setCreatedAt(now);
        versions.save(version);
        locked.setLatestVersion(next);
        locked.setUpdatedAt(now);
        workflows.save(locked);
        audit.record(userId, locked.getWorkspaceId(), projectId, "workflow.publish", "workflow_version", versionId, null);
        return toDetail(version);
    }

    @Transactional(readOnly = true)
    public List<VersionSummary> listVersions(UUID userId, UUID projectId, UUID workflowId) {
        drafts.requireWorkflow(userId, projectId, workflowId);
        return versions.findByWorkflowIdOrderByVersionNumberDesc(workflowId).stream()
                .map(version -> new VersionSummary(
                        version.getId(), version.getVersionNumber(), version.getDefinitionHash(), version.getPublishedAt()))
                .toList();
    }

    @Transactional(readOnly = true)
    public VersionDetail getVersion(UUID userId, UUID projectId, UUID workflowId, int versionNumber) {
        drafts.requireWorkflow(userId, projectId, workflowId);
        WorkflowVersionEntity version = versions
                .findByWorkflowIdAndVersionNumber(workflowId, versionNumber)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "VERSION_NOT_FOUND", "Version not found"));
        return toDetail(version);
    }

    private JsonNode currentDraft(UUID workflowId) {
        WorkflowDraftEntity draft = draftRepository
                .findById(workflowId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "DRAFT_NOT_FOUND", "Draft not found"));
        try {
            return objectMapper.readTree(draft.getDefinitionJson());
        } catch (Exception ex) {
            throw new IllegalStateException("Stored draft is not valid JSON");
        }
    }

    private VersionDetail toDetail(WorkflowVersionEntity version) {
        try {
            return new VersionDetail(
                    version.getId(),
                    version.getWorkflowId(),
                    version.getVersionNumber(),
                    version.getDefinitionHash(),
                    objectMapper.readTree(version.getDefinitionJson()),
                    version.getPublishedAt());
        } catch (Exception ex) {
            throw new IllegalStateException("Stored version is not valid JSON");
        }
    }
}
