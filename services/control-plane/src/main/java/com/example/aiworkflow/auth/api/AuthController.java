package com.example.aiworkflow.auth.api;

import com.example.aiworkflow.auth.application.AuthService;
import com.example.aiworkflow.security.CurrentUser;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final AuthService authService;
    private final CurrentUser currentUser;

    public AuthController(AuthService authService, CurrentUser currentUser) {
        this.authService = authService;
        this.currentUser = currentUser;
    }

    @PostMapping("/register")
    @ResponseStatus(HttpStatus.CREATED)
    public AuthDtos.TokenResponse register(
            @Valid @RequestBody AuthDtos.RegisterRequest request, HttpServletResponse response) {
        return authService.register(request.email(), request.password(), request.displayName(), response);
    }

    @PostMapping("/login")
    public AuthDtos.TokenResponse login(
            @Valid @RequestBody AuthDtos.LoginRequest request, HttpServletResponse response) {
        return authService.login(request.email(), request.password(), response);
    }

    @PostMapping("/refresh")
    public AuthDtos.TokenResponse refresh(HttpServletRequest request, HttpServletResponse response) {
        return authService.refresh(request, response);
    }

    @PostMapping("/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void logout(HttpServletRequest request, HttpServletResponse response) {
        authService.logout(currentUser.requireUserId(), request, response);
    }

    @GetMapping("/me")
    public AuthDtos.MeResponse me() {
        return authService.me(currentUser.requireUserId());
    }
}
