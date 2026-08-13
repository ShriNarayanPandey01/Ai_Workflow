package com.example.aiworkflow.dataset.api;

import com.example.aiworkflow.dataset.application.DatasetService;
import java.util.UUID;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class InternalDocumentController {

    private final DatasetService datasets;

    public InternalDocumentController(DatasetService datasets) {
        this.datasets = datasets;
    }

    @PostMapping("/internal/v1/documents/{documentId}/download-intent")
    public DatasetDtos.DownloadIntentResponse downloadIntent(@PathVariable UUID documentId) {
        return datasets.downloadIntent(documentId);
    }
}
