package com.example.aiworkflow.storage;

import java.time.Clock;
import java.time.Duration;
import java.util.Map;

public class FakeObjectStore implements ObjectStore {

    private final Clock clock;

    public FakeObjectStore(Clock clock) {
        this.clock = clock;
    }

    @Override
    public PresignedObject presignPut(String objectKey, String mediaType, Duration ttl) {
        return new PresignedObject(
                "http://localhost/fake-put/" + objectKey,
                Map.of("Content-Type", mediaType),
                clock.instant().plus(ttl));
    }

    @Override
    public PresignedObject presignGet(String objectKey, Duration ttl) {
        return new PresignedObject(
                "http://localhost/fake-get/" + objectKey, Map.of(), clock.instant().plus(ttl));
    }
}
