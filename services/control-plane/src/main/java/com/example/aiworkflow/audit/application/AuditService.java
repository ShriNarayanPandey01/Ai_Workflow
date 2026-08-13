package com.example.aiworkflow.audit.application;

import com.example.aiworkflow.audit.persistence.AuditEventEntity;
import com.example.aiworkflow.audit.persistence.AuditEventRepository;
import java.time.Clock;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuditService {

    private final AuditEventRepository events;
    private final Clock clock;

    public AuditService(AuditEventRepository events, Clock clock) {
        this.events = events;
        this.clock = clock;
    }

    @Transactional
    public void record(
            UUID actorUserId,
            UUID workspaceId,
            UUID projectId,
            String action,
            String resourceType,
            UUID resourceId,
            String detailsJson) {
        AuditEventEntity entity = new AuditEventEntity();
        entity.setId(UUID.randomUUID());
        entity.setActorUserId(actorUserId);
        entity.setWorkspaceId(workspaceId);
        entity.setProjectId(projectId);
        entity.setAction(action);
        entity.setResourceType(resourceType);
        entity.setResourceId(resourceId);
        entity.setDetailsJson(detailsJson);
        entity.setCreatedAt(clock.instant());
        events.save(entity);
    }
}
