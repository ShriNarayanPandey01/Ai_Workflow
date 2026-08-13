package com.example.aiworkflow.workflow.application;

import com.example.aiworkflow.common.problem.ProblemError;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.workflow.application.validation.ContractSchemaValidator;
import com.example.aiworkflow.workflow.application.validation.SemanticValidator;
import com.fasterxml.jackson.databind.JsonNode;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

@Service
public class WorkflowValidationService {

    private static final int MAX_BYTES = 512 * 1024;

    private final ContractSchemaValidator schemas;
    private final SemanticValidator semanticValidator;

    public WorkflowValidationService(ContractSchemaValidator schemas, SemanticValidator semanticValidator) {
        this.schemas = schemas;
        this.semanticValidator = semanticValidator;
    }

    public List<ProblemError> validate(JsonNode definition) {
        List<ProblemError> errors = new ArrayList<>();
        String raw = definition.toString();
        if (raw.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES) {
            errors.add(ProblemError.of("PAYLOAD_TOO_LARGE", "Workflow definition exceeds size limit"));
            return errors;
        }
        List<String> schemaErrors = schemas.validateDefinition(definition);
        if (!schemaErrors.isEmpty()) {
            String first = schemaErrors.getFirst();
            String code = first.toLowerCase().contains("additional")
                    ? "SCHEMA_ADDITIONAL_PROPERTY"
                    : "SCHEMA_INVALID";
            errors.add(ProblemError.of(code, first));
            return errors;
        }
        semanticValidator.validate(definition).forEach(issue -> errors.add(issue.toProblem()));
        return errors;
    }

    public JsonNode parseAndValidateOrThrow(String json) {
        JsonNode node = schemas.parse(json);
        List<ProblemError> errors = validate(node);
        if (!errors.isEmpty()) {
            throw new ProblemException(
                    HttpStatus.UNPROCESSABLE_ENTITY, "WORKFLOW_INVALID", "Workflow validation failed", errors);
        }
        return node;
    }
}
