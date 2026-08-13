package com.example.aiworkflow.trigger.application;

import com.example.aiworkflow.audit.application.AuditService;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.execution.application.ExecutionService;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.project.persistence.ProjectEntity;
import com.example.aiworkflow.project.persistence.ProjectRepository;
import com.example.aiworkflow.trigger.api.TriggerDtos.CreateTriggerRequest;
import com.example.aiworkflow.trigger.api.TriggerDtos.PatchTriggerRequest;
import com.example.aiworkflow.trigger.api.TriggerDtos.TriggerResponse;
import com.example.aiworkflow.trigger.persistence.TriggerEntity;
import com.example.aiworkflow.trigger.persistence.TriggerRepository;
import com.example.aiworkflow.workflow.application.WorkflowDraftService;
import com.example.aiworkflow.workflow.persistence.WorkflowEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowRepository;
import com.example.aiworkflow.workflow.persistence.WorkflowVersionEntity;
import com.example.aiworkflow.workflow.persistence.WorkflowVersionRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import java.util.UUID;
import org.quartz.CronScheduleBuilder;
import org.quartz.JobBuilder;
import org.quartz.JobDetail;
import org.quartz.JobKey;
import org.quartz.Scheduler;
import org.quartz.SchedulerException;
import org.quartz.TriggerBuilder;
import org.quartz.TriggerKey;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TriggerService {

    private static final SecureRandom RANDOM = new SecureRandom();

    private final ProjectService projects;
    private final ProjectRepository projectRepository;
    private final WorkflowDraftService drafts;
    private final WorkflowRepository workflows;
    private final WorkflowVersionRepository versions;
    private final TriggerRepository triggers;
    private final ExecutionService executions;
    private final PasswordEncoder passwordEncoder;
    private final Scheduler scheduler;
    private final AuditService audit;
    private final ObjectMapper objectMapper;
    private final Clock clock;

    public TriggerService(
            ProjectService projects,
            ProjectRepository projectRepository,
            WorkflowDraftService drafts,
            WorkflowRepository workflows,
            WorkflowVersionRepository versions,
            TriggerRepository triggers,
            ExecutionService executions,
            PasswordEncoder passwordEncoder,
            Scheduler scheduler,
            AuditService audit,
            ObjectMapper objectMapper,
            Clock clock) {
        this.projects = projects;
        this.projectRepository = projectRepository;
        this.drafts = drafts;
        this.workflows = workflows;
        this.versions = versions;
        this.triggers = triggers;
        this.executions = executions;
        this.passwordEncoder = passwordEncoder;
        this.scheduler = scheduler;
        this.audit = audit;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public List<TriggerResponse> list(UUID userId, UUID projectId, UUID workflowId) {
        drafts.requireWorkflow(userId, projectId, workflowId);
        return triggers.findByWorkflowIdOrderByCreatedAtDesc(workflowId).stream()
                .map(row -> toResponse(row, null))
                .toList();
    }

    @Transactional
    public TriggerResponse create(UUID userId, UUID projectId, UUID workflowId, CreateTriggerRequest request) {
        ProjectEntity project = projects.requireMember(userId, projectId);
        WorkflowEntity workflow = drafts.requireWorkflow(userId, projectId, workflowId);
        String type = request.type().trim().toLowerCase();
        if (!type.equals("webhook") && !type.equals("schedule") && !type.equals("manual")) {
            throw new ProblemException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "Unsupported trigger type");
        }
        WorkflowVersionEntity version = versions
                .findByIdAndWorkflowId(request.workflowVersionId(), workflowId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "VERSION_NOT_FOUND", "Version not found"));
        Instant now = clock.instant();
        TriggerEntity entity = new TriggerEntity();
        entity.setId(UUID.randomUUID());
        entity.setWorkspaceId(project.getWorkspaceId());
        entity.setProjectId(projectId);
        entity.setWorkflowId(workflowId);
        entity.setWorkflowVersionId(version.getId());
        entity.setType(type);
        entity.setName(request.name());
        entity.setStatus("active");
        entity.setConfigJson(request.config() == null ? "{}" : request.config().toString());
        entity.setCreatedAt(now);
        entity.setUpdatedAt(now);
        String plaintextSecret = null;
        if (type.equals("webhook")) {
            entity.setPublicId(UUID.randomUUID());
            plaintextSecret = randomSecret();
            entity.setSecretHash(passwordEncoder.encode(plaintextSecret));
        }
        triggers.save(entity);
        if (type.equals("schedule")) {
            schedule(entity);
        }
        audit.record(userId, project.getWorkspaceId(), projectId, "trigger.create", "trigger", entity.getId(), null);
        return toResponse(entity, plaintextSecret);
    }

    @Transactional
    public TriggerResponse patch(
            UUID userId, UUID projectId, UUID workflowId, UUID triggerId, PatchTriggerRequest request) {
        drafts.requireWorkflow(userId, projectId, workflowId);
        TriggerEntity entity = triggers
                .findByIdAndWorkflowId(triggerId, workflowId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "TRIGGER_NOT_FOUND", "Trigger not found"));
        if (request.status() != null && !request.status().isBlank()) {
            entity.setStatus(request.status().trim().toLowerCase());
        }
        if (request.workflowVersionId() != null) {
            WorkflowVersionEntity version = versions
                    .findByIdAndWorkflowId(request.workflowVersionId(), workflowId)
                    .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "VERSION_NOT_FOUND", "Version not found"));
            entity.setWorkflowVersionId(version.getId());
        }
        if (request.config() != null) {
            entity.setConfigJson(request.config().toString());
        }
        entity.setUpdatedAt(clock.instant());
        if ("schedule".equals(entity.getType())) {
            if ("active".equals(entity.getStatus())) {
                schedule(entity);
            } else {
                unschedule(entity.getId());
            }
        }
        return toResponse(entity, null);
    }

    @Transactional
    public void delete(UUID userId, UUID projectId, UUID workflowId, UUID triggerId) {
        drafts.requireWorkflow(userId, projectId, workflowId);
        TriggerEntity entity = triggers
                .findByIdAndWorkflowId(triggerId, workflowId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "TRIGGER_NOT_FOUND", "Trigger not found"));
        unschedule(entity.getId());
        triggers.delete(entity);
        audit.record(userId, entity.getWorkspaceId(), projectId, "trigger.delete", "trigger", triggerId, null);
    }

    @Transactional
    public UUID handleWebhook(UUID publicId, String secret, JsonNode input) {
        TriggerEntity entity = triggers
                .findByPublicId(publicId)
                .orElseThrow(() -> opaque());
        if (!"webhook".equals(entity.getType()) || !"active".equals(entity.getStatus()) || entity.getSecretHash() == null) {
            throw opaque();
        }
        if (secret == null || !passwordEncoder.matches(secret, entity.getSecretHash())) {
            throw opaque();
        }
        return dispatchInternal(
                entity, input == null ? objectMapper.createObjectNode() : input, "webhook:" + entity.getId() + ":" + UUID.randomUUID());
    }

    @Transactional
    public void dispatchScheduled(UUID triggerId, Instant fireTime) {
        TriggerEntity entity = triggers.findById(triggerId).orElse(null);
        if (entity == null || !"schedule".equals(entity.getType()) || !"active".equals(entity.getStatus())) {
            return;
        }
        JsonNode input = objectMapper.createObjectNode();
        try {
            JsonNode config = objectMapper.readTree(entity.getConfigJson());
            if (config.has("input")) {
                input = config.get("input");
            }
        } catch (Exception ignored) {
            // empty input
        }
        String idempotency = "schedule:" + triggerId + ":" + fireTime.toEpochMilli();
        dispatchInternal(entity, input, idempotency);
    }

    UUID dispatchInternal(TriggerEntity entity, JsonNode input, String idempotencyKey) {
        ProjectEntity project = projectRepository
                .findById(entity.getProjectId())
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "PROJECT_NOT_FOUND", "Project not found"));
        WorkflowEntity workflow = workflows
                .findByIdAndProjectId(entity.getWorkflowId(), entity.getProjectId())
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "WORKFLOW_NOT_FOUND", "Workflow not found"));
        return executions.startFromTrigger(
                null,
                project,
                workflow,
                entity.getWorkflowVersionId(),
                input,
                idempotencyKey,
                entity.getType(),
                entity.getId());
    }

    private ProblemException opaque() {
        return new ProblemException(HttpStatus.NOT_FOUND, "TRIGGER_NOT_FOUND", "Trigger not found");
    }

    private void schedule(TriggerEntity entity) {
        JsonNode config;
        try {
            config = objectMapper.readTree(entity.getConfigJson());
        } catch (Exception ex) {
            throw new ProblemException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "Invalid trigger config");
        }
        String cron = config.path("cron").asText(null);
        if (cron == null || cron.isBlank()) {
            throw new ProblemException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "Schedule trigger requires cron");
        }
        String timeZone = config.path("timeZone").asText("UTC");
        JobDetail job = JobBuilder.newJob(ScheduleTriggerJob.class)
                .withIdentity(jobKey(entity.getId()))
                .usingJobData("triggerId", entity.getId().toString())
                .storeDurably()
                .build();
        org.quartz.Trigger quartzTrigger = TriggerBuilder.newTrigger()
                .withIdentity(triggerKey(entity.getId()))
                .forJob(job)
                .withSchedule(CronScheduleBuilder.cronSchedule(cron)
                        .inTimeZone(java.util.TimeZone.getTimeZone(timeZone))
                        .withMisfireHandlingInstructionDoNothing())
                .build();
        try {
            scheduler.addJob(job, true);
            if (scheduler.checkExists(triggerKey(entity.getId()))) {
                scheduler.rescheduleJob(triggerKey(entity.getId()), quartzTrigger);
            } else {
                scheduler.scheduleJob(quartzTrigger);
            }
        } catch (SchedulerException ex) {
            throw new ProblemException(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Unable to schedule trigger");
        }
    }

    private void unschedule(UUID triggerId) {
        try {
            scheduler.unscheduleJob(triggerKey(triggerId));
            scheduler.deleteJob(jobKey(triggerId));
        } catch (SchedulerException ignored) {
            // best-effort in tests when scheduler is not started
        }
    }

    private static JobKey jobKey(UUID triggerId) {
        return JobKey.jobKey(triggerId.toString(), "aiw-triggers");
    }

    private static TriggerKey triggerKey(UUID triggerId) {
        return TriggerKey.triggerKey(triggerId.toString(), "aiw-triggers");
    }

    private static String randomSecret() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private TriggerResponse toResponse(TriggerEntity entity, String secret) {
        JsonNode config;
        try {
            config = objectMapper.readTree(entity.getConfigJson());
        } catch (Exception ex) {
            config = objectMapper.createObjectNode();
        }
        return new TriggerResponse(
                entity.getId(),
                entity.getWorkflowId(),
                entity.getWorkflowVersionId(),
                entity.getType(),
                entity.getName(),
                entity.getStatus(),
                config,
                entity.getPublicId(),
                secret,
                entity.getCreatedAt(),
                entity.getUpdatedAt());
    }
}
