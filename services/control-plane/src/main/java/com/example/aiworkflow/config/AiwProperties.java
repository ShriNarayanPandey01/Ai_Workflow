package com.example.aiworkflow.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties(prefix = "aiw")
public record AiwProperties(
        Jwt jwt,
        Refresh refresh,
        Contracts contracts,
        Limits limits,
        Auth auth,
        Credentials credentials,
        ServiceJwt serviceJwt,
        Messaging messaging,
        Storage storage) {

    public record Jwt(
            String secret,
            @DefaultValue("PT10M") Duration accessTtl) {}

    public record Refresh(
            String hashSecret,
            @DefaultValue("PT720H") Duration ttl,
            @DefaultValue("aiw_refresh") String cookieName,
            @DefaultValue("false") boolean cookieSecure,
            @DefaultValue("/api/v1/auth") String cookiePath) {}

    public record Contracts(@DefaultValue("../../contracts") String root) {}

    public record Limits(
            @DefaultValue("500") int maxGraphNodes,
            @DefaultValue("100") int maxLoopIterations,
            @DefaultValue("86400") int maxRunSeconds,
            @DefaultValue("10000") int maxFanOutItems) {}

    public record Auth(@DefaultValue("20") int rateLimitPerMinute) {}

    public record Credentials(
            @DefaultValue("development-only-credential-kek-must-be-32b") String kek,
            @DefaultValue("v1") String keyId) {}

    public record ServiceJwt(
            String secret,
            @DefaultValue("PT5M") Duration ttl,
            @DefaultValue("control-plane") String audience) {}

    public record Messaging(
            @DefaultValue("true") boolean enabled,
            @DefaultValue("PT2S") Duration publishInterval,
            @DefaultValue("20") int publishBatchSize) {}

    public record Storage(
            @DefaultValue("false") boolean enabled,
            @DefaultValue("http://localhost:9000") String endpoint,
            @DefaultValue("aiw") String bucket,
            @DefaultValue("aiw") String accessKey,
            @DefaultValue("aiwsecret") String secretKey,
            @DefaultValue("us-east-1") String region,
            @DefaultValue("true") boolean pathStyle,
            @DefaultValue("PT15M") Duration presignTtl) {}
}
