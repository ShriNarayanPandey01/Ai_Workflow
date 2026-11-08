package com.example.aiworkflow.workflow.application.validation;

import com.example.aiworkflow.catalog.ContractsPaths;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaLocation;
import com.networknt.schema.ValidationMessage;
import jakarta.annotation.PostConstruct;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import org.springframework.stereotype.Component;

@Component
public class ContractSchemaValidator {

    private final ContractsPaths paths;
    private final ObjectMapper objectMapper;
    private final JsonSchemaFactory schemaFactory;
    private JsonSchema definitionSchema;
    private JsonSchema conditionSchema;

    public ContractSchemaValidator(
            ContractsPaths paths, ObjectMapper objectMapper, JsonSchemaFactory schemaFactory) {
        this.paths = paths;
        this.objectMapper = objectMapper;
        this.schemaFactory = schemaFactory;
    }

    @PostConstruct
    public void init() {
        definitionSchema = schemaFactory.getSchema(SchemaLocation.of(paths.definitionSchema().toUri().toString()));
        conditionSchema = schemaFactory.getSchema(SchemaLocation.of(paths.conditionSchema().toUri().toString()));
    }

    public List<String> validateDefinition(JsonNode node) {
        return messages(definitionSchema.validate(node));
    }

    public List<String> validateCondition(JsonNode node) {
        return messages(conditionSchema.validate(node));
    }

    public List<String> validateAgainst(JsonNode schemaNode, JsonNode instance) {
        JsonSchema schema = schemaFactory.getSchema(schemaNode);
        return messages(schema.validate(instance));
    }

    public JsonNode parse(String json) {
        try {
            return objectMapper.readTree(json);
        } catch (Exception ex) {
            throw new IllegalArgumentException("Invalid JSON");
        }
    }

    private static List<String> messages(Set<ValidationMessage> errors) {
        List<String> messages = new ArrayList<>();
        for (ValidationMessage error : errors) {
            messages.add(error.getMessage());
        }
        return messages;
    }
}
