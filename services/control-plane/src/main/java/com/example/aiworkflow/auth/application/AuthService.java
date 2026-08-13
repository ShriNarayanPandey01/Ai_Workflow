package com.example.aiworkflow.auth.application;

import com.example.aiworkflow.auth.api.AuthDtos.MeResponse;
import com.example.aiworkflow.auth.api.AuthDtos.TokenResponse;
import com.example.aiworkflow.auth.api.AuthDtos.UserResponse;
import com.example.aiworkflow.auth.persistence.RefreshTokenEntity;
import com.example.aiworkflow.auth.persistence.RefreshTokenRepository;
import com.example.aiworkflow.auth.persistence.UserEntity;
import com.example.aiworkflow.auth.persistence.UserRepository;
import com.example.aiworkflow.auth.persistence.WorkspaceEntity;
import com.example.aiworkflow.auth.persistence.WorkspaceMembershipEntity;
import com.example.aiworkflow.auth.persistence.WorkspaceMembershipId;
import com.example.aiworkflow.auth.persistence.WorkspaceMembershipRepository;
import com.example.aiworkflow.auth.persistence.WorkspaceRepository;
import com.example.aiworkflow.audit.application.AuditService;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.config.AiwProperties;
import com.example.aiworkflow.security.AccessTokenService;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Locale;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

    public static final String INVALID_CREDENTIALS = "Invalid email or password";

    private final UserRepository users;
    private final WorkspaceRepository workspaces;
    private final WorkspaceMembershipRepository memberships;
    private final RefreshTokenRepository refreshTokens;
    private final PasswordEncoder passwordEncoder;
    private final AccessTokenService accessTokens;
    private final AiwProperties properties;
    private final AuditService audit;
    private final Clock clock;
    private final SecureRandom random = new SecureRandom();

    public AuthService(
            UserRepository users,
            WorkspaceRepository workspaces,
            WorkspaceMembershipRepository memberships,
            RefreshTokenRepository refreshTokens,
            PasswordEncoder passwordEncoder,
            AccessTokenService accessTokens,
            AiwProperties properties,
            AuditService audit,
            Clock clock) {
        this.users = users;
        this.workspaces = workspaces;
        this.memberships = memberships;
        this.refreshTokens = refreshTokens;
        this.passwordEncoder = passwordEncoder;
        this.accessTokens = accessTokens;
        this.properties = properties;
        this.audit = audit;
        this.clock = clock;
    }

    @Transactional
    public TokenResponse register(String email, String password, String displayName, HttpServletResponse response) {
        String normalized = normalizeEmail(email);
        if (users.existsByEmailNormalized(normalized)) {
            throw new ProblemException(HttpStatus.CONFLICT, "EMAIL_TAKEN", "Email already registered");
        }
        Instant now = clock.instant();
        UUID userId = UUID.randomUUID();
        UserEntity user = new UserEntity();
        user.setId(userId);
        user.setEmailNormalized(normalized);
        user.setPasswordHash(passwordEncoder.encode(password));
        user.setStatus("ACTIVE");
        user.setDisplayName(displayName);
        user.setCreatedAt(now);
        user.setUpdatedAt(now);
        users.save(user);

        UUID workspaceId = UUID.randomUUID();
        WorkspaceEntity workspace = new WorkspaceEntity();
        workspace.setId(workspaceId);
        workspace.setName("Personal");
        workspace.setKind("PERSONAL");
        workspace.setOwnerUserId(userId);
        workspace.setCreatedAt(now);
        workspace.setUpdatedAt(now);
        workspaces.save(workspace);

        WorkspaceMembershipEntity membership = new WorkspaceMembershipEntity();
        membership.setId(new WorkspaceMembershipId(workspaceId, userId));
        membership.setRole("owner");
        membership.setCreatedAt(now);
        memberships.save(membership);

        issueRefresh(userId, UUID.randomUUID(), response);
        audit.record(userId, workspaceId, null, "auth.register", "user", userId, null);
        return tokenResponse(user, workspace);
    }

    @Transactional
    public TokenResponse login(String email, String password, HttpServletResponse response) {
        String normalized = normalizeEmail(email);
        UserEntity user = users.findByEmailNormalized(normalized).orElse(null);
        if (user == null || !passwordEncoder.matches(password, user.getPasswordHash())) {
            throw new ProblemException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", INVALID_CREDENTIALS);
        }
        if (!"ACTIVE".equals(user.getStatus())) {
            throw new ProblemException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", INVALID_CREDENTIALS);
        }
        WorkspaceEntity workspace = personalWorkspace(user.getId());
        issueRefresh(user.getId(), UUID.randomUUID(), response);
        audit.record(user.getId(), workspace.getId(), null, "auth.login", "user", user.getId(), null);
        return tokenResponse(user, workspace);
    }

    @Transactional
    public TokenResponse refresh(HttpServletRequest request, HttpServletResponse response) {
        String raw = readCookie(request);
        if (raw == null) {
            throw new ProblemException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", INVALID_CREDENTIALS);
        }
        Instant now = clock.instant();
        RefreshTokenEntity current = refreshTokens.findByTokenHash(hashRefresh(raw)).orElse(null);
        if (current == null) {
            throw new ProblemException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", INVALID_CREDENTIALS);
        }
        boolean reused = current.getRevokedAt() != null || current.getReplacedById() != null;
        boolean expired = current.getExpiresAt().isBefore(now);
        if (reused || expired) {
            refreshTokens.revokeFamily(current.getFamilyId(), now);
            clearCookie(response);
            audit.record(current.getUserId(), null, null, "auth.refresh_replay", "refresh_token", current.getFamilyId(), null);
            throw new ProblemException(HttpStatus.UNAUTHORIZED, "REFRESH_REPLAY", INVALID_CREDENTIALS);
        }
        UUID successorId = UUID.randomUUID();
        RefreshTokenEntity successor = persistRefresh(current.getUserId(), current.getFamilyId(), successorId, now);
        current.setReplacedById(successor.getId());
        current.setRevokedAt(now);
        refreshTokens.save(current);
        writeCookie(response, successorRawHolder.get());
        UserEntity user = users.findById(current.getUserId()).orElseThrow();
        return tokenResponse(user, personalWorkspace(user.getId()));
    }

    private final ThreadLocal<String> successorRawHolder = new ThreadLocal<>();

    @Transactional
    public void logout(UUID userId, HttpServletRequest request, HttpServletResponse response) {
        String raw = readCookie(request);
        Instant now = clock.instant();
        if (raw != null) {
            refreshTokens.findByTokenHash(hashRefresh(raw)).ifPresent(token -> {
                if (token.getUserId().equals(userId)) {
                    refreshTokens.revokeFamily(token.getFamilyId(), now);
                }
            });
        }
        clearCookie(response);
        audit.record(userId, null, null, "auth.logout", "user", userId, null);
    }

    @Transactional(readOnly = true)
    public MeResponse me(UUID userId) {
        UserEntity user = users.findById(userId)
                .orElseThrow(() -> new ProblemException(HttpStatus.UNAUTHORIZED, "UNAUTHENTICATED", "Authentication required"));
        WorkspaceEntity workspace = personalWorkspace(userId);
        return new MeResponse(toUser(user, workspace));
    }

    private TokenResponse tokenResponse(UserEntity user, WorkspaceEntity workspace) {
        return new TokenResponse(
                accessTokens.issue(user.getId()), "Bearer", accessTokens.expiresInSeconds(), toUser(user, workspace));
    }

    private static UserResponse toUser(UserEntity user, WorkspaceEntity workspace) {
        return new UserResponse(
                user.getId(), user.getEmailNormalized(), user.getDisplayName(), workspace.getId(), workspace.getKind());
    }

    private WorkspaceEntity personalWorkspace(UUID userId) {
        return workspaces
                .findByOwnerUserIdAndKind(userId, "PERSONAL")
                .orElseThrow(() -> new ProblemException(HttpStatus.INTERNAL_SERVER_ERROR, "WORKSPACE_MISSING", "Workspace missing"));
    }

    private void issueRefresh(UUID userId, UUID familyId, HttpServletResponse response) {
        Instant now = clock.instant();
        persistRefresh(userId, familyId, UUID.randomUUID(), now);
        writeCookie(response, successorRawHolder.get());
        successorRawHolder.remove();
    }

    private RefreshTokenEntity persistRefresh(UUID userId, UUID familyId, UUID tokenId, Instant now) {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String raw = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        successorRawHolder.set(raw);
        RefreshTokenEntity entity = new RefreshTokenEntity();
        entity.setId(tokenId);
        entity.setUserId(userId);
        entity.setFamilyId(familyId);
        entity.setTokenHash(hashRefresh(raw));
        entity.setExpiresAt(now.plus(properties.refresh().ttl()));
        entity.setCreatedAt(now);
        return refreshTokens.save(entity);
    }

    private String hashRefresh(String raw) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(
                    properties.refresh().hashSecret().getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] digest = mac.doFinal(raw.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (Exception ex) {
            throw new IllegalStateException("Unable to hash refresh token");
        }
    }

    private void writeCookie(HttpServletResponse response, String raw) {
        var refresh = properties.refresh();
        ResponseCookie cookie = ResponseCookie.from(refresh.cookieName(), raw)
                .httpOnly(true)
                .secure(refresh.cookieSecure())
                .sameSite("Lax")
                .path(refresh.cookiePath())
                .maxAge(refresh.ttl())
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private void clearCookie(HttpServletResponse response) {
        var refresh = properties.refresh();
        ResponseCookie cookie = ResponseCookie.from(refresh.cookieName(), "")
                .httpOnly(true)
                .secure(refresh.cookieSecure())
                .sameSite("Lax")
                .path(refresh.cookiePath())
                .maxAge(0)
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private String readCookie(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) {
            return null;
        }
        String name = properties.refresh().cookieName();
        for (Cookie cookie : cookies) {
            if (name.equals(cookie.getName())) {
                return cookie.getValue();
            }
        }
        return null;
    }

    public static String normalizeEmail(String email) {
        return email.trim().toLowerCase(Locale.ROOT);
    }

    @SuppressWarnings("unused")
    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }
}
