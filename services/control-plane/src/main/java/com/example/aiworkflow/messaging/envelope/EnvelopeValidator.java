package com.example.aiworkflow.messaging.envelope;

import com.example.aiworkflow.catalog.ContractsPaths;
import com.example.aiworkflow.workflow.application.validation.ContractSchemaValidator;
import com.fasterxml.jackson.databind.JsonNode;
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
public class EnvelopeValidator {

    private final ContractsPaths paths;
    private final JsonSchemaFactory schemaFactory;
    private final ContractSchemaValidator schemas;
    private JsonSchema envelopeSchema;

    public EnvelopeValidator(ContractsPaths paths, JsonSchemaFactory schemaFactory, ContractSchemaValidator schemas) {
        this.paths = paths;
        this.schemaFactory = schemaFactory;
        this.schemas = schemas;
    }

    @PostConstruct
    public void init() {
        envelopeSchema = schemaFactory.getSchema(SchemaLocation.of(paths.envelopeSchema().toUri().toString()));
    }

    public List<String> validate(JsonNode envelope) {
        Set<ValidationMessage> errors = envelopeSchema.validate(envelope);
        List<String> messages = new ArrayList<>();
        for (ValidationMessage error : errors) {
            messages.add(error.getMessage());
        }
        return messages;
    }

    public JsonNode parse(String json) {
        return schemas.parse(json);
    }
}
