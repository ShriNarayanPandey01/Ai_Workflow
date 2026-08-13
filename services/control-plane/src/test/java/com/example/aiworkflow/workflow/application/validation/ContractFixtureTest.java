package com.example.aiworkflow.workflow.application.validation;

import static org.assertj.core.api.Assertions.assertThat;

import com.example.aiworkflow.catalog.ContractsPaths;
import com.example.aiworkflow.catalog.JsonSchemaFactoryConfig;
import com.example.aiworkflow.catalog.NodeCatalogService;
import com.example.aiworkflow.config.AiwProperties;
import com.example.aiworkflow.workflow.application.WorkflowValidationService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchemaFactory;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

class ContractFixtureTest {

    private static Path contractsRoot;
    private static ObjectMapper mapper;
    private static WorkflowValidationService validation;
    private static NodeCatalogService catalog;
    private static ContractSchemaValidator schemas;

    @BeforeAll
    static void setup() throws Exception {
        contractsRoot = Path.of(System.getProperty("user.dir")).resolve("../../contracts").normalize();
        if (!Files.isDirectory(contractsRoot.resolve("nodes").resolve("catalog"))) {
            contractsRoot = Path.of("contracts").toAbsolutePath().normalize();
        }
        mapper = new ObjectMapper();
        AiwProperties properties = new AiwProperties(
                new AiwProperties.Jwt("development-only-jwt-secret-must-be-at-least-32-bytes", Duration.ofMinutes(10)),
                new AiwProperties.Refresh(
                        "development-only-refresh-hash-secret",
                        Duration.ofDays(30),
                        "aiw_refresh",
                        false,
                        "/api/v1/auth"),
                new AiwProperties.Contracts(contractsRoot.toString()),
                new AiwProperties.Limits(500, 100, 86400, 10000),
                new AiwProperties.Auth(20),
                new AiwProperties.Credentials("development-only-credential-kek-must-be-32b", "v1"),
                new AiwProperties.ServiceJwt(
                        "development-only-jwt-secret-must-be-at-least-32-bytes",
                        Duration.ofMinutes(5),
                        "control-plane"),
                new AiwProperties.Messaging(true, Duration.ofSeconds(2), 20),
                new AiwProperties.Storage(
                        false,
                        "http://localhost:9000",
                        "aiw",
                        "aiw",
                        "aiwsecret",
                        "us-east-1",
                        true,
                        Duration.ofMinutes(15)));
        ContractsPaths paths = new ContractsPaths(properties);
        JsonSchemaFactory factory = JsonSchemaFactoryConfig.create(paths);
        catalog = new NodeCatalogService(paths, mapper, factory);
        catalog.load();
        schemas = new ContractSchemaValidator(paths, mapper, factory);
        schemas.init();
        SemanticValidator semantic = new SemanticValidator(catalog, schemas, properties);
        validation = new WorkflowValidationService(schemas, semantic);
    }

    @ParameterizedTest
    @ValueSource(
            strings = {
                "workflow-linear.json",
                "workflow-conditional.json",
                "workflow-fan-out-fan-in.json",
                "workflow-bounded-loop.json",
                "workflow-field-bindings.json",
                "workflow-compose-demo.json"
            })
    void validWorkflowFixturesPass(String file) throws Exception {
        JsonNode node = mapper.readTree(contractsRoot.resolve("fixtures/valid").resolve(file).toFile());
        assertThat(validation.validate(node)).isEmpty();
    }

    @Test
    void catalogManifestsMatchSchema() throws Exception {
        Path catalogDir = contractsRoot.resolve("nodes/catalog");
        try (var files = Files.list(catalogDir)) {
            for (Path file : files.filter(path -> path.toString().endsWith(".json")).toList()) {
                JsonNode raw = mapper.readTree(file.toFile());
                assertThat(catalog.manifestSchema().validate(raw)).isEmpty();
            }
        }
    }

    @ParameterizedTest
    @CsvSource({
        "workflow-arbitrary-cycle.json,ARBITRARY_CYCLE",
        "workflow-unbounded-loop.json,LOOP_UNBOUNDED",
        "workflow-missing-node-ref.json,NODE_REF_MISSING",
        "workflow-invalid-port.json,PORT_UNKNOWN",
        "workflow-unsupported-node-version.json,NODE_VERSION_UNSUPPORTED",
        "workflow-unknown-top-level.json,SCHEMA_ADDITIONAL_PROPERTY",
        "workflow-binding-missing.json,BINDING_MISSING",
        "workflow-binding-unreachable.json,BINDING_UNREACHABLE",
        "workflow-binding-incompatible.json,BINDING_INCOMPATIBLE",
        "workflow-binding-ambiguous.json,BINDING_AMBIGUOUS"
    })
    void invalidWorkflowFixturesEmitExpectedCodes(String file, String expected) throws Exception {
        JsonNode node = mapper.readTree(contractsRoot.resolve("fixtures/invalid").resolve(file).toFile());
        Set<String> codes = validation.validate(node).stream().map(err -> err.code()).collect(Collectors.toSet());
        assertThat(codes).contains(expected);
    }

    @Test
    void invalidConditionFixtureFailsSchema() throws Exception {
        JsonNode node = mapper.readTree(
                contractsRoot.resolve("fixtures/invalid/workflow-invalid-condition-op.json").toFile());
        assertThat(schemas.validateCondition(node)).isNotEmpty();
    }
}
