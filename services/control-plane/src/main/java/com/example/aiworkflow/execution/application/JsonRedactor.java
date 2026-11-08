package com.example.aiworkflow.execution.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Iterator;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

public final class JsonRedactor {

    private static final Set<String> SECRET_KEYS = Set.of(
            "apikey", "api_key", "secret", "password", "token", "authorization", "ciphertext");

    private JsonRedactor() {}

    public static JsonNode redact(JsonNode node) {
        if (node == null || node.isNull() || node.isMissingNode()) {
            return node;
        }
        if (node.isObject()) {
            ObjectNode object = (ObjectNode) node;
            Iterator<Map.Entry<String, JsonNode>> fields = object.fields();
            while (fields.hasNext()) {
                Map.Entry<String, JsonNode> field = fields.next();
                if (SECRET_KEYS.contains(field.getKey().toLowerCase(Locale.ROOT))) {
                    object.put(field.getKey(), "[REDACTED]");
                } else {
                    redact(field.getValue());
                }
            }
        } else if (node.isArray()) {
            ArrayNode array = (ArrayNode) node;
            for (JsonNode child : array) {
                redact(child);
            }
        }
        return node;
    }
}
