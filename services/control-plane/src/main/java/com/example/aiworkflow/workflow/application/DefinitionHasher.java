package com.example.aiworkflow.workflow.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import org.springframework.stereotype.Component;

@Component
public class DefinitionHasher {

    private final ObjectMapper canonical;

    public DefinitionHasher(ObjectMapper objectMapper) {
        this.canonical = objectMapper.copy().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    }

    public String sha256(JsonNode definition) {
        try {
            byte[] bytes = canonical.writeValueAsBytes(canonical.treeToValue(definition, Object.class));
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (Exception ex) {
            throw new IllegalStateException("Unable to hash definition");
        }
    }

    public String sha256(String json) {
        try {
            return sha256(canonical.readTree(json.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException("Unable to hash definition");
        }
    }
}
