package com.example.aiworkflow.credential.api;

import com.example.aiworkflow.credential.application.CredentialService;
import com.example.aiworkflow.security.CurrentUser;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/projects/{projectId}/credentials")
public class CredentialController {

    private final CredentialService credentials;
    private final CurrentUser currentUser;

    public CredentialController(CredentialService credentials, CurrentUser currentUser) {
        this.credentials = credentials;
        this.currentUser = currentUser;
    }

    @GetMapping
    public List<CredentialDtos.CredentialResponse> list(@PathVariable UUID projectId) {
        return credentials.list(currentUser.requireUserId(), projectId);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public CredentialDtos.CredentialResponse create(
            @PathVariable UUID projectId, @Valid @RequestBody CredentialDtos.CreateCredentialRequest request) {
        return credentials.create(currentUser.requireUserId(), projectId, request);
    }

    @PutMapping("/{credentialId}")
    public CredentialDtos.CredentialResponse update(
            @PathVariable UUID projectId,
            @PathVariable UUID credentialId,
            @Valid @RequestBody CredentialDtos.UpdateCredentialRequest request) {
        return credentials.update(currentUser.requireUserId(), projectId, credentialId, request);
    }

    @DeleteMapping("/{credentialId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable UUID projectId, @PathVariable UUID credentialId) {
        credentials.delete(currentUser.requireUserId(), projectId, credentialId);
    }
}
