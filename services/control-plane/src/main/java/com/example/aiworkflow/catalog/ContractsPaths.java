package com.example.aiworkflow.catalog;

import com.example.aiworkflow.config.AiwProperties;
import java.nio.file.Files;
import java.nio.file.Path;
import org.springframework.stereotype.Component;

@Component
public class ContractsPaths {

    private final Path root;

    public ContractsPaths(AiwProperties properties) {
        Path configured = Path.of(properties.contracts().root());
        if (!configured.isAbsolute()) {
            configured = Path.of(System.getProperty("user.dir")).resolve(configured).normalize();
        }
        this.root = configured;
    }

    public Path root() {
        return root;
    }

    public Path catalogDir() {
        return root.resolve("nodes").resolve("catalog");
    }

    public Path manifestSchema() {
        return root.resolve("nodes").resolve("manifest.schema.json");
    }

    public Path definitionSchema() {
        return root.resolve("workflow").resolve("definition.schema.json");
    }

    public Path conditionSchema() {
        return root.resolve("workflow").resolve("condition.schema.json");
    }

    public Path envelopeSchema() {
        return root.resolve("messages").resolve("envelope.schema.json");
    }

    public void requirePresent() {
        if (!Files.isDirectory(catalogDir())) {
            throw new IllegalStateException("Contracts catalog not found at " + catalogDir());
        }
    }
}
