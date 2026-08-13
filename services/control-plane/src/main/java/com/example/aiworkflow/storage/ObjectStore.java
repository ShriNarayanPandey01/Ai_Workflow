package com.example.aiworkflow.storage;

import java.time.Duration;

public interface ObjectStore {

    PresignedObject presignPut(String objectKey, String mediaType, Duration ttl);

    PresignedObject presignGet(String objectKey, Duration ttl);
}
