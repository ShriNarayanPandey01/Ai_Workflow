package com.example.aiworkflow.storage;

import com.example.aiworkflow.config.AiwProperties;
import java.time.Clock;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class StorageConfig {

    @Bean
    @ConditionalOnProperty(prefix = "aiw.storage", name = "enabled", havingValue = "false", matchIfMissing = true)
    ObjectStore fakeObjectStore(Clock clock) {
        return new FakeObjectStore(clock);
    }

    @Bean
    @ConditionalOnProperty(prefix = "aiw.storage", name = "enabled", havingValue = "true")
    ObjectStore s3ObjectStore(AiwProperties properties, Clock clock) {
        return new S3ObjectStore(properties.storage(), clock);
    }
}
