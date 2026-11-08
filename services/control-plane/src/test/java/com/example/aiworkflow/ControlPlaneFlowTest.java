package com.example.aiworkflow;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.cookie;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.servlet.http.Cookie;
import java.nio.file.Path;
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
class ControlPlaneFlowTest {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine");

    @Autowired
    MockMvc mockMvc;

    @Autowired
    ObjectMapper objectMapper;

    @Test
    void authProjectDraftValidatePublish() throws Exception {
        String email = "user+" + UUID.randomUUID() + "@example.com";
        MvcResult register = mockMvc.perform(post("/api/v1/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","password":"password1","displayName":"Ada"}
                                """.formatted(email)))
                .andExpect(status().isCreated())
                .andExpect(cookie().exists("aiw_refresh"))
                .andExpect(jsonPath("$.accessToken").isString())
                .andReturn();
        String token = objectMapper.readTree(register.getResponse().getContentAsString()).path("accessToken").asText();
        Cookie refresh = register.getResponse().getCookie("aiw_refresh");

        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","password":"wrong-password"}
                                """.formatted(email)))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_CREDENTIALS"));

        mockMvc.perform(post("/api/v1/auth/refresh").cookie(refresh))
                .andExpect(status().isOk())
                .andExpect(cookie().exists("aiw_refresh"));

        mockMvc.perform(post("/api/v1/auth/refresh").cookie(refresh))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("REFRESH_REPLAY"));

        MvcResult login = mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","password":"password1"}
                                """.formatted(email)))
                .andExpect(status().isOk())
                .andReturn();
        token = objectMapper.readTree(login.getResponse().getContentAsString()).path("accessToken").asText();

        mockMvc.perform(get("/api/v1/auth/me").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.user.email").value(email));

        MvcResult createdProject = mockMvc.perform(post("/api/v1/projects")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"name":"Demo","description":"First project"}
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        String projectId = objectMapper.readTree(createdProject.getResponse().getContentAsString())
                .path("projectId")
                .asText();

        mockMvc.perform(get("/api/v1/projects/" + UUID.randomUUID()).header("Authorization", "Bearer " + token))
                .andExpect(status().isNotFound());

        mockMvc.perform(patch("/api/v1/projects/" + projectId)
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"description":"Updated"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.description").value("Updated"));

        mockMvc.perform(get("/api/v1/node-catalog").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items").isArray());

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

        MvcResult draft = mockMvc.perform(get("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/draft")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.revision").value(1))
                .andReturn();
        int revision = objectMapper.readTree(draft.getResponse().getContentAsString()).path("revision").asInt();

        JsonNode linear = objectMapper.readTree(
                Path.of(System.getProperty("user.dir")).resolve("../../contracts/fixtures/valid/workflow-linear.json").normalize().toFile());
        ((ObjectNode) linear).put("workflow_id", workflowId);
        ((ObjectNode) linear).putNull("workflow_version_id");

        mockMvc.perform(put("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/draft")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"baseRevision":%s,"definition":%s}
                                """.formatted(revision, linear)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.revision").value(2));

        mockMvc.perform(put("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/draft")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"baseRevision":%s,"definition":%s}
                                """.formatted(revision, linear)))
                .andExpect(status().isConflict());

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/validate")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.valid").value(true));

        mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/publish")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.versionNumber").value(1))
                .andExpect(jsonPath("$.definitionHash").isString());

        mockMvc.perform(get("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/versions/1")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionNumber").value(1));

        JsonNode cycle = objectMapper.readTree(
                Path.of(System.getProperty("user.dir")).resolve("../../contracts/fixtures/invalid/workflow-arbitrary-cycle.json").normalize().toFile());
        ((ObjectNode) cycle).put("workflow_id", workflowId);
        mockMvc.perform(put("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/draft")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"baseRevision":2,"definition":%s}
                                """.formatted(cycle)))
                .andExpect(status().isOk());
        mockMvc.perform(post("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/validate")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.code").value("WORKFLOW_INVALID"));

        mockMvc.perform(get("/api/v1/projects/" + projectId + "/workflows/" + workflowId + "/versions/1")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.definition.nodes").isArray());
        assertThat(true).isTrue();
    }
}
