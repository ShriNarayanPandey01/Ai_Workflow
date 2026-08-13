package com.example.aiworkflow.dataset.api;

import com.example.aiworkflow.dataset.application.DatasetService;
import com.example.aiworkflow.security.CurrentUser;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/projects/{projectId}/datasets")
public class DatasetController {

    private final DatasetService datasets;
    private final CurrentUser currentUser;

    public DatasetController(DatasetService datasets, CurrentUser currentUser) {
        this.datasets = datasets;
        this.currentUser = currentUser;
    }

    @GetMapping
    public List<DatasetDtos.DatasetResponse> list(@PathVariable UUID projectId) {
        return datasets.list(currentUser.requireUserId(), projectId);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public DatasetDtos.DatasetResponse create(
            @PathVariable UUID projectId, @Valid @RequestBody DatasetDtos.CreateDatasetRequest request) {
        return datasets.create(currentUser.requireUserId(), projectId, request);
    }

    @PostMapping("/{datasetId}/documents/uploads")
    @ResponseStatus(HttpStatus.CREATED)
    public DatasetDtos.UploadIntentResponse upload(
            @PathVariable UUID projectId,
            @PathVariable UUID datasetId,
            @Valid @RequestBody DatasetDtos.CreateUploadRequest request) {
        return datasets.createUpload(currentUser.requireUserId(), projectId, datasetId, request);
    }

    @PostMapping("/{datasetId}/documents")
    public DatasetDtos.DocumentResponse confirm(
            @PathVariable UUID projectId,
            @PathVariable UUID datasetId,
            @Valid @RequestBody DatasetDtos.ConfirmDocumentRequest request) {
        return datasets.confirm(currentUser.requireUserId(), projectId, datasetId, request);
    }

    @GetMapping("/{datasetId}/documents")
    public List<DatasetDtos.DocumentResponse> listDocuments(
            @PathVariable UUID projectId, @PathVariable UUID datasetId) {
        return datasets.listDocuments(currentUser.requireUserId(), projectId, datasetId);
    }

    @DeleteMapping("/{datasetId}/documents/{documentId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(
            @PathVariable UUID projectId, @PathVariable UUID datasetId, @PathVariable UUID documentId) {
        datasets.deleteDocument(currentUser.requireUserId(), projectId, datasetId, documentId);
    }
}
