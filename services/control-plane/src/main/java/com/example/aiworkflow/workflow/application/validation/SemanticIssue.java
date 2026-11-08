package com.example.aiworkflow.workflow.application.validation;

import com.example.aiworkflow.common.problem.ProblemError;
import java.util.UUID;

public record SemanticIssue(String code, String message, UUID nodeId, UUID edgeId, String path) {

    public ProblemError toProblem() {
        return new ProblemError(code, path, nodeId, edgeId, message);
    }
}
