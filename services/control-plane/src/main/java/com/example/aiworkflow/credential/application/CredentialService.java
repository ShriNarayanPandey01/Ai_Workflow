package com.example.aiworkflow.credential.application;

import com.example.aiworkflow.audit.application.AuditService;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.config.AiwProperties;
import com.example.aiworkflow.credential.api.CredentialDtos.CreateCredentialRequest;
import com.example.aiworkflow.credential.api.CredentialDtos.CredentialResponse;
import com.example.aiworkflow.credential.api.CredentialDtos.ResolveRequest;
import com.example.aiworkflow.credential.api.CredentialDtos.ResolveResponse;
import com.example.aiworkflow.credential.api.CredentialDtos.UpdateCredentialRequest;
import com.example.aiworkflow.credential.crypto.AesGcmCrypter;
import com.example.aiworkflow.credential.persistence.CredentialEntity;
import com.example.aiworkflow.credential.persistence.CredentialRepository;
import com.example.aiworkflow.execution.persistence.ExecutionEntity;
import com.example.aiworkflow.execution.persistence.ExecutionRepository;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.project.persistence.ProjectEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowDraftRepository;
import com.example.aiworkflow.workflow.persistence.WorkflowVersionRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CredentialService {

    private final ProjectService projects;
    private final CredentialRepository credentials;
    private final ExecutionRepository executions;
    private final WorkflowDraftRepository drafts;
    private final WorkflowVersionRepository versions;
    private final AesGcmCrypter crypter;
    private final AiwProperties properties;
    private final ObjectMapper objectMapper;
    private final AuditService audit;
    private final Clock clock;

    public CredentialService(
            ProjectService projects,
            CredentialRepository credentials,
            ExecutionRepository executions,
            WorkflowDraftRepository drafts,
            WorkflowVersionRepository versions,
            AesGcmCrypter crypter,
            AiwProperties properties,
            ObjectMapper objectMapper,
            AuditService audit,
            Clock clock) {
        this.projects = projects;
        this.credentials = credentials;
        this.executions = executions;
        this.drafts = drafts;
        this.versions = versions;
        this.crypter = crypter;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.audit = audit;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public List<CredentialResponse> list(UUID userId, UUID projectId) {
        projects.requireMember(userId, projectId);
        return credentials.findByProjectIdOrderByCreatedAtDesc(projectId).stream()
                .map(CredentialService::toResponse)
                .toList();
    }

    @Transactional
    public CredentialResponse create(UUID userId, UUID projectId, CreateCredentialRequest request) {
        ProjectEntity project = projects.requireMember(userId, projectId);
        if (credentials.existsByProjectIdAndName(projectId, request.name())) {
            throw new ProblemException(HttpStatus.CONFLICT, "CREDENTIAL_NAME_TAKEN", "Credential name already exists");
        }
        Instant now = clock.instant();
        UUID id = UUID.randomUUID();
        CredentialEntity entity = new CredentialEntity();
        entity.setId(id);
        entity.setWorkspaceId(project.getWorkspaceId());
        entity.setProjectId(projectId);
        entity.setType(request.type());
        entity.setName(request.name());
        seal(entity, request.data());
        entity.setCreatedAt(now);
        entity.setUpdatedAt(now);
        credentials.save(entity);
        audit.record(userId, project.getWorkspaceId(), projectId, "credential.create", "credential", id, null);
        return toResponse(entity);
    }

    @Transactional
    public CredentialResponse update(UUID userId, UUID projectId, UUID credentialId, UpdateCredentialRequest request) {
        ProjectEntity project = projects.requireMember(userId, projectId);
        CredentialEntity entity = credentials
                .findByIdAndProjectId(credentialId, projectId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "CREDENTIAL_NOT_FOUND", "Credential not found"));
        if (request.name() != null && !request.name().isBlank() && !request.name().equals(entity.getName())) {
            if (credentials.existsByProjectIdAndNameAndIdNot(projectId, request.name(), credentialId)) {
                throw new ProblemException(HttpStatus.CONFLICT, "CREDENTIAL_NAME_TAKEN", "Credential name already exists");
            }
            entity.setName(request.name());
        }
        if (request.data() != null && !request.data().isNull()) {
            seal(entity, request.data());
        }
        entity.setUpdatedAt(clock.instant());
        audit.record(userId, project.getWorkspaceId(), projectId, "credential.update", "credential", credentialId, null);
        return toResponse(entity);
    }

    @Transactional
    public void delete(UUID userId, UUID projectId, UUID credentialId) {
        ProjectEntity project = projects.requireMember(userId, projectId);
        CredentialEntity entity = credentials
                .findByIdAndProjectId(credentialId, projectId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "CREDENTIAL_NOT_FOUND", "Credential not found"));
        String id = credentialId.toString();
        if (Boolean.TRUE.equals(drafts.definitionReferencesCredential(id))
                || Boolean.TRUE.equals(versions.definitionReferencesCredential(id))
                || Boolean.TRUE.equals(executions.definitionReferencesCredential(id))) {
            throw new ProblemException(HttpStatus.CONFLICT, "CREDENTIAL_IN_USE", "Credential is still referenced");
        }
        credentials.delete(entity);
        audit.record(userId, project.getWorkspaceId(), projectId, "credential.delete", "credential", credentialId, null);
    }

    @Transactional(readOnly = true)
    public ResolveResponse resolve(UUID runId, ResolveRequest request) {
        if (request == null || request.nodeId() == null || request.slots() == null || request.slots().isEmpty()) {
            throw new ProblemException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "nodeId and slots are required");
        }
        ExecutionEntity run = executions
                .findById(runId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "Run not found"));
        if (request.workflowVersionId() != null
                && (run.getWorkflowVersionId() == null || !request.workflowVersionId().equals(run.getWorkflowVersionId()))) {
            throw new ProblemException(HttpStatus.FORBIDDEN, "CREDENTIAL_SLOT_DENIED", "workflowVersionId does not match run snapshot");
        }
        if (request.workflowVersionId() == null && run.getWorkflowVersionId() != null) {
            throw new ProblemException(HttpStatus.FORBIDDEN, "CREDENTIAL_SLOT_DENIED", "workflowVersionId does not match run snapshot");
        }
        JsonNode definition;
        try {
            definition = objectMapper.readTree(run.getDefinitionJson());
        } catch (Exception ex) {
            throw new ProblemException(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Invalid run snapshot");
        }
        JsonNode node = findNode(definition, request.nodeId());
        if (node == null) {
            throw new ProblemException(HttpStatus.FORBIDDEN, "CREDENTIAL_SLOT_DENIED", "Node is not in the run snapshot");
        }
        JsonNode refs = node.path("credential_refs");
        ObjectNode secrets = objectMapper.createObjectNode();
        for (String slot : request.slots()) {
            JsonNode ref = refs.get(slot);
            if (ref == null || !ref.isTextual()) {
                throw new ProblemException(HttpStatus.FORBIDDEN, "CREDENTIAL_SLOT_DENIED", "Slot is not declared on the run snapshot");
            }
            UUID credentialId = UUID.fromString(ref.asText());
            CredentialEntity credential = credentials
                    .findByIdAndProjectId(credentialId, run.getProjectId())
                    .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "CREDENTIAL_NOT_FOUND", "Credential not found"));
            secrets.set(slot, decryptData(credential));
        }
        return new ResolveResponse(runId, request.nodeId(), secrets);
    }

    private void seal(CredentialEntity entity, JsonNode data) {
        String json;
        try {
            json = objectMapper.writeValueAsString(data);
        } catch (Exception ex) {
            throw new ProblemException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "Invalid credential data");
        }
        byte[] key = crypter.keyFromSecret(properties.credentials().kek());
        byte[] aad = crypter.aad(entity.getId(), entity.getWorkspaceId(), entity.getProjectId(), entity.getType());
        AesGcmCrypter.Sealed sealed = crypter.encrypt(key, json.getBytes(StandardCharsets.UTF_8), aad);
        entity.setCiphertext(sealed.ciphertext());
        entity.setNonce(sealed.nonce());
        entity.setKeyId(properties.credentials().keyId());
        entity.setMaskedHint(AesGcmCrypter.mask(hintSource(data)));
    }

    private JsonNode decryptData(CredentialEntity entity) {
        byte[] key = crypter.keyFromSecret(properties.credentials().kek());
        byte[] aad = crypter.aad(entity.getId(), entity.getWorkspaceId(), entity.getProjectId(), entity.getType());
        byte[] plaintext = crypter.decrypt(key, entity.getCiphertext(), entity.getNonce(), aad);
        try {
            return objectMapper.readTree(new String(plaintext, StandardCharsets.UTF_8));
        } catch (Exception ex) {
            throw new ProblemException(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Unable to decode credential");
        }
    }

    private static String hintSource(JsonNode data) {
        if (data == null) {
            return "";
        }
        if (data.isTextual()) {
            return data.asText();
        }
        Iterator<Map.Entry<String, JsonNode>> fields = data.fields();
        while (fields.hasNext()) {
            JsonNode value = fields.next().getValue();
            if (value != null && value.isTextual() && !value.asText().isBlank()) {
                return value.asText();
            }
        }
        return "";
    }

    private static JsonNode findNode(JsonNode definition, UUID nodeId) {
        JsonNode nodes = definition.path("nodes");
        if (!nodes.isArray()) {
            return null;
        }
        for (JsonNode node : nodes) {
            if (nodeId.toString().equals(node.path("id").asText())) {
                return node;
            }
        }
        return null;
    }

    private static CredentialResponse toResponse(CredentialEntity entity) {
        return new CredentialResponse(
                entity.getId(),
                entity.getProjectId(),
                entity.getType(),
                entity.getName(),
                entity.getMaskedHint(),
                entity.getKeyId(),
                entity.getCreatedAt(),
                entity.getUpdatedAt());
    }
}
