package com.example.aiworkflow.messaging.envelope;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class EnvelopeFactory {

    private final ObjectMapper objectMapper;

    public EnvelopeFactory(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public ObjectNode command(
            String messageType,
            UUID workspaceId,
            UUID projectId,
            UUID workflowId,
            UUID workflowVersionId,
            UUID runId,
            UUID correlationId,
            UUID causationId,
            String idempotencyKey,
            JsonNode payload,
            Instant occurredAt) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("message_id", UUID.randomUUID().toString());
        envelope.put("message_type", messageType);
        envelope.put("schema_version", "1.0");
        envelope.put("occurred_at", occurredAt.toString());
        envelope.put("correlation_id", correlationId.toString());
        if (causationId == null) {
            envelope.putNull("causation_id");
        } else {
            envelope.put("causation_id", causationId.toString());
        }
        envelope.put("idempotency_key", idempotencyKey);
        ObjectNode tenant = envelope.putObject("tenant");
        tenant.put("workspace_id", workspaceId.toString());
        tenant.put("project_id", projectId.toString());
        ObjectNode subject = envelope.putObject("subject");
        subject.put("workflow_id", workflowId.toString());
        if (workflowVersionId == null) {
            subject.putNull("workflow_version_id");
        } else {
            subject.put("workflow_version_id", workflowVersionId.toString());
        }
        subject.put("run_id", runId.toString());
        subject.putNull("node_id");
        subject.putNull("task_id");
        subject.putNull("document_id");
        envelope.putNull("sequence");
        envelope.set("payload", payload);
        return envelope;
    }

    public ObjectNode documentCommand(
            String messageType,
            UUID workspaceId,
            UUID projectId,
            UUID documentId,
            String idempotencyKey,
            JsonNode payload,
            Instant occurredAt) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("message_id", UUID.randomUUID().toString());
        envelope.put("message_type", messageType);
        envelope.put("schema_version", "1.0");
        envelope.put("occurred_at", occurredAt.toString());
        envelope.put("correlation_id", documentId.toString());
        envelope.putNull("causation_id");
        envelope.put("idempotency_key", idempotencyKey);
        ObjectNode tenant = envelope.putObject("tenant");
        tenant.put("workspace_id", workspaceId.toString());
        tenant.put("project_id", projectId.toString());
        ObjectNode subject = envelope.putObject("subject");
        subject.putNull("workflow_id");
        subject.putNull("workflow_version_id");
        subject.putNull("run_id");
        subject.putNull("node_id");
        subject.putNull("task_id");
        subject.put("document_id", documentId.toString());
        envelope.putNull("sequence");
        envelope.set("payload", payload);
        return envelope;
    }

    public ObjectNode taskCommand(
            String messageType,
            UUID workspaceId,
            UUID projectId,
            UUID workflowId,
            UUID workflowVersionId,
            UUID runId,
            UUID nodeId,
            UUID taskId,
            UUID correlationId,
            String idempotencyKey,
            JsonNode payload,
            Instant occurredAt) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("message_id", UUID.randomUUID().toString());
        envelope.put("message_type", messageType);
        envelope.put("schema_version", "1.0");
        envelope.put("occurred_at", occurredAt.toString());
        envelope.put("correlation_id", correlationId.toString());
        envelope.putNull("causation_id");
        envelope.put("idempotency_key", idempotencyKey);
        ObjectNode tenant = envelope.putObject("tenant");
        tenant.put("workspace_id", workspaceId.toString());
        tenant.put("project_id", projectId.toString());
        ObjectNode subject = envelope.putObject("subject");
        subject.put("workflow_id", workflowId.toString());
        if (workflowVersionId == null) {
            subject.putNull("workflow_version_id");
        } else {
            subject.put("workflow_version_id", workflowVersionId.toString());
        }
        subject.put("run_id", runId.toString());
        if (nodeId == null) {
            subject.putNull("node_id");
        } else {
            subject.put("node_id", nodeId.toString());
        }
        subject.put("task_id", taskId.toString());
        subject.putNull("document_id");
        envelope.putNull("sequence");
        envelope.set("payload", payload);
        return envelope;
    }
}
