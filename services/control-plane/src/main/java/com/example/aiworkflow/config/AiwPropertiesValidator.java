package com.example.aiworkflow.config;

import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Component;

@Component
public class AiwPropertiesValidator {

    private final AiwProperties properties;

    public AiwPropertiesValidator(AiwProperties properties) {
        this.properties = properties;
    }

    @PostConstruct
    void validate() {
        requireNamed("AIW_JWT_SECRET", properties.jwt().secret(), 32);
        requireNamed("AIW_REFRESH_HASH_SECRET", properties.refresh().hashSecret(), 16);
        requireNamed("AIW_CREDENTIAL_KEK", properties.credentials().kek(), 32);
        String serviceSecret = properties.serviceJwt().secret();
        if (serviceSecret == null || serviceSecret.isBlank()) {
            serviceSecret = properties.jwt().secret();
        }
        requireNamed("AIW_SERVICE_JWT_SECRET", serviceSecret, 32);
    }

    private static void requireNamed(String name, String value, int minLength) {
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("Missing required configuration: " + name);
        }
        if (value.length() < minLength) {
            throw new IllegalStateException(name + " must be at least " + minLength + " characters");
        }
    }
}
