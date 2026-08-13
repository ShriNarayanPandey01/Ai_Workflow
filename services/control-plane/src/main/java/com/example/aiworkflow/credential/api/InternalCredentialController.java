package com.example.aiworkflow.credential.api;

import com.example.aiworkflow.credential.application.CredentialService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class InternalCredentialController {

    private final CredentialService credentials;

    public InternalCredentialController(CredentialService credentials) {
        this.credentials = credentials;
    }

    @PostMapping("/internal/v1/executions/{runId}/credentials:resolve")
    public CredentialDtos.ResolveResponse resolve(
            @PathVariable UUID runId, @Valid @RequestBody CredentialDtos.ResolveRequest request) {
        return credentials.resolve(runId, request);
    }
}
