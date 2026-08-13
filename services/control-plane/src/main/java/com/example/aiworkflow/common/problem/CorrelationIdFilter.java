package com.example.aiworkflow.common.problem;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class CorrelationIdFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-Correlation-Id";
    public static final String MDC_KEY = "correlationId";

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String incoming = request.getHeader(HEADER);
        UUID correlationId;
        try {
            correlationId = incoming == null || incoming.isBlank() ? UUID.randomUUID() : UUID.fromString(incoming);
        } catch (IllegalArgumentException ex) {
            correlationId = UUID.randomUUID();
        }
        request.setAttribute(MDC_KEY, correlationId);
        MDC.put(MDC_KEY, correlationId.toString());
        response.setHeader(HEADER, correlationId.toString());
        try {
            filterChain.doFilter(request, response);
        } finally {
            MDC.remove(MDC_KEY);
        }
    }

    public static UUID from(HttpServletRequest request) {
        Object value = request.getAttribute(MDC_KEY);
        if (value instanceof UUID uuid) {
            return uuid;
        }
        return UUID.randomUUID();
    }
}
