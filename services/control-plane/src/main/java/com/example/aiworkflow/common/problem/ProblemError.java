package com.example.aiworkflow.common.problem;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.UUID;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record ProblemError(String code, String path, UUID nodeId, UUID edgeId, String message) {

    public static ProblemError of(String code, String message) {
        return new ProblemError(code, null, null, null, message);
    }
}
