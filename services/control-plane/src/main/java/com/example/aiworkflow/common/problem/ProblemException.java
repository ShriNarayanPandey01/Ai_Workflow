package com.example.aiworkflow.common.problem;

import java.util.List;
import org.springframework.http.HttpStatus;

public class ProblemException extends RuntimeException {

    private final HttpStatus status;
    private final String code;
    private final List<ProblemError> errors;

    public ProblemException(HttpStatus status, String code, String message) {
        this(status, code, message, List.of());
    }

    public ProblemException(HttpStatus status, String code, String message, List<ProblemError> errors) {
        super(message);
        this.status = status;
        this.code = code;
        this.errors = errors;
    }

    public HttpStatus status() {
        return status;
    }

    public String code() {
        return code;
    }

    public List<ProblemError> errors() {
        return errors;
    }
}
