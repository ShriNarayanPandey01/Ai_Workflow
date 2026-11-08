package com.example.aiworkflow.common.problem;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.UUID;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record ProblemJson(
        String type,
        String title,
        int status,
        String code,
        UUID correlationId,
        List<ProblemError> errors) {

    public static ProblemJson of(int status, String code, String title, UUID correlationId) {
        return new ProblemJson(
                "https://errors.example.dev/" + code.toLowerCase().replace('_', '-'),
                title,
                status,
                code,
                correlationId,
                null);
    }

    public static ProblemJson of(
            int status, String code, String title, UUID correlationId, List<ProblemError> errors) {
        return new ProblemJson(
                "https://errors.example.dev/" + code.toLowerCase().replace('_', '-'),
                title,
                status,
                code,
                correlationId,
                errors);
    }
}
