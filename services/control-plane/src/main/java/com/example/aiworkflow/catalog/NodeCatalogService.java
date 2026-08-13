package com.example.aiworkflow.catalog;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaLocation;
import com.networknt.schema.ValidationMessage;
import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;
import org.springframework.stereotype.Service;

@Service
public class NodeCatalogService {

    private final ContractsPaths paths;
    private final ObjectMapper objectMapper;
    private final JsonSchemaFactory schemaFactory;
    private final Map<String, NodeManifest> manifests = new LinkedHashMap<>();
    private JsonSchema manifestSchema;

    public NodeCatalogService(ContractsPaths paths, ObjectMapper objectMapper, JsonSchemaFactory schemaFactory) {
        this.paths = paths;
        this.objectMapper = objectMapper;
        this.schemaFactory = schemaFactory;
    }

    @PostConstruct
    public void load() throws IOException {
        paths.requirePresent();
        manifestSchema = schemaFactory.getSchema(SchemaLocation.of(paths.manifestSchema().toUri().toString()));
        try (Stream<Path> files = Files.list(paths.catalogDir())) {
            List<Path> jsonFiles = files.filter(path -> path.getFileName().toString().endsWith(".json"))
                    .sorted()
                    .toList();
            for (Path file : jsonFiles) {
                JsonNode raw = objectMapper.readTree(file.toFile());
                Set<ValidationMessage> errors = manifestSchema.validate(raw);
                if (!errors.isEmpty()) {
                    throw new IllegalStateException("Invalid catalog manifest " + file.getFileName() + ": " + errors.iterator().next().getMessage());
                }
                NodeManifest manifest = NodeManifest.from(raw);
                if (manifests.containsKey(manifest.type())) {
                    throw new IllegalStateException("Duplicate catalog type " + manifest.type());
                }
                manifests.put(manifest.type(), manifest);
            }
        }
    }

    public List<JsonNode> allRaw() {
        List<JsonNode> items = new ArrayList<>();
        manifests.values().forEach(manifest -> items.add(manifest.raw()));
        return items;
    }

    public Map<String, NodeManifest> manifests() {
        return manifests;
    }

    public JsonSchema manifestSchema() {
        return manifestSchema;
    }
}
