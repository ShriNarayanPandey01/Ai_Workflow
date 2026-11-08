package com.example.aiworkflow.catalog;

import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class JsonSchemaFactoryConfig {

    @Bean
    JsonSchemaFactory jsonSchemaFactory(ContractsPaths paths) {
        return create(paths);
    }

    public static JsonSchemaFactory create(ContractsPaths paths) {
        String filePrefix = paths.root().toAbsolutePath().toUri().toString();
        if (!filePrefix.endsWith("/")) {
            filePrefix = filePrefix + "/";
        }
        String mappedPrefix = filePrefix;
        return JsonSchemaFactory.getInstance(
                SpecVersion.VersionFlag.V202012,
                builder -> builder.schemaMappers(mappers -> mappers
                        .mapPrefix("https://ai-workflow.local/contracts/", mappedPrefix)
                        .mapPrefix("../../workflow/", mappedPrefix + "workflow/")
                        .mapPrefix("commands/", mappedPrefix + "messages/commands/")
                        .mapPrefix("events/", mappedPrefix + "messages/events/")));
    }
}
