package com.example.aiworkflow.credential.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.example.aiworkflow.credential.api.CredentialDtos.ResolveResponse;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class CredentialResolveDtoTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void resolveResponse_serializesCredentialsKeyForPythonEngine() throws Exception {
        UUID runId = UUID.randomUUID();
        UUID nodeId = UUID.randomUUID();
        JsonNode secrets = mapper.readTree("{\"provider\":\"sk-test-key-123\"}");

        ResolveResponse response = new ResolveResponse(runId, nodeId, secrets);
        String json = mapper.writeValueAsString(response);
        JsonNode tree = mapper.readTree(json);

        assertThat(tree.has("credentials")).isTrue();
        assertThat(tree.path("credentials").path("provider").asText()).isEqualTo("sk-test-key-123");
        assertThat(tree.has("secrets")).isTrue();
        assertThat(tree.path("secrets").path("provider").asText()).isEqualTo("sk-test-key-123");
    }
}
