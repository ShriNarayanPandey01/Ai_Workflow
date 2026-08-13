package com.example.aiworkflow.catalog.api;

import com.example.aiworkflow.catalog.NodeCatalogService;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/node-catalog")
public class NodeCatalogController {

    private final NodeCatalogService catalog;

    public NodeCatalogController(NodeCatalogService catalog) {
        this.catalog = catalog;
    }

    @GetMapping
    public Map<String, List<JsonNode>> list() {
        return Map.of("items", catalog.allRaw());
    }
}
