package com.example.aiworkflow.common.problem;

import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@RestControllerAdvice
public class ProblemExceptionHandler {

    @ExceptionHandler(ProblemException.class)
    public ResponseEntity<ProblemJson> handleProblem(ProblemException ex, HttpServletRequest request) {
        UUID correlationId = CorrelationIdFilter.from(request);
        ProblemJson body =
                ProblemJson.of(ex.status().value(), ex.code(), ex.getMessage(), correlationId, ex.errors());
        return ResponseEntity.status(ex.status()).contentType(MediaType.APPLICATION_PROBLEM_JSON).body(body);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ProblemJson> handleValidation(
            MethodArgumentNotValidException ex, HttpServletRequest request) {
        List<ProblemError> errors = ex.getBindingResult().getFieldErrors().stream()
                .map(err -> ProblemError.of("VALIDATION_ERROR", err.getField() + " " + err.getDefaultMessage()))
                .toList();
        return problem(HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", "Request validation failed", request, errors);
    }

    @ExceptionHandler({HttpMessageNotReadableException.class, MethodArgumentTypeMismatchException.class,
            IllegalArgumentException.class})
    public ResponseEntity<ProblemJson> handleBadRequest(Exception ex, HttpServletRequest request) {
        return problem(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "Invalid request", request, List.of());
    }

    @ExceptionHandler(AuthenticationException.class)
    public ResponseEntity<ProblemJson> handleAuth(AuthenticationException ex, HttpServletRequest request) {
        return problem(HttpStatus.UNAUTHORIZED, "UNAUTHENTICATED", "Authentication required", request, List.of());
    }

    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<ProblemJson> handleDenied(AccessDeniedException ex, HttpServletRequest request) {
        return problem(HttpStatus.FORBIDDEN, "FORBIDDEN", "Access denied", request, List.of());
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ProblemJson> handleGeneric(Exception ex, HttpServletRequest request) {
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Unexpected error", request, List.of());
    }

    private static ResponseEntity<ProblemJson> problem(
            HttpStatus status, String code, String title, HttpServletRequest request, List<ProblemError> errors) {
        UUID correlationId = CorrelationIdFilter.from(request);
        ProblemJson body = ProblemJson.of(status.value(), code, title, correlationId, errors.isEmpty() ? null : errors);
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_PROBLEM_JSON).body(body);
    }
}
