package com.example.aiworkflow.project.api;

import com.example.aiworkflow.common.pagination.CursorPage;
import com.example.aiworkflow.project.application.ProjectService;
import com.example.aiworkflow.security.CurrentUser;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/projects")
public class ProjectController {

    private final ProjectService projectService;
    private final CurrentUser currentUser;

    public ProjectController(ProjectService projectService, CurrentUser currentUser) {
        this.projectService = projectService;
        this.currentUser = currentUser;
    }

    @GetMapping
    public CursorPage<ProjectDtos.ProjectResponse> list(
            @RequestParam(required = false) String cursor, @RequestParam(defaultValue = "20") int limit) {
        return projectService.list(currentUser.requireUserId(), cursor, limit);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ProjectDtos.ProjectResponse create(@Valid @RequestBody ProjectDtos.CreateProjectRequest request) {
        return projectService.create(currentUser.requireUserId(), request);
    }

    @GetMapping("/{projectId}")
    public ProjectDtos.ProjectResponse get(@PathVariable UUID projectId) {
        return projectService.get(currentUser.requireUserId(), projectId);
    }

    @PatchMapping("/{projectId}")
    public ProjectDtos.ProjectResponse patch(
            @PathVariable UUID projectId, @Valid @RequestBody ProjectDtos.PatchProjectRequest request) {
        return projectService.patch(currentUser.requireUserId(), projectId, request);
    }
}
