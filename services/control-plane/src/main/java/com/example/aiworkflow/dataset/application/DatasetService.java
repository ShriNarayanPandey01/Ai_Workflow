package com.example.aiworkflow.dataset.application;

import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.config.AiwProperties;
import com.example.aiworkflow.dataset.api.DatasetDtos.ConfirmDocumentRequest;
import com.example.aiworkflow.dataset.api.DatasetDtos.CreateDatasetRequest;
import com.example.aiworkflow.dataset.api.DatasetDtos.CreateUploadRequest;
import com.example.aiworkflow.dataset.api.DatasetDtos.DatasetResponse;
import com.example.aiworkflow.dataset.api.DatasetDtos.DocumentResponse;
import com.example.aiworkflow.dataset.api.DatasetDtos.DownloadIntentResponse;
import com.example.aiworkflow.dataset.api.DatasetDtos.UploadIntentResponse;
import com.example.aiworkflow.dataset.persistence.DatasetEntity;
import com.example.aiworkflow.dataset.persistence.DatasetRepository;
import com.example.aiworkflow.dataset.persistence.DocumentEntity;
import com.example.aiworkflow.dataset.persistence.DocumentRepository;
import com.example.aiworkflow.messaging.envelope.EnvelopeFactory;
import com.example.aiworkflow.messaging.outbox.OutboxWriter;
import com.example.aiworkflow.observability.AiwMetrics;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.project.persistence.ProjectEntity;
import com.example.aiworkflow.storage.ObjectKeys;
import com.example.aiworkflow.storage.ObjectStore;
import com.example.aiworkflow.storage.PresignedObject;
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
public class DatasetService {

    private final ProjectService projects;
    private final DatasetRepository datasets;
    private final DocumentRepository documents;
    private final ObjectStore objectStore;
    private final EnvelopeFactory envelopes;
    private final OutboxWriter outbox;
    private final AiwMetrics metrics;
    private final AiwProperties properties;
    private final ObjectMapper objectMapper;
    private final Clock clock;

    public DatasetService(
            ProjectService projects,
            DatasetRepository datasets,
            DocumentRepository documents,
            ObjectStore objectStore,
            EnvelopeFactory envelopes,
            OutboxWriter outbox,
            AiwMetrics metrics,
            AiwProperties properties,
            ObjectMapper objectMapper,
            Clock clock) {
        this.projects = projects;
        this.datasets = datasets;
        this.documents = documents;
        this.objectStore = objectStore;
        this.envelopes = envelopes;
        this.outbox = outbox;
        this.metrics = metrics;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public List<DatasetResponse> list(UUID userId, UUID projectId) {
        projects.requireMember(userId, projectId);
        return datasets.findByProjectIdOrderByCreatedAtDesc(projectId).stream()
                .map(this::toDataset)
                .toList();
    }

    @Transactional
    public DatasetResponse create(UUID userId, UUID projectId, CreateDatasetRequest request) {
        ProjectEntity project = projects.requireMember(userId, projectId);
        if (datasets.existsByProjectIdAndName(projectId, request.name())) {
            throw new ProblemException(HttpStatus.CONFLICT, "DATASET_NAME_TAKEN", "Dataset name already exists");
        }
        Instant now = clock.instant();
        DatasetEntity entity = new DatasetEntity();
        entity.setId(UUID.randomUUID());
        entity.setWorkspaceId(project.getWorkspaceId());
        entity.setProjectId(projectId);
        entity.setName(request.name());
        entity.setEmbeddingConfigJson(writeJson(request.embeddingConfig()));
        entity.setCreatedAt(now);
        entity.setUpdatedAt(now);
        return toDataset(datasets.save(entity));
    }

    @Transactional
    public UploadIntentResponse createUpload(
            UUID userId, UUID projectId, UUID datasetId, CreateUploadRequest request) {
        DatasetEntity dataset = requireDataset(userId, projectId, datasetId);
        if (!DatasetConstraints.ALLOWED_MEDIA_TYPES.contains(request.mediaType())) {
            throw new ProblemException(HttpStatus.UNPROCESSABLE_ENTITY, "MEDIA_TYPE_REJECTED", "Media type is not allowed");
        }
        if (request.sizeBytes() > DatasetConstraints.MAX_SIZE_BYTES) {
            throw new ProblemException(HttpStatus.UNPROCESSABLE_ENTITY, "DOCUMENT_TOO_LARGE", "Document exceeds 100 MiB");
        }
        Instant now = clock.instant();
        UUID documentId = UUID.randomUUID();
        int version = 1;
        String objectKey = ObjectKeys.document(
                dataset.getWorkspaceId(), projectId, datasetId, documentId, version);
        DocumentEntity document = new DocumentEntity();
        document.setId(documentId);
        document.setWorkspaceId(dataset.getWorkspaceId());
        document.setProjectId(projectId);
        document.setDatasetId(datasetId);
        document.setObjectKey(objectKey);
        document.setOriginalName(request.originalName());
        document.setMediaType(request.mediaType());
        document.setSizeBytes(request.sizeBytes());
        document.setVersion(version);
        document.setStatus("pending_upload");
        document.setCreatedAt(now);
        document.setUpdatedAt(now);
        documents.save(document);
        PresignedObject signed =
                objectStore.presignPut(objectKey, request.mediaType(), properties.storage().presignTtl());
        return new UploadIntentResponse(
                documentId, objectKey, signed.url(), signed.headers(), signed.expiresAt());
    }

    @Transactional
    public DocumentResponse confirm(
            UUID userId, UUID projectId, UUID datasetId, ConfirmDocumentRequest request) {
        DatasetEntity dataset = requireDataset(userId, projectId, datasetId);
        DocumentEntity document = documents
                .findByIdAndDatasetId(request.documentId(), datasetId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "DOCUMENT_NOT_FOUND", "Document not found"));
        if (!"pending_upload".equals(document.getStatus())) {
            throw new ProblemException(HttpStatus.CONFLICT, "DOCUMENT_NOT_CONFIRMABLE", "Document is not awaiting upload");
        }
        Instant now = clock.instant();
        document.setContentHash(request.contentHash());
        document.setStatus("uploaded");
        document.setUpdatedAt(now);
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("dataset_id", datasetId.toString());
        payload.put("document_id", document.getId().toString());
        payload.put("object_key", document.getObjectKey());
        payload.put("content_hash", request.contentHash());
        payload.put("media_type", document.getMediaType());
        payload.put("size_bytes", document.getSizeBytes());
        payload.put("version", document.getVersion());
        payload.put("original_name", document.getOriginalName());
        if (dataset.getEmbeddingConfigJson() != null) {
            payload.set("embedding_config", parse(dataset.getEmbeddingConfigJson()));
        }
        JsonNode envelope = envelopes.documentCommand(
                "document.ingest",
                dataset.getWorkspaceId(),
                projectId,
                document.getId(),
                "ingest:" + document.getId(),
                payload,
                now);
        outbox.enqueue("document", document.getId(), "document.ingest", envelope);
        metrics.incrementIngestQueued();
        return toDocument(document);
    }

    @Transactional(readOnly = true)
    public List<DocumentResponse> listDocuments(UUID userId, UUID projectId, UUID datasetId) {
        requireDataset(userId, projectId, datasetId);
        return documents.findByDatasetIdOrderByCreatedAtDesc(datasetId).stream()
                .map(this::toDocument)
                .toList();
    }

    @Transactional
    public void deleteDocument(UUID userId, UUID projectId, UUID datasetId, UUID documentId) {
        DatasetEntity dataset = requireDataset(userId, projectId, datasetId);
        DocumentEntity document = documents
                .findByIdAndDatasetId(documentId, datasetId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "DOCUMENT_NOT_FOUND", "Document not found"));
        Instant now = clock.instant();
        document.setStatus("deleting");
        document.setUpdatedAt(now);
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("dataset_id", datasetId.toString());
        payload.put("document_id", documentId.toString());
        payload.put("delete_object", true);
        payload.put("delete_vectors", true);
        JsonNode envelope = envelopes.documentCommand(
                "document.delete",
                dataset.getWorkspaceId(),
                projectId,
                documentId,
                "delete:" + documentId,
                payload,
                now);
        outbox.enqueue("document", documentId, "document.delete", envelope);
    }

    @Transactional(readOnly = true)
    public DownloadIntentResponse downloadIntent(UUID documentId) {
        DocumentEntity document = documents
                .findById(documentId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "DOCUMENT_NOT_FOUND", "Document not found"));
        PresignedObject signed =
                objectStore.presignGet(document.getObjectKey(), properties.storage().presignTtl());
        return new DownloadIntentResponse(
                document.getId(), document.getObjectKey(), signed.url(), signed.expiresAt());
    }

    private DatasetEntity requireDataset(UUID userId, UUID projectId, UUID datasetId) {
        projects.requireMember(userId, projectId);
        return datasets.findByIdAndProjectId(datasetId, projectId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "DATASET_NOT_FOUND", "Dataset not found"));
    }

    private DatasetResponse toDataset(DatasetEntity entity) {
        return new DatasetResponse(
                entity.getId(),
                entity.getProjectId(),
                entity.getName(),
                parse(entity.getEmbeddingConfigJson()),
                entity.getCreatedAt(),
                entity.getUpdatedAt());
    }

    private DocumentResponse toDocument(DocumentEntity entity) {
        return new DocumentResponse(
                entity.getId(),
                entity.getDatasetId(),
                entity.getOriginalName(),
                entity.getMediaType(),
                entity.getSizeBytes(),
                entity.getContentHash(),
                entity.getVersion(),
                entity.getStatus(),
                entity.getErrorCode(),
                entity.getChunkCount(),
                entity.getCreatedAt(),
                entity.getUpdatedAt());
    }

    private String writeJson(JsonNode node) {
        if (node == null || node.isNull()) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(node);
        } catch (Exception ex) {
            throw new IllegalStateException("Unable to serialize embedding config");
        }
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
