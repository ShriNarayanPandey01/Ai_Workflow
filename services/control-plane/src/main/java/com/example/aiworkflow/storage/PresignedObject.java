package com.example.aiworkflow.storage;

import java.time.Instant;
import java.util.Map;

public record PresignedObject(String url, Map<String, String> headers, Instant expiresAt) {}
