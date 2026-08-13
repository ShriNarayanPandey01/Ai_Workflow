package com.example.aiworkflow;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.aiworkflow.execution.application.ExecutionProjector;
import com.example.aiworkflow.security.ServiceTokenService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.file.Path;
import java.time.Instant;
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
class ControlPlaneF6F11FlowTest {

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
    ServiceTokenService serviceTokens;

    @Test
    void credentialsExecutionsTriggersApprovals() throws Exception {
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
                                {"name":"Runs"}
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        String projectId = objectMapper.readTree(createdProject.getResponse().getContentAsString())
                .path("projectId")
                .asText();

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/credentials")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"type":"openai_compatible","name":"openai","data":{"apiKey":"sk-live-secret"}}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.maskedHint").value("****cret"))
                .andExpect(jsonPath("$.data").doesNotExist())
                .andExpect(jsonPath("$.apiKey").doesNotExist());

        MvcResult listCreds = mockMvc.perform(get("/api/v1/projects/" + projectId + "/credentials")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andReturn();
        String body = listCreds.getResponse().getContentAsString();
        assertThat(body).doesNotContain("sk-live-secret");
        String credentialId = objectMapper.readTree(body).get(0).path("credentialId").asText();

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
        mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/publish")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isCreated());

        MvcResult start = mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/executions")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"mode":"draft","input":{"order_id":"o-1"},"idempotencyKey":"run-1"}
                                """))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.runId").isString())
                .andReturn();
        String runId = objectMapper.readTree(start.getResponse().getContentAsString()).path("runId").asText();
        mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/executions")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"mode":"draft","input":{"order_id":"o-2"},"idempotencyKey":"run-1"}
                                """))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.runId").value(runId));

        mockMvc.perform(get("/api/v1/projects/" + projectId + "/executions/" + runId)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("QUEUED"));

        mockMvc.perform(post("/internal/v1/executions/" + runId + "/credentials:resolve")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"nodeId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1","slots":["provider"]}
                                """))
                .andExpect(status().isUnauthorized());

        String serviceToken = serviceTokens.issue("execution-worker", UUID.fromString(runId));
        mockMvc.perform(post("/internal/v1/executions/" + runId + "/credentials:resolve")
                        .header("Authorization", "Bearer " + serviceToken)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"nodeId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1","slots":["provider"]}
                                """))
                .andExpect(status().isForbidden());

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/executions/" + runId + "/cancel")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("CANCELLING"));

        MvcResult version = mockMvc.perform(get("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/versions/1")
                        .header("Authorization", "Bearer " + token))
                .andReturn();
        String versionId = objectMapper.readTree(version.getResponse().getContentAsString()).path("versionId").asText();

        MvcResult webhook = mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/triggers")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"type":"webhook","name":"hook","workflowVersionId":"%s","config":{}}
                                """.formatted(versionId)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.secret").isString())
                .andReturn();
        JsonNode trigger = objectMapper.readTree(webhook.getResponse().getContentAsString());
        String publicId = trigger.path("publicId").asText();
        String secret = trigger.path("secret").asText();

        mockMvc.perform(post("/hooks/v1/" + publicId + "/wrong-secret")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"order_id":"from-hook"}
                                """))
                .andExpect(status().isNotFound());
        mockMvc.perform(post("/hooks/v1/" + publicId + "/" + secret)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"order_id":"from-hook"}
                                """))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.runId").isString());

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/triggers")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"type":"schedule","name":"nightly","workflowVersionId":"%s","config":{"cron":"0 0 * * * ?","timeZone":"UTC","input":{"order_id":"sched"}}}
                                """.formatted(versionId)))
                .andExpect(status().isCreated());

        MvcResult publishedStart = mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/executions")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"mode":"published","input":{"order_id":"wait"},"idempotencyKey":"wait-1"}
                                """))
                .andExpect(status().isAccepted())
                .andReturn();
        String waitRunId = objectMapper.readTree(publishedStart.getResponse().getContentAsString()).path("runId").asText();

        ObjectNode started = envelope("execution.started", waitRunId, workflowId, versionId, 1);
        started.set("payload", objectMapper.readTree("""
                {"status":"RUNNING","started_at":"%s"}
                """.formatted(Instant.now())));
        assertThat(projector.apply(started)).isEqualTo(ExecutionProjector.Result.APPLIED);
        assertThat(projector.apply(started)).isEqualTo(ExecutionProjector.Result.DUPLICATE);

        UUID interruptId = UUID.randomUUID();
        UUID engineApprovalId = UUID.randomUUID();
        ObjectNode waiting = envelope("execution.waiting", waitRunId, workflowId, versionId, 2);
        waiting.set(
                "payload",
                objectMapper.readTree(
                        """
                        {"status":"WAITING","waiting_reason":"HUMAN","interrupt_id":"%s","approval_id":"%s","node_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1","approval_request":{"request_payload":{"prompt":"ok?"},"allowed_response_schema":{"type":"object"}}}
                        """
                                .formatted(interruptId, engineApprovalId)));
        assertThat(projector.apply(waiting)).isEqualTo(ExecutionProjector.Result.APPLIED);

        MvcResult pending = mockMvc.perform(get("/api/v1/approvals").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].status").value("PENDING"))
                .andReturn();
        String approvalId = objectMapper.readTree(pending.getResponse().getContentAsString()).get(0).path("approvalId").asText();
        assertThat(approvalId).isEqualTo(engineApprovalId.toString());

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/executions/" + waitRunId + "/approvals/" + approvalId + "/decision")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"decision":"APPROVE","payload":{"ok":true}}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("APPROVED"));

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/executions/" + waitRunId + "/approvals/" + approvalId + "/decision")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"decision":"APPROVE"}
                                """))
                .andExpect(status().isConflict());

        mockMvc.perform(delete("/api/v1/projects/" + projectId + "/credentials/" + credentialId)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isNoContent());
    }

    private ObjectNode envelope(String type, String runId, String workflowId, String versionId, int sequence) {
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
        subject.put("workflow_version_id", versionId);
        subject.put("run_id", runId);
        subject.putNull("node_id");
        subject.putNull("task_id");
        subject.putNull("document_id");
        envelope.put("sequence", sequence);
        return envelope;
    }
}
