package com.example.aiworkflow.storage;

import java.util.UUID;

public final class ObjectKeys {

    private ObjectKeys() {}

    public static String document(
            UUID workspaceId, UUID projectId, UUID datasetId, UUID documentId, int version) {
        return workspaceId + "/" + projectId + "/datasets/" + datasetId + "/" + documentId + "/v" + version;
    }

    public static String artifact(UUID workspaceId, UUID projectId, UUID artifactId) {
        return workspaceId + "/" + projectId + "/artifacts/" + artifactId;
    }
}
