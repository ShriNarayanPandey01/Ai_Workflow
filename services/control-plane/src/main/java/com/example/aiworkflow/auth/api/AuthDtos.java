package com.example.aiworkflow.auth.api;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.UUID;

public final class AuthDtos {

    private AuthDtos() {}

    public record RegisterRequest(
            @Email @NotBlank String email,
            @NotBlank @Size(min = 8, max = 128) String password,
            @NotBlank @Size(max = 255) String displayName) {}

    public record LoginRequest(@Email @NotBlank String email, @NotBlank String password) {}

    public record UserResponse(UUID userId, String email, String displayName, UUID workspaceId, String workspaceKind) {}

    public record TokenResponse(String accessToken, String tokenType, long expiresIn, UserResponse user) {}

    public record MeResponse(UserResponse user) {}
}
