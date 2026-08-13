package com.example.aiworkflow.dataset.application;

import com.example.aiworkflow.dataset.persistence.DocumentEntity;
import com.example.aiworkflow.dataset.persistence.DocumentRepository;
import com.fasterxml.jackson.databind.JsonNode;
import java.time.Clock;
import java.util.UUID;
import org.springframework.stereotype.Service;

@Service
public class DocumentProjector {

    private final DocumentRepository documents;
    private final Clock clock;

    public DocumentProjector(DocumentRepository documents, Clock clock) {
        this.documents = documents;
        this.clock = clock;
    }

    public void apply(JsonNode envelope) {
        String type = envelope.path("message_type").asText();
        JsonNode payload = envelope.path("payload");
        UUID documentId = UUID.fromString(payload.path("document_id").asText(
                envelope.path("subject").path("document_id").asText()));
        DocumentEntity document = documents.findById(documentId).orElse(null);
        if (document == null) {
            return;
        }
        switch (type) {
            case "document.ingestion.started" -> {
                document.setStatus("ingesting");
                document.setErrorCode(null);
            }
            case "document.ingestion.completed" -> {
                document.setStatus("ready");
                document.setErrorCode(null);
                if (payload.has("chunk_count")) {
                    document.setChunkCount(payload.path("chunk_count").asInt());
                }
                if (payload.hasNonNull("content_hash")) {
                    document.setContentHash(payload.path("content_hash").asText());
                }
            }
            case "document.ingestion.failed" -> {
                document.setStatus("failed");
                document.setErrorCode(payload.path("error_code").asText(null));
            }
            default -> {
                return;
            }
        }
        document.setUpdatedAt(clock.instant());
        documents.save(document);
    }
}
