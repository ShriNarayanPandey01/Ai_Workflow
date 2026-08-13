package com.example.aiworkflow;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.aiworkflow.execution.application.ExecutionProjector;
import com.example.aiworkflow.messaging.outbox.OutboxMessageEntity;
import com.example.aiworkflow.messaging.outbox.OutboxMessageRepository;
import com.example.aiworkflow.security.ServiceTokenService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@SpringBootTest
@AutoConfigureMockMvc
@Testcontainers(disabledWithoutDocker = true)
class ControlPlaneF12F14FlowTest {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine");

    @Autowired
    MockMvc mockMvc;

    @Autowired
    ObjectMapper objectMapper;

    @Autowired
    ExecutionProjector projector;

    @Autowired
    OutboxMessageRepository outbox;

    @Autowired
    ServiceTokenService serviceTokens;

    @Test
    void datasetsTasksArtifactsAndHealth() throws Exception {
        String email = "user+" + UUID.randomUUID() + "@example.com";
        MvcResult register = mockMvc.perform(post("/api/v1/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","password":"password1","displayName":"Ada"}
                                """.formatted(email)))
                .andExpect(status().isCreated())
                .andReturn();
        String token = objectMapper.readTree(register.getResponse().getContentAsString()).path("accessToken").asText();

        MvcResult createdProject = mockMvc.perform(post("/api/v1/projects")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"name":"Data"}
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        String projectId = objectMapper.readTree(createdProject.getResponse().getContentAsString())
                .path("projectId")
                .asText();

        MvcResult dataset = mockMvc.perform(post("/api/v1/projects/" + projectId + "/datasets")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"name":"kb"}
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        String datasetId = objectMapper.readTree(dataset.getResponse().getContentAsString()).path("datasetId").asText();

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/datasets/" + datasetId + "/documents/uploads")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"originalName":"x.exe","mediaType":"application/octet-stream","sizeBytes":10}
                                """))
                .andExpect(status().isUnprocessableEntity());

        MvcResult upload = mockMvc.perform(post("/api/v1/projects/" + projectId + "/datasets/" + datasetId + "/documents/uploads")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"originalName":"notes.txt","mediaType":"text/plain","sizeBytes":12}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.objectKey").isString())
                .andExpect(jsonPath("$.uploadUrl").isString())
                .andReturn();
        JsonNode intent = objectMapper.readTree(upload.getResponse().getContentAsString());
        String documentId = intent.path("documentId").asText();
        assertThat(intent.path("objectKey").asText()).contains("/datasets/");

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/datasets/" + datasetId + "/documents")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"documentId":"%s","contentHash":"%s"}
                                """.formatted(documentId, "a".repeat(64))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("uploaded"));

        List<OutboxMessageEntity> ingest = outbox.findByMessageType("document.ingest");
        assertThat(ingest).isNotEmpty();
        assertThat(ingest.getLast().getRoutingKey()).isEqualTo("document.ingest.v1");

        ObjectNode started = documentEnvelope("document.ingestion.started", documentId, datasetId);
        started.set("payload", objectMapper.readTree("""
                {"document_id":"%s","dataset_id":"%s","status":"ingesting","version":1}
                """.formatted(documentId, datasetId)));
        assertThat(projector.apply(started)).isEqualTo(ExecutionProjector.Result.APPLIED);
        mockMvc.perform(get("/api/v1/projects/" + projectId + "/datasets/" + datasetId + "/documents")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].status").value("ingesting"));

        mockMvc.perform(delete("/api/v1/projects/" + projectId + "/datasets/" + datasetId + "/documents/" + documentId)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isNoContent());
        assertThat(outbox.findByMessageType("document.delete").getLast().getRoutingKey()).isEqualTo("document.delete.v1");

        String serviceToken = serviceTokens.issue("rag-worker", UUID.fromString(documentId));
        mockMvc.perform(post("/internal/v1/documents/" + documentId + "/download-intent")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(post("/internal/v1/documents/" + documentId + "/download-intent")
                        .header("Authorization", "Bearer " + serviceToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.objectKey").isString())
                .andExpect(jsonPath("$.downloadUrl").isString());

        MvcResult createdWf = mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"name":"Linear"}
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        String workflowId = objectMapper.readTree(createdWf.getResponse().getContentAsString())
                .path("workflowId")
                .asText();
        int revision = objectMapper
                .readTree(mockMvc.perform(get("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/draft")
                                .header("Authorization", "Bearer " + token))
                        .andReturn()
                        .getResponse()
                        .getContentAsString())
                .path("revision")
                .asInt();
        JsonNode linear = objectMapper.readTree(Path.of(System.getProperty("user.dir"))
                .resolve("../../contracts/fixtures/valid/workflow-linear.json")
                .normalize()
                .toFile());
        ((ObjectNode) linear).put("workflow_id", workflowId);
        ((ObjectNode) linear).putNull("workflow_version_id");
        mockMvc.perform(put("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/draft")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"baseRevision":%s,"definition":%s}
                                """.formatted(revision, linear)))
                .andExpect(status().isOk());

        MvcResult start = mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/executions")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"mode":"draft","input":{"order_id":"o-1"},"idempotencyKey":"f12-run"}
                                """))
                .andExpect(status().isAccepted())
                .andReturn();
        String runId = objectMapper.readTree(start.getResponse().getContentAsString()).path("runId").asText();

        UUID taskId = UUID.randomUUID();
        ObjectNode progress = taskEnvelope("task.progress", runId, workflowId, taskId);
        progress.set(
                "payload",
                objectMapper.readTree(
                        """
                        {"task_id":"%s","status":"RUNNING","progress":{"total":2,"completed":1,"failed":0,"skipped":0,"percent":50}}
                        """
                                .formatted(taskId)));
        assertThat(projector.apply(progress)).isEqualTo(ExecutionProjector.Result.APPLIED);

        mockMvc.perform(get("/api/v1/projects/" + projectId + "/executions/" + runId + "/tasks")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].taskId").value(taskId.toString()));

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/tasks/" + taskId + "/cancel")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("CANCELLING"));
        assertThat(outbox.findByMessageType("task.cancel")).isNotEmpty();
        assertThat(outbox.findByMessageType("execution.cancel")).isNotEmpty();

        mockMvc.perform(get("/api/v1/projects/" + projectId + "/artifacts/" + UUID.randomUUID() + "/download")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isNotFound());

        ObjectNode waiting = envelope("execution.waiting", runId, workflowId, 1);
        waiting.set(
                "payload",
                objectMapper.readTree(
                        """
                        {"status":"WAITING","waiting_reason":"TASK","interrupt_id":"%s"}
                        """
                                .formatted(UUID.randomUUID())));
        assertThat(projector.apply(waiting)).isEqualTo(ExecutionProjector.Result.APPLIED);
        mockMvc.perform(get("/api/v1/approvals").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isEmpty());

        mockMvc.perform(get("/actuator/health/readiness")).andExpect(status().isOk());
        mockMvc.perform(get("/actuator/health")).andExpect(status().isOk());
    }

    private ObjectNode documentEnvelope(String type, String documentId, String datasetId) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("message_id", UUID.randomUUID().toString());
        envelope.put("message_type", type);
        envelope.put("schema_version", "1.0");
        envelope.put("occurred_at", Instant.now().toString());
        envelope.put("correlation_id", documentId);
        envelope.putNull("causation_id");
        envelope.put("idempotency_key", type + "-" + documentId);
        ObjectNode tenant = envelope.putObject("tenant");
        tenant.put("workspace_id", UUID.randomUUID().toString());
        tenant.put("project_id", UUID.randomUUID().toString());
        ObjectNode subject = envelope.putObject("subject");
        subject.putNull("workflow_id");
        subject.putNull("workflow_version_id");
        subject.putNull("run_id");
        subject.putNull("node_id");
        subject.putNull("task_id");
        subject.put("document_id", documentId);
        envelope.putNull("sequence");
        return envelope;
    }

    private ObjectNode taskEnvelope(String type, String runId, String workflowId, UUID taskId) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("message_id", UUID.randomUUID().toString());
        envelope.put("message_type", type);
        envelope.put("schema_version", "1.0");
        envelope.put("occurred_at", Instant.now().toString());
        envelope.put("correlation_id", runId);
        envelope.putNull("causation_id");
        envelope.put("idempotency_key", type + "-" + taskId);
        ObjectNode tenant = envelope.putObject("tenant");
        tenant.put("workspace_id", UUID.randomUUID().toString());
        tenant.put("project_id", UUID.randomUUID().toString());
        ObjectNode subject = envelope.putObject("subject");
        subject.put("workflow_id", workflowId);
        subject.putNull("workflow_version_id");
        subject.put("run_id", runId);
        subject.putNull("node_id");
        subject.put("task_id", taskId.toString());
        subject.putNull("document_id");
        envelope.putNull("sequence");
        return envelope;
    }

    private ObjectNode envelope(String type, String runId, String workflowId, int sequence) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("message_id", UUID.randomUUID().toString());
        envelope.put("message_type", type);
        envelope.put("schema_version", "1.0");
        envelope.put("occurred_at", Instant.now().toString());
        envelope.put("correlation_id", runId);
        envelope.putNull("causation_id");
        envelope.put("idempotency_key", type + "-" + sequence);
        ObjectNode tenant = envelope.putObject("tenant");
        tenant.put("workspace_id", UUID.randomUUID().toString());
        tenant.put("project_id", UUID.randomUUID().toString());
        ObjectNode subject = envelope.putObject("subject");
        subject.put("workflow_id", workflowId);
        subject.putNull("workflow_version_id");
        subject.put("run_id", runId);
        subject.putNull("node_id");
        subject.putNull("task_id");
        subject.putNull("document_id");
        envelope.put("sequence", sequence);
        return envelope;
    }
}
