package com.example.aiworkflow.dataset.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.config.AiwProperties;
import com.example.aiworkflow.dataset.api.DatasetDtos.ConfirmDocumentRequest;
import com.example.aiworkflow.dataset.api.DatasetDtos.CreateUploadRequest;
import com.example.aiworkflow.dataset.persistence.DatasetEntity;
import com.example.aiworkflow.dataset.persistence.DatasetRepository;
import com.example.aiworkflow.dataset.persistence.DocumentEntity;
import com.example.aiworkflow.dataset.persistence.DocumentRepository;
import com.example.aiworkflow.messaging.MessagingNames;
import com.example.aiworkflow.messaging.envelope.EnvelopeFactory;
import com.example.aiworkflow.messaging.outbox.OutboxWriter;
import com.example.aiworkflow.observability.AiwMetrics;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.project.persistence.ProjectEntity;
import com.example.aiworkflow.storage.FakeObjectStore;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Duration;
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
class DatasetServiceTest {

    @Mock
    ProjectService projects;

    @Mock
    DatasetRepository datasets;

    @Mock
    DocumentRepository documents;

    @Mock
    OutboxWriter outbox;

    @Mock
    AiwMetrics metrics;

    private DatasetService service;
    private final ObjectMapper mapper = new ObjectMapper();
    private final Clock clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);
    private final UUID userId = UUID.randomUUID();
    private final UUID projectId = UUID.randomUUID();
    private final UUID workspaceId = UUID.randomUUID();
    private final UUID datasetId = UUID.randomUUID();

    @BeforeEach
    void setup() {
        AiwProperties properties = new AiwProperties(
                new AiwProperties.Jwt("development-only-jwt-secret-must-be-at-least-32-bytes", Duration.ofMinutes(10)),
                new AiwProperties.Refresh(
                        "development-only-refresh-hash-secret",
                        Duration.ofDays(30),
                        "aiw_refresh",
                        false,
                        "/api/v1/auth"),
                new AiwProperties.Contracts("../../contracts"),
                new AiwProperties.Limits(500, 100, 86400, 10000),
                new AiwProperties.Auth(20),
                new AiwProperties.Credentials("development-only-credential-kek-must-be-32b", "v1"),
                new AiwProperties.ServiceJwt(
                        "development-only-jwt-secret-must-be-at-least-32-bytes", Duration.ofMinutes(5), "control-plane"),
                new AiwProperties.Messaging(false, Duration.ofSeconds(2), 20),
                new AiwProperties.Storage(
                        false, "http://localhost:9000", "aiw", "aiw", "aiwsecret", "us-east-1", true, Duration.ofMinutes(15)));
        service = new DatasetService(
                projects,
                datasets,
                documents,
                new FakeObjectStore(clock),
                new EnvelopeFactory(mapper),
                outbox,
                metrics,
                properties,
                mapper,
                clock);
        DatasetEntity dataset = new DatasetEntity();
        dataset.setId(datasetId);
        dataset.setWorkspaceId(workspaceId);
        dataset.setProjectId(projectId);
        dataset.setName("docs");
        when(projects.requireMember(userId, projectId)).thenReturn(project(workspaceId, projectId));
        when(datasets.findByIdAndProjectId(datasetId, projectId)).thenReturn(Optional.of(dataset));
    }

    @Test
    void createUpload_rejectsDisallowedMime() {
        assertThatThrownBy(() -> service.createUpload(
                        userId, projectId, datasetId, new CreateUploadRequest("x.exe", "application/octet-stream", 10L)))
                .isInstanceOf(ProblemException.class)
                .extracting(ex -> ((ProblemException) ex).code())
                .isEqualTo("MEDIA_TYPE_REJECTED");
    }

    @Test
    void confirm_enqueuesDocumentIngestNotExecution() {
        UUID documentId = UUID.randomUUID();
        DocumentEntity document = pending(documentId);
        when(documents.findByIdAndDatasetId(documentId, datasetId)).thenReturn(Optional.of(document));
        String hash = "a".repeat(64);
        service.confirm(userId, projectId, datasetId, new ConfirmDocumentRequest(documentId, hash));
        ArgumentCaptor<String> type = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<JsonNode> envelope = ArgumentCaptor.forClass(JsonNode.class);
        verify(outbox).enqueue(eq("document"), eq(documentId), type.capture(), envelope.capture());
        assertThat(type.getValue()).isEqualTo("document.ingest");
        assertThat(MessagingNames.routingKey(type.getValue())).isEqualTo("document.ingest.v1");
        assertThat(MessagingNames.routingKey(type.getValue())).doesNotContain("execution");
        assertThat(envelope.getValue().path("subject").path("document_id").asText()).isEqualTo(documentId.toString());
        assertThat(envelope.getValue().path("subject").path("run_id").isNull()).isTrue();
        verify(metrics).incrementIngestQueued();
    }

    @Test
    void delete_enqueuesDocumentDelete() {
        UUID documentId = UUID.randomUUID();
        when(documents.findByIdAndDatasetId(documentId, datasetId)).thenReturn(Optional.of(pending(documentId)));
        service.deleteDocument(userId, projectId, datasetId, documentId);
        ArgumentCaptor<String> type = ArgumentCaptor.forClass(String.class);
        verify(outbox).enqueue(eq("document"), eq(documentId), type.capture(), any());
        assertThat(type.getValue()).isEqualTo("document.delete");
        assertThat(MessagingNames.routingKey(type.getValue())).isEqualTo("document.delete.v1");
    }

    private DocumentEntity pending(UUID documentId) {
        DocumentEntity document = new DocumentEntity();
        document.setId(documentId);
        document.setWorkspaceId(workspaceId);
        document.setProjectId(projectId);
        document.setDatasetId(datasetId);
        document.setObjectKey("k");
        document.setOriginalName("a.pdf");
        document.setMediaType("application/pdf");
        document.setSizeBytes(12);
        document.setVersion(1);
        document.setStatus("pending_upload");
        document.setCreatedAt(clock.instant());
        document.setUpdatedAt(clock.instant());
        return document;
    }

    private static ProjectEntity project(UUID workspaceId, UUID projectId) {
        ProjectEntity project = new ProjectEntity();
        project.setId(projectId);
        project.setWorkspaceId(workspaceId);
        return project;
    }
}
