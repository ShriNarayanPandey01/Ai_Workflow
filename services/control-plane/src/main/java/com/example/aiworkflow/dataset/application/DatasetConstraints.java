package com.example.aiworkflow.dataset.application;

import java.util.Set;

public final class DatasetConstraints {

    public static final Set<String> ALLOWED_MEDIA_TYPES =
            Set.of("application/pdf", "text/plain", "text/markdown", "application/json");

    public static final long MAX_SIZE_BYTES = 104_857_600L;

    private DatasetConstraints() {}
}
