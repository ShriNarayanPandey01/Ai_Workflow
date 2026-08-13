package com.example.aiworkflow.security;

import com.example.aiworkflow.common.problem.ProblemJson;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.server.resource.web.authentication.BearerTokenAuthenticationFilter;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain securityFilterChain(
            HttpSecurity http,
            JwtDecoder jwtDecoder,
            AuthRateLimitFilter rateLimitFilter,
            ObjectMapper objectMapper)
            throws Exception {
        TokenAudienceFilter audienceFilter = new TokenAudienceFilter(objectMapper);
        http.csrf(csrf -> csrf.disable())
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth.requestMatchers(
                                "/api/v1/auth/register",
                                "/api/v1/auth/login",
                                "/api/v1/auth/refresh",
                                "/hooks/v1/**",
                                "/actuator/health",
                                "/actuator/health/**")
                        .permitAll()
                        .requestMatchers("/internal/**")
                        .authenticated()
                        .anyRequest()
                        .authenticated())
                .oauth2ResourceServer(oauth -> oauth.jwt(jwt -> jwt.decoder(jwtDecoder)))
                .exceptionHandling(ex -> ex.authenticationEntryPoint((request, response, exception) ->
                                writeProblem(objectMapper, request, response, HttpStatus.UNAUTHORIZED, "UNAUTHENTICATED", "Authentication required"))
                        .accessDeniedHandler((request, response, exception) -> writeProblem(
                                objectMapper, request, response, HttpStatus.FORBIDDEN, "FORBIDDEN", "Access denied")))
                .addFilterBefore(rateLimitFilter, BearerTokenAuthenticationFilter.class)
                .addFilterAfter(audienceFilter, BearerTokenAuthenticationFilter.class);
        return http.build();
    }

    private static void writeProblem(
            ObjectMapper objectMapper,
            HttpServletRequest request,
            HttpServletResponse response,
            HttpStatus status,
            String code,
            String title)
            throws IOException {
        UUID correlationId = com.example.aiworkflow.common.problem.CorrelationIdFilter.from(request);
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
        objectMapper.writeValue(response.getOutputStream(), ProblemJson.of(status.value(), code, title, correlationId));
    }
}
