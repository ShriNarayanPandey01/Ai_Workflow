package com.example.aiworkflow.storage;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.UUID;
import org.junit.jupiter.api.Test;

class ObjectKeysTest {

    @Test
    void documentKey_isServerGeneratedPath() {
        UUID workspace = UUID.fromString("11111111-1111-4111-8111-111111111111");
        UUID project = UUID.fromString("22222222-2222-4222-8222-222222222222");
        UUID dataset = UUID.fromString("33333333-3333-4333-8333-333333333333");
        UUID document = UUID.fromString("44444444-4444-4444-8444-444444444444");
        assertThat(ObjectKeys.document(workspace, project, dataset, document, 2))
                .isEqualTo(workspace + "/" + project + "/datasets/" + dataset + "/" + document + "/v2");
    }

    @Test
    void artifactKey_usesJoinContract() {
        UUID workspace = UUID.fromString("11111111-1111-4111-8111-111111111111");
        UUID project = UUID.fromString("22222222-2222-4222-8222-222222222222");
        UUID artifact = UUID.fromString("55555555-5555-4555-8555-555555555555");
        assertThat(ObjectKeys.artifact(workspace, project, artifact))
                .isEqualTo(workspace + "/" + project + "/artifacts/" + artifact);
    }
}
