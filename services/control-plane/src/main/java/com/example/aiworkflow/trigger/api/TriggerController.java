package com.example.aiworkflow.trigger.api;

import com.example.aiworkflow.security.CurrentUser;
import com.example.aiworkflow.trigger.application.TriggerService;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/projects/{projectId}/workflows/{workflowId}/triggers")
public class TriggerController {

    private final TriggerService triggers;
    private final CurrentUser currentUser;

    public TriggerController(TriggerService triggers, CurrentUser currentUser) {
        this.triggers = triggers;
        this.currentUser = currentUser;
    }

    @GetMapping
    public List<TriggerDtos.TriggerResponse> list(@PathVariable UUID projectId, @PathVariable UUID workflowId) {
        return triggers.list(currentUser.requireUserId(), projectId, workflowId);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public TriggerDtos.TriggerResponse create(
            @PathVariable UUID projectId,
            @PathVariable UUID workflowId,
            @Valid @RequestBody TriggerDtos.CreateTriggerRequest request) {
        return triggers.create(currentUser.requireUserId(), projectId, workflowId, request);
    }

    @PatchMapping("/{triggerId}")
    public TriggerDtos.TriggerResponse patch(
            @PathVariable UUID projectId,
            @PathVariable UUID workflowId,
            @PathVariable UUID triggerId,
            @Valid @RequestBody TriggerDtos.PatchTriggerRequest request) {
        return triggers.patch(currentUser.requireUserId(), projectId, workflowId, triggerId, request);
    }

    @DeleteMapping("/{triggerId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(
            @PathVariable UUID projectId, @PathVariable UUID workflowId, @PathVariable UUID triggerId) {
        triggers.delete(currentUser.requireUserId(), projectId, workflowId, triggerId);
    }
}
