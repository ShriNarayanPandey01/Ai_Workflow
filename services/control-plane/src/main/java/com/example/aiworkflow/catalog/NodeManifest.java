package com.example.aiworkflow.catalog;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

public record NodeManifest(
        String type,
        JsonNode raw,
        List<PortDefinition> inputs,
        List<PortDefinition> outputs,
        JsonNode configSchema) {

    public Optional<PortDefinition> input(String name) {
        return inputs.stream().filter(port -> port.name().equals(name)).findFirst();
    }

    public Optional<PortDefinition> output(String name) {
        return outputs.stream().filter(port -> port.name().equals(name)).findFirst();
    }

    public String baseType() {
        int at = type.lastIndexOf('@');
        return at < 0 ? type : type.substring(0, at);
    }

    public static NodeManifest from(JsonNode raw) {
        List<PortDefinition> inputs = new ArrayList<>();
        for (JsonNode port : raw.path("inputs")) {
            inputs.add(PortDefinition.from(port));
        }
        List<PortDefinition> outputs = new ArrayList<>();
        for (JsonNode port : raw.path("outputs")) {
            outputs.add(PortDefinition.from(port));
        }
        return new NodeManifest(raw.path("type").asText(), raw, List.copyOf(inputs), List.copyOf(outputs), raw.get("config_schema"));
    }

    public record PortDefinition(String name, boolean required, String cardinality, JsonNode schema) {
        static PortDefinition from(JsonNode node) {
            return new PortDefinition(
                    node.path("name").asText(),
                    node.path("required").asBoolean(false),
                    node.path("cardinality").asText("single"),
                    node.get("schema"));
        }
    }

    public Map<String, PortDefinition> inputsByName() {
        return inputs.stream().collect(java.util.stream.Collectors.toMap(PortDefinition::name, port -> port));
    }
}
