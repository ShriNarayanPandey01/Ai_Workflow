package com.example.aiworkflow.common.pagination;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;

public final class Cursors {

    private Cursors() {}

    public record Key(Instant createdAt, UUID id) {}

    public static String encode(Instant createdAt, UUID id) {
        String raw = createdAt.toString() + "|" + id;
        return Base64.getUrlEncoder().withoutPadding().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }

    public static Key decode(String cursor) {
        if (cursor == null || cursor.isBlank()) {
            return null;
        }
        try {
            String raw = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
            int sep = raw.lastIndexOf('|');
            Instant createdAt = Instant.parse(raw.substring(0, sep));
            UUID id = UUID.fromString(raw.substring(sep + 1));
            return new Key(createdAt, id);
        } catch (RuntimeException ex) {
            throw new IllegalArgumentException("Invalid cursor");
        }
    }
}
