package com.example.aiworkflow.common.ids;

import java.util.UUID;

public final class Ids {

    private Ids() {}

    public static UUID parse(String raw, String field) {
        try {
            return UUID.fromString(raw);
        } catch (RuntimeException ex) {
            throw new IllegalArgumentException("Invalid UUID for " + field);
        }
    }
}
