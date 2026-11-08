package com.example.aiworkflow.security;

import com.example.aiworkflow.common.problem.ProblemJson;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * User access tokens cannot call /internal/**; service tokens cannot call /api/v1/**.
 */
public class TokenAudienceFilter extends OncePerRequestFilter {

    private final ObjectMapper objectMapper;

    public TokenAudienceFilter(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String path = request.getRequestURI();
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getPrincipal() instanceof Jwt jwt) {
            boolean service = "service".equals(jwt.getClaimAsString("typ"));
            if (path.startsWith("/internal/") && !service) {
                write(request, response, HttpStatus.UNAUTHORIZED, "UNAUTHENTICATED", "Service authentication required");
                return;
            }
            if (path.startsWith("/api/") && service) {
                write(request, response, HttpStatus.FORBIDDEN, "FORBIDDEN", "Access denied");
                return;
            }
        }
        chain.doFilter(request, response);
    }

    private void write(
            HttpServletRequest request, HttpServletResponse response, HttpStatus status, String code, String title)
            throws IOException {
        UUID correlationId = com.example.aiworkflow.common.problem.CorrelationIdFilter.from(request);
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
        objectMapper.writeValue(response.getOutputStream(), ProblemJson.of(status.value(), code, title, correlationId));
    }
}
