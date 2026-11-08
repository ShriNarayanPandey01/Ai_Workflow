package com.example.aiworkflow.task.api;

import com.example.aiworkflow.common.pagination.CursorPage;
import com.example.aiworkflow.security.CurrentUser;
import com.example.aiworkflow.task.application.TaskService;
import java.util.List;
import java.util.UUID;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class TaskController {

    private final TaskService tasks;
    private final CurrentUser currentUser;

    public TaskController(TaskService tasks, CurrentUser currentUser) {
        this.tasks = tasks;
        this.currentUser = currentUser;
    }

    @GetMapping("/api/v1/projects/{projectId}/executions/{runId}/tasks")
    public List<TaskDtos.TaskSummary> listForRun(@PathVariable UUID projectId, @PathVariable UUID runId) {
        return tasks.listForRun(currentUser.requireUserId(), projectId, runId);
    }

    @GetMapping("/api/v1/projects/{projectId}/tasks/{taskId}")
    public TaskDtos.TaskDetail get(@PathVariable UUID projectId, @PathVariable UUID taskId) {
        return tasks.get(currentUser.requireUserId(), projectId, taskId);
    }

    @GetMapping("/api/v1/projects/{projectId}/tasks/{taskId}/items")
    public CursorPage<TaskDtos.TaskItemView> items(
            @PathVariable UUID projectId,
            @PathVariable UUID taskId,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "20") int limit) {
        return tasks.listItems(currentUser.requireUserId(), projectId, taskId, cursor, limit);
    }

    @PostMapping("/api/v1/projects/{projectId}/tasks/{taskId}/cancel")
    public TaskDtos.TaskCancelResponse cancel(@PathVariable UUID projectId, @PathVariable UUID taskId) {
        return tasks.cancel(currentUser.requireUserId(), projectId, taskId);
    }

    @GetMapping("/api/v1/projects/{projectId}/artifacts/{artifactId}/download")
    public TaskDtos.ArtifactDownloadResponse download(
            @PathVariable UUID projectId, @PathVariable UUID artifactId) {
        return tasks.download(currentUser.requireUserId(), projectId, artifactId);
    }
}
