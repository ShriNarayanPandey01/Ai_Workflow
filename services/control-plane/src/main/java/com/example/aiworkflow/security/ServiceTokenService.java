package com.example.aiworkflow.security;

import com.example.aiworkflow.config.AiwProperties;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.stereotype.Component;

@Component
public class ServiceTokenService {

    private final JwtEncoder encoder;
    private final AiwProperties properties;
    private final Clock clock;

    public ServiceTokenService(JwtEncoder encoder, AiwProperties properties, Clock clock) {
        this.encoder = encoder;
        this.properties = properties;
        this.clock = clock;
    }

    public String issue(String callerService, UUID runId) {
        Instant now = clock.instant();
        var builder = JwtClaimsSet.builder()
                .subject(callerService)
                .audience(java.util.List.of(properties.serviceJwt().audience()))
                .id(UUID.randomUUID().toString())
                .issuedAt(now)
                .expiresAt(now.plus(properties.serviceJwt().ttl()))
                .claim("typ", "service")
                .claim("svc", callerService);
        if (runId != null) {
            builder.claim("run_id", runId.toString());
        }
        JwsHeader header = JwsHeader.with(MacAlgorithm.HS256).build();
        return encoder.encode(JwtEncoderParameters.from(header, builder.build())).getTokenValue();
    }
}
