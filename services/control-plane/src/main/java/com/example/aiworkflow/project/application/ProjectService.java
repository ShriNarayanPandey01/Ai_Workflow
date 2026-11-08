package com.example.aiworkflow.project.application;

import com.example.aiworkflow.auth.persistence.WorkspaceMembershipRepository;
import com.example.aiworkflow.auth.persistence.WorkspaceRepository;
import com.example.aiworkflow.common.pagination.CursorPage;
import com.example.aiworkflow.common.pagination.Cursors;
import com.example.aiworkflow.common.problem.ProblemException;
import com.example.aiworkflow.project.api.ProjectDtos.CreateProjectRequest;
import com.example.aiworkflow.project.api.ProjectDtos.PatchProjectRequest;
import com.example.aiworkflow.project.api.ProjectDtos.ProjectResponse;
import com.example.aiworkflow.project.persistence.ProjectEntity;
import com.example.aiworkflow.project.persistence.ProjectRepository;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ProjectService {

    private final ProjectRepository projects;
    private final WorkspaceRepository workspaces;
    private final WorkspaceMembershipRepository memberships;
    private final Clock clock;

    public ProjectService(
            ProjectRepository projects,
            WorkspaceRepository workspaces,
            WorkspaceMembershipRepository memberships,
            Clock clock) {
        this.projects = projects;
        this.workspaces = workspaces;
        this.memberships = memberships;
        this.clock = clock;
    }

    @Transactional
    public ProjectResponse create(UUID userId, CreateProjectRequest request) {
        UUID workspaceId = personalWorkspaceId(userId);
        Instant now = clock.instant();
        ProjectEntity entity = new ProjectEntity();
        entity.setId(UUID.randomUUID());
        entity.setWorkspaceId(workspaceId);
        entity.setName(request.name());
        entity.setDescription(request.description());
        entity.setCreatedAt(now);
        entity.setUpdatedAt(now);
        return toResponse(projects.save(entity));
    }

    @Transactional(readOnly = true)
    public CursorPage<ProjectResponse> list(UUID userId, String cursor, int limit) {
        UUID workspaceId = personalWorkspaceId(userId);
        int capped = Math.min(Math.max(limit, 1), 100);
        Cursors.Key key = cursor == null ? null : Cursors.decode(cursor);
        List<ProjectEntity> rows = projects.listPage(
                workspaceId,
                key == null ? null : key.createdAt(),
                key == null ? null : key.id(),
                org.springframework.data.domain.PageRequest.of(0, capped + 1));
        List<ProjectEntity> page = rows.size() > capped ? rows.subList(0, capped) : rows;
        String next = rows.size() > capped
                ? Cursors.encode(page.get(page.size() - 1).getCreatedAt(), page.get(page.size() - 1).getId())
                : null;
        return new CursorPage<>(page.stream().map(ProjectService::toResponse).toList(), next);
    }

    @Transactional(readOnly = true)
    public ProjectResponse get(UUID userId, UUID projectId) {
        return toResponse(requireMember(userId, projectId));
    }

    @Transactional
    public ProjectResponse patch(UUID userId, UUID projectId, PatchProjectRequest request) {
        ProjectEntity entity = requireMember(userId, projectId);
        if (request.name() != null && !request.name().isBlank()) {
            entity.setName(request.name());
        }
        if (request.description() != null) {
            entity.setDescription(request.description());
        }
        entity.setUpdatedAt(clock.instant());
        return toResponse(projects.save(entity));
    }

    public ProjectEntity requireMember(UUID userId, UUID projectId) {
        ProjectEntity project = projects.findById(projectId)
                .orElseThrow(() -> new ProblemException(HttpStatus.NOT_FOUND, "PROJECT_NOT_FOUND", "Project not found"));
        if (!memberships.existsByIdWorkspaceIdAndIdUserId(project.getWorkspaceId(), userId)) {
            throw new ProblemException(HttpStatus.NOT_FOUND, "PROJECT_NOT_FOUND", "Project not found");
        }
        return project;
    }

    private UUID personalWorkspaceId(UUID userId) {
        return workspaces
                .findByOwnerUserIdAndKind(userId, "PERSONAL")
                .orElseThrow(() -> new ProblemException(HttpStatus.INTERNAL_SERVER_ERROR, "WORKSPACE_MISSING", "Workspace missing"))
                .getId();
    }

    private static ProjectResponse toResponse(ProjectEntity entity) {
        return new ProjectResponse(
                entity.getId(),
                entity.getWorkspaceId(),
                entity.getName(),
                entity.getDescription(),
                entity.getCreatedAt(),
                entity.getUpdatedAt());
    }
}
