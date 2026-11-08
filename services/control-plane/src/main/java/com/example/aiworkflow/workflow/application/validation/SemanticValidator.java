package com.example.aiworkflow.workflow.application.validation;

import com.example.aiworkflow.catalog.NodeCatalogService;
import com.example.aiworkflow.catalog.NodeManifest;
import com.example.aiworkflow.catalog.NodeManifest.PortDefinition;
import com.example.aiworkflow.config.AiwProperties;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class SemanticValidator {

    private static final String LOOP_TYPE = "control.loop@1";
    private static final String FOREACH_TYPE = "control.for-each@1";
    private static final String COLLECT_TYPE = "control.collect@1";
    private static final String INPUT_TYPE = "data.input@1";
    private static final String OUTPUT_TYPE = "data.output@1";
    private static final Set<String> FOREACH_FORBIDDEN = Set.of(
            "human.approval@1",
            "human.review@1",
            "control.for-each@1",
            "control.loop@1",
            "research.deep-research@1",
            "action.cleanup-plan@1",
            "action.cleanup-execute@1");

    private final NodeCatalogService catalog;
    private final ContractSchemaValidator schemas;
    private final AiwProperties properties;

    public SemanticValidator(
            NodeCatalogService catalog, ContractSchemaValidator schemas, AiwProperties properties) {
        this.catalog = catalog;
        this.schemas = schemas;
        this.properties = properties;
    }

    public List<SemanticIssue> validate(JsonNode definition) {
        List<SemanticIssue> errors = new ArrayList<>();
        Graph graph = Graph.parse(definition);
        errors.addAll(uniqueIds(graph));
        errors.addAll(nodeConfigs(graph));
        errors.addAll(edgeRefs(graph));
        errors.addAll(cycles(graph));
        errors.addAll(bindings(graph));
        errors.addAll(foreachBodies(graph));
        errors.addAll(reachability(graph));
        errors.addAll(policyLimits(graph));
        return errors;
    }

    private List<SemanticIssue> uniqueIds(Graph graph) {
        List<SemanticIssue> errors = new ArrayList<>();
        Set<UUID> nodes = new HashSet<>();
        for (Graph.Node node : graph.nodes) {
            if (!nodes.add(node.id)) {
                errors.add(new SemanticIssue("DUPLICATE_NODE_ID", "Duplicate node id", node.id, null, "/nodes"));
            }
        }
        Set<UUID> edges = new HashSet<>();
        for (Graph.Edge edge : graph.edges) {
            if (!edges.add(edge.id)) {
                errors.add(new SemanticIssue("DUPLICATE_EDGE_ID", "Duplicate edge id", null, edge.id, "/edges"));
            }
        }
        return errors;
    }

    private List<SemanticIssue> nodeConfigs(Graph graph) {
        List<SemanticIssue> errors = new ArrayList<>();
        Set<String> baseTypes = new HashSet<>();
        catalog.manifests().keySet().forEach(type -> baseTypes.add(baseType(type)));
        int maxLoop = properties.limits().maxLoopIterations();
        for (Graph.Node node : graph.nodes) {
            NodeManifest manifest = catalog.manifests().get(node.type);
            if (manifest == null) {
                if (baseTypes.contains(baseType(node.type))) {
                    errors.add(new SemanticIssue(
                            "NODE_VERSION_UNSUPPORTED",
                            "Unsupported version for node type " + node.type,
                            node.id,
                            null,
                            nodePath(node)));
                } else {
                    errors.add(new SemanticIssue(
                            "NODE_TYPE_UNKNOWN", "Unknown node type " + node.type, node.id, null, nodePath(node)));
                }
                continue;
            }
            List<String> configErrors = schemas.validateAgainst(manifest.configSchema(), node.config);
            if (!configErrors.isEmpty()) {
                errors.add(new SemanticIssue("NODE_CONFIG_INVALID", configErrors.getFirst(), node.id, null, nodePath(node)));
                if (LOOP_TYPE.equals(node.type) && !node.config.has("max_iterations")) {
                    errors.add(new SemanticIssue(
                            "LOOP_UNBOUNDED", "control.loop@1 requires max_iterations >= 1", node.id, null, nodePath(node)));
                }
                continue;
            }
            if (LOOP_TYPE.equals(node.type)) {
                JsonNode maxIters = node.config.get("max_iterations");
                if (maxIters == null || !maxIters.isInt() || maxIters.asInt() < 1) {
                    errors.add(new SemanticIssue(
                            "LOOP_UNBOUNDED", "control.loop@1 requires max_iterations >= 1", node.id, null, nodePath(node)));
                } else if (maxIters.asInt() > maxLoop) {
                    errors.add(new SemanticIssue(
                            "LOOP_UNBOUNDED",
                            "max_iterations " + maxIters.asInt() + " exceeds platform cap " + maxLoop,
                            node.id,
                            null,
                            nodePath(node)));
                }
            }
        }
        return errors;
    }

    private List<SemanticIssue> edgeRefs(Graph graph) {
        List<SemanticIssue> errors = new ArrayList<>();
        for (Graph.Edge edge : graph.edges) {
            Graph.Node source = graph.node(edge.sourceNodeId);
            Graph.Node target = graph.node(edge.targetNodeId);
            if (source == null) {
                errors.add(new SemanticIssue(
                        "NODE_REF_MISSING",
                        "Edge source node " + edge.sourceNodeId + " does not exist",
                        null,
                        edge.id,
                        "/edges"));
            }
            if (target == null) {
                errors.add(new SemanticIssue(
                        "NODE_REF_MISSING",
                        "Edge target node " + edge.targetNodeId + " does not exist",
                        null,
                        edge.id,
                        "/edges"));
            }
            if (source == null) {
                continue;
            }
            NodeManifest manifest = catalog.manifests().get(source.type);
            if (manifest == null) {
                continue;
            }
            if (manifest.output(edge.sourcePort).isEmpty()) {
                errors.add(new SemanticIssue(
                        "PORT_UNKNOWN",
                        "Source port '" + edge.sourcePort + "' is not declared by node type " + source.type,
                        null,
                        edge.id,
                        "/edges"));
            }
        }
        return errors;
    }

    private List<SemanticIssue> cycles(Graph graph) {
        Map<UUID, List<Adj>> adjacency = new LinkedHashMap<>();
        for (Graph.Node node : graph.nodes) {
            adjacency.put(node.id, new ArrayList<>());
        }
        for (Graph.Edge edge : graph.edges) {
            if (adjacency.containsKey(edge.sourceNodeId) && adjacency.containsKey(edge.targetNodeId)) {
                adjacency.get(edge.sourceNodeId).add(new Adj(edge.targetNodeId, edge.sourcePort, edge.id));
            }
        }
        List<SemanticIssue> errors = new ArrayList<>();
        for (Set<UUID> scc : tarjan(adjacency)) {
            if (scc.size() == 1) {
                UUID nodeId = scc.iterator().next();
                boolean self = adjacency.get(nodeId).stream().anyMatch(adj -> adj.target.equals(nodeId));
                if (!self) {
                    continue;
                }
            }
            List<UUID> loopOwners = scc.stream()
                    .filter(id -> LOOP_TYPE.equals(graph.node(id).type))
                    .toList();
            if (loopOwners.size() != 1) {
                errors.add(new SemanticIssue(
                        "ARBITRARY_CYCLE",
                        "Cycle between nodes without exactly one owning control.loop@1: " + scc.stream().sorted().toList(),
                        null,
                        null,
                        "/edges"));
                continue;
            }
            UUID ownerId = loopOwners.getFirst();
            Set<UUID> permittedBack = new HashSet<>();
            for (UUID sourceId : scc) {
                for (Adj adj : adjacency.get(sourceId)) {
                    if (!adj.target.equals(ownerId)) {
                        continue;
                    }
                    Graph.Edge edge = graph.edge(adj.edgeId);
                    if (sourceId.equals(ownerId)) {
                        continue;
                    }
                    if (!"iteration".equals(edge.targetPort)) {
                        errors.add(new SemanticIssue(
                                "ARBITRARY_CYCLE",
                                "Loop back-edge must target the loop iteration port",
                                ownerId,
                                edge.id,
                                "/edges"));
                    } else {
                        permittedBack.add(edge.id);
                    }
                }
            }
            Map<UUID, List<UUID>> reduced = new HashMap<>();
            for (UUID id : scc) {
                reduced.put(id, new ArrayList<>());
            }
            for (UUID sourceId : scc) {
                for (Adj adj : adjacency.get(sourceId)) {
                    if (!scc.contains(adj.target) || permittedBack.contains(adj.edgeId)) {
                        continue;
                    }
                    reduced.get(sourceId).add(adj.target);
                }
            }
            if (hasCycle(reduced)) {
                errors.add(new SemanticIssue(
                        "ARBITRARY_CYCLE",
                        "Cycle remains after removing loop-back edges in " + scc.stream().sorted().toList(),
                        null,
                        null,
                        "/edges"));
            }
        }
        return errors;
    }

    private List<SemanticIssue> bindings(Graph graph) {
        List<SemanticIssue> errors = new ArrayList<>();
        Map<UUID, Set<UUID>> ancestors = ancestorMap(graph);
        Set<UUID> runtimeCollect = graph.nodes.stream().anyMatch(node -> FOREACH_TYPE.equals(node.type))
                ? graph.nodes.stream()
                        .filter(node -> COLLECT_TYPE.equals(node.type))
                        .map(node -> node.id)
                        .collect(java.util.stream.Collectors.toSet())
                : Set.of();
        for (Graph.Node node : graph.nodes) {
            NodeManifest manifest = catalog.manifests().get(node.type);
            if (manifest == null) {
                continue;
            }
            List<Graph.Edge> incoming = graph.incoming(node.id);
            List<ResolvedBinding> effective = bindingsFor(node, incoming);
            if (node.inputBindings == null) {
                Map<String, Integer> passThrough = new HashMap<>();
                Set<String> multiple = manifest.inputs().stream()
                        .filter(port -> "multiple".equals(port.cardinality()))
                        .map(PortDefinition::name)
                        .collect(java.util.stream.Collectors.toSet());
                for (ResolvedBinding binding : inferPassThrough(node, incoming)) {
                    if ("/".equals(binding.targetPath) || binding.targetPath.isEmpty()) {
                        passThrough.merge(binding.targetPort, 1, Integer::sum);
                    }
                }
                passThrough.forEach((port, count) -> {
                    if (count > 1 && !multiple.contains(port)) {
                        errors.add(new SemanticIssue(
                                "BINDING_AMBIGUOUS",
                                "Multiple incoming edges pass-through to input port '" + port
                                        + "'; explicit input_bindings required",
                                node.id,
                                null,
                                nodePath(node)));
                    }
                });
            }
            Set<String> covered = effective.stream().map(b -> b.targetPort).collect(java.util.stream.Collectors.toSet());
            for (PortDefinition input : manifest.inputs()) {
                if (input.required() && !covered.contains(input.name())) {
                    if (COLLECT_TYPE.equals(node.type)
                            && "items".equals(input.name())
                            && runtimeCollect.contains(node.id)) {
                        continue;
                    }
                    errors.add(new SemanticIssue(
                            "BINDING_MISSING",
                            "Required input port '" + input.name() + "' has no binding",
                            node.id,
                            null,
                            nodePath(node)));
                }
            }
            Map<String, PortDefinition> inputsByName = manifest.inputsByName();
            Map<String, Integer> targetCounts = new HashMap<>();
            for (ResolvedBinding binding : effective) {
                targetCounts.merge(binding.targetPort + "\0" + binding.targetPath, 1, Integer::sum);
            }
            Set<String> reported = new HashSet<>();
            for (ResolvedBinding binding : effective) {
                String key = binding.targetPort + "\0" + binding.targetPath;
                PortDefinition targetPort = inputsByName.get(binding.targetPort);
                boolean allowDuplicate = targetPort != null && "multiple".equals(targetPort.cardinality());
                if (targetCounts.get(key) > 1 && !allowDuplicate && reported.add(key)) {
                    errors.add(new SemanticIssue(
                            "BINDING_INCOMPATIBLE",
                            "Duplicate binding target '" + binding.targetPort + "' at '" + binding.targetPath + "'",
                            node.id,
                            null,
                            nodePath(node)));
                }
                if (!isValidPointer(binding.sourcePath) || !isValidPointer(binding.targetPath)) {
                    errors.add(new SemanticIssue(
                            "BINDING_INCOMPATIBLE", "Invalid JSON Pointer on binding", node.id, null, nodePath(node)));
                }
                Graph.Node source = graph.node(binding.sourceNodeId);
                if (source == null) {
                    errors.add(new SemanticIssue(
                            "BINDING_UNREACHABLE",
                            "Unknown source node " + binding.sourceNodeId,
                            node.id,
                            null,
                            nodePath(node)));
                    continue;
                }
                if (!ancestors.getOrDefault(node.id, Set.of()).contains(binding.sourceNodeId)) {
                    errors.add(new SemanticIssue(
                            "BINDING_UNREACHABLE",
                            "Source node " + binding.sourceNodeId + " is not upstream of " + node.id,
                            node.id,
                            null,
                            nodePath(node)));
                }
                if ("user".equals(binding.origin) && !edgeConnects(binding, node.id, graph.edges)) {
                    errors.add(new SemanticIssue(
                            "BINDING_INCOMPATIBLE",
                            "User binding requires edge from "
                                    + binding.sourceNodeId + "." + binding.sourcePort
                                    + " to " + node.id + "." + binding.targetPort,
                            node.id,
                            null,
                            nodePath(node)));
                }
                NodeManifest sourceManifest = catalog.manifests().get(source.type);
                if (sourceManifest == null || targetPort == null) {
                    continue;
                }
                JsonNode sourceSchema = outputSchema(graph, source, sourceManifest, binding.sourcePort);
                JsonNode targetSchema = inputSchema(graph, node, manifest, binding.targetPort);
                JsonNode sourceSub = schemaAtPointer(sourceSchema, binding.sourcePath);
                JsonNode targetSub = schemaAtPointer(targetSchema, binding.targetPath);
                if (sourceSub == null && !isWhole(binding.sourcePath)) {
                    errors.add(new SemanticIssue(
                            "BINDING_INCOMPATIBLE",
                            "source_path '" + binding.sourcePath + "' does not resolve in output port '"
                                    + binding.sourcePort + "' schema",
                            node.id,
                            null,
                            nodePath(node)));
                    continue;
                }
                if (targetSub == null && !isWhole(binding.targetPath)) {
                    errors.add(new SemanticIssue(
                            "BINDING_INCOMPATIBLE",
                            "target_path '" + binding.targetPath + "' does not resolve in input port '"
                                    + binding.targetPort + "' schema",
                            node.id,
                            null,
                            nodePath(node)));
                    continue;
                }
                if (sourceSub != null && targetSub != null && !schemasCompatible(sourceSub, targetSub)) {
                    errors.add(new SemanticIssue(
                            "BINDING_INCOMPATIBLE",
                            "source '" + binding.sourcePath + "' is not compatible with target '"
                                    + binding.targetPath + "'",
                            node.id,
                            null,
                            nodePath(node)));
                }
            }
        }
        return errors;
    }

    private List<SemanticIssue> foreachBodies(Graph graph) {
        List<SemanticIssue> errors = new ArrayList<>();
        Set<UUID> collectIds = graph.nodes.stream()
                .filter(node -> COLLECT_TYPE.equals(node.type))
                .map(node -> node.id)
                .collect(java.util.stream.Collectors.toSet());
        Map<UUID, Map<String, List<Graph.Edge>>> outgoing = new HashMap<>();
        for (Graph.Edge edge : graph.edges) {
            outgoing.computeIfAbsent(edge.sourceNodeId, ignored -> new HashMap<>())
                    .computeIfAbsent(edge.sourcePort, ignored -> new ArrayList<>())
                    .add(edge);
        }
        for (Graph.Node node : graph.nodes) {
            if (!FOREACH_TYPE.equals(node.type)) {
                continue;
            }
            Set<UUID> body = new HashSet<>();
            Deque<UUID> queue = new ArrayDeque<>();
            for (Graph.Edge edge : outgoing.getOrDefault(node.id, Map.of()).getOrDefault("item", List.of())) {
                queue.add(edge.targetNodeId);
            }
            while (!queue.isEmpty()) {
                UUID current = queue.removeFirst();
                if (body.contains(current) || current.equals(node.id) || collectIds.contains(current)) {
                    continue;
                }
                body.add(current);
                for (Graph.Edge edge : graph.edges) {
                    if (!edge.sourceNodeId.equals(current)) {
                        continue;
                    }
                    if (!body.contains(edge.targetNodeId) && !collectIds.contains(edge.targetNodeId)) {
                        queue.add(edge.targetNodeId);
                    }
                }
            }
            for (UUID bodyId : body) {
                Graph.Node bodyNode = graph.node(bodyId);
                if (bodyNode != null && FOREACH_FORBIDDEN.contains(bodyNode.type)) {
                    errors.add(new SemanticIssue(
                            "FOREACH_BODY_FORBIDDEN",
                            "Node type " + bodyNode.type + " is not allowed inside control.for-each@1 bodies",
                            bodyId,
                            null,
                            "/nodes"));
                }
            }
        }
        return errors;
    }

    private List<SemanticIssue> reachability(Graph graph) {
        List<SemanticIssue> errors = new ArrayList<>();
        List<Graph.Node> starts = graph.nodes.stream().filter(node -> INPUT_TYPE.equals(node.type)).toList();
        if (starts.size() != 1) {
            errors.add(new SemanticIssue(
                    "START_NODE_INVALID",
                    "Workflow must have exactly one data.input@1 node",
                    null,
                    null,
                    "/nodes"));
            return errors;
        }
        UUID start = starts.getFirst().id;
        Set<UUID> reachable = new HashSet<>();
        Deque<UUID> queue = new ArrayDeque<>();
        queue.add(start);
        while (!queue.isEmpty()) {
            UUID current = queue.removeFirst();
            if (!reachable.add(current)) {
                continue;
            }
            for (Graph.Edge edge : graph.edges) {
                if (edge.sourceNodeId.equals(current)) {
                    queue.add(edge.targetNodeId);
                }
            }
        }
        for (Graph.Node node : graph.nodes) {
            if (!reachable.contains(node.id)) {
                errors.add(new SemanticIssue(
                        "NODE_UNREACHABLE", "Node is not reachable from start", node.id, null, nodePath(node)));
            }
        }
        boolean outputReachable = graph.nodes.stream()
                .anyMatch(node -> OUTPUT_TYPE.equals(node.type) && reachable.contains(node.id));
        if (!outputReachable) {
            errors.add(new SemanticIssue(
                    "OUTPUT_UNREACHABLE", "No reachable data.output@1 node", null, null, "/nodes"));
        }
        return errors;
    }

    private List<SemanticIssue> policyLimits(Graph graph) {
        List<SemanticIssue> errors = new ArrayList<>();
        int maxNodes = properties.limits().maxGraphNodes();
        if (graph.nodes.size() > maxNodes) {
            errors.add(new SemanticIssue(
                    "POLICY_LIMIT", "Graph exceeds AIW_MAX_GRAPH_NODES", null, null, "/nodes"));
        }
        JsonNode policy = graph.raw.path("execution_policy");
        int capFanOut = properties.limits().maxFanOutItems();
        int policyFanOut = policy.path("max_fan_out_items").asInt(capFanOut);
        int effectiveFanOut = Math.min(policyFanOut, capFanOut);
        for (Graph.Node node : graph.nodes) {
            if (FOREACH_TYPE.equals(node.type) && node.config.path("max_items").asInt(0) > effectiveFanOut) {
                errors.add(new SemanticIssue(
                        "POLICY_LIMIT",
                        "for-each max_items exceeds effective fan-out cap",
                        node.id,
                        null,
                        nodePath(node)));
            }
        }
        int maxRun = properties.limits().maxRunSeconds();
        if (policy.path("timeout_seconds").asInt(0) > maxRun) {
            errors.add(new SemanticIssue(
                    "POLICY_LIMIT", "execution_policy.timeout_seconds exceeds AIW_MAX_RUN_SECONDS", null, null, "/execution_policy"));
        }
        return errors;
    }

    private static List<ResolvedBinding> bindingsFor(Graph.Node node, List<Graph.Edge> incoming) {
        if (node.inputBindings != null) {
            return node.inputBindings;
        }
        return inferPassThrough(node, incoming);
    }

    private static List<ResolvedBinding> inferPassThrough(Graph.Node node, List<Graph.Edge> incoming) {
        List<ResolvedBinding> bindings = new ArrayList<>();
        for (Graph.Edge edge : incoming) {
            if (!edge.targetNodeId.equals(node.id)) {
                continue;
            }
            bindings.add(new ResolvedBinding(
                    edge.targetPort, "/", edge.sourceNodeId, edge.sourcePort, "/", "pass_through"));
        }
        return bindings;
    }

    private static boolean edgeConnects(ResolvedBinding binding, UUID targetNodeId, List<Graph.Edge> edges) {
        for (Graph.Edge edge : edges) {
            if (edge.sourceNodeId.equals(binding.sourceNodeId)
                    && edge.targetNodeId.equals(targetNodeId)
                    && edge.sourcePort.equals(binding.sourcePort)
                    && edge.targetPort.equals(binding.targetPort)) {
                return true;
            }
        }
        return false;
    }

    private static Map<UUID, Set<UUID>> ancestorMap(Graph graph) {
        Map<UUID, List<UUID>> reverse = new HashMap<>();
        for (Graph.Node node : graph.nodes) {
            reverse.put(node.id, new ArrayList<>());
        }
        for (Graph.Edge edge : graph.edges) {
            if (reverse.containsKey(edge.targetNodeId)) {
                reverse.get(edge.targetNodeId).add(edge.sourceNodeId);
            }
        }
        Map<UUID, Set<UUID>> ancestors = new HashMap<>();
        for (Graph.Node node : graph.nodes) {
            Set<UUID> found = new HashSet<>();
            Deque<UUID> stack = new ArrayDeque<>(reverse.get(node.id));
            while (!stack.isEmpty()) {
                UUID current = stack.pop();
                if (!found.add(current)) {
                    continue;
                }
                stack.addAll(reverse.getOrDefault(current, List.of()));
            }
            ancestors.put(node.id, found);
        }
        return ancestors;
    }

    private static JsonNode outputSchema(Graph graph, Graph.Node node, NodeManifest manifest, String port) {
        return manifest.output(port)
                .map(def -> INPUT_TYPE.equals(node.type) && "value".equals(port) ? graph.raw.get("input_schema") : def.schema())
                .orElse(null);
    }

    private static JsonNode inputSchema(Graph graph, Graph.Node node, NodeManifest manifest, String port) {
        return manifest.input(port)
                .map(def -> OUTPUT_TYPE.equals(node.type) && "value".equals(port) ? graph.raw.get("output_schema") : def.schema())
                .orElse(null);
    }

    static JsonNode schemaAtPointer(JsonNode schema, String pointer) {
        if (schema == null || isWhole(pointer)) {
            return schema;
        }
        if (!pointer.startsWith("/")) {
            return null;
        }
        JsonNode current = schema;
        for (String token : pointer.substring(1).split("/")) {
            if (current == null || !current.isObject()) {
                return null;
            }
            if (token.chars().allMatch(Character::isDigit)) {
                current = current.get("items");
                continue;
            }
            JsonNode properties = current.get("properties");
            if (properties == null || !properties.has(token)) {
                return null;
            }
            current = properties.get(token);
        }
        return current;
    }

    static boolean schemasCompatible(JsonNode source, JsonNode target) {
        Set<String> sourceTypes = schemaTypes(source);
        Set<String> targetTypes = schemaTypes(target);
        if (sourceTypes == null || targetTypes == null) {
            return true;
        }
        boolean compatible;
        if (sourceTypes.equals(targetTypes)) {
            compatible = true;
        } else if (sourceTypes.stream().allMatch(t -> t.equals("integer") || t.equals("number"))
                && targetTypes.stream().allMatch(t -> t.equals("integer") || t.equals("number"))) {
            compatible = targetTypes.contains("number") || sourceTypes.equals(Set.of("integer"));
        } else {
            compatible = false;
        }
        if (!compatible) {
            return false;
        }
        Set<String> targetEnum = enumValues(target);
        if (targetEnum == null) {
            return true;
        }
        Set<String> sourceEnum = enumValues(source);
        if (sourceEnum == null) {
            return true;
        }
        return targetEnum.containsAll(sourceEnum);
    }

    private static Set<String> schemaTypes(JsonNode schema) {
        JsonNode type = schema.get("type");
        if (type == null) {
            return null;
        }
        if (type.isTextual()) {
            return Set.of(type.asText());
        }
        if (type.isArray()) {
            Set<String> types = new HashSet<>();
            type.forEach(item -> types.add(item.asText()));
            return types;
        }
        return null;
    }

    private static Set<String> enumValues(JsonNode schema) {
        if (schema.has("enum") && schema.get("enum").isArray()) {
            Set<String> values = new HashSet<>();
            schema.get("enum").forEach(item -> values.add(item.toString()));
            return values;
        }
        if (schema.has("const")) {
            return Set.of(schema.get("const").toString());
        }
        return null;
    }

    static boolean isValidPointer(String path) {
        if (isWhole(path)) {
            return true;
        }
        if (!path.startsWith("/")) {
            return false;
        }
        for (String token : path.substring(1).split("/", -1)) {
            if (token.isEmpty()) {
                return false;
            }
            int idx = 0;
            while (idx < token.length()) {
                int tilde = token.indexOf('~', idx);
                if (tilde < 0) {
                    break;
                }
                if (tilde == token.length() - 1 || (token.charAt(tilde + 1) != '0' && token.charAt(tilde + 1) != '1')) {
                    return false;
                }
                idx = tilde + 2;
            }
        }
        return true;
    }

    private static boolean isWhole(String path) {
        return path == null || path.isEmpty() || "/".equals(path);
    }

    private static String nodePath(Graph.Node node) {
        return "/nodes/" + node.id;
    }

    private static String baseType(String type) {
        int at = type.lastIndexOf('@');
        return at < 0 ? type : type.substring(0, at);
    }

    private static List<Set<UUID>> tarjan(Map<UUID, List<Adj>> adjacency) {
        List<Set<UUID>> result = new ArrayList<>();
        Map<UUID, Integer> indices = new HashMap<>();
        Map<UUID, Integer> lowlink = new HashMap<>();
        Deque<UUID> stack = new ArrayDeque<>();
        Set<UUID> onStack = new HashSet<>();
        int[] index = {0};
        for (UUID node : adjacency.keySet()) {
            if (!indices.containsKey(node)) {
                strongconnect(node, adjacency, indices, lowlink, stack, onStack, index, result);
            }
        }
        return result;
    }

    private static void strongconnect(
            UUID node,
            Map<UUID, List<Adj>> adjacency,
            Map<UUID, Integer> indices,
            Map<UUID, Integer> lowlink,
            Deque<UUID> stack,
            Set<UUID> onStack,
            int[] index,
            List<Set<UUID>> result) {
        indices.put(node, index[0]);
        lowlink.put(node, index[0]);
        index[0]++;
        stack.push(node);
        onStack.add(node);
        for (Adj adj : adjacency.getOrDefault(node, List.of())) {
            if (!indices.containsKey(adj.target)) {
                strongconnect(adj.target, adjacency, indices, lowlink, stack, onStack, index, result);
                lowlink.put(node, Math.min(lowlink.get(node), lowlink.get(adj.target)));
            } else if (onStack.contains(adj.target)) {
                lowlink.put(node, Math.min(lowlink.get(node), indices.get(adj.target)));
            }
        }
        if (lowlink.get(node).equals(indices.get(node))) {
            Set<UUID> component = new HashSet<>();
            while (true) {
                UUID member = stack.pop();
                onStack.remove(member);
                component.add(member);
                if (member.equals(node)) {
                    break;
                }
            }
            result.add(component);
        }
    }

    private static boolean hasCycle(Map<UUID, List<UUID>> adjacency) {
        Map<UUID, Integer> color = new HashMap<>();
        adjacency.keySet().forEach(id -> color.put(id, 0));
        for (UUID node : adjacency.keySet()) {
            if (color.get(node) == 0 && dfsCycle(node, adjacency, color)) {
                return true;
            }
        }
        return false;
    }

    private static boolean dfsCycle(UUID node, Map<UUID, List<UUID>> adjacency, Map<UUID, Integer> color) {
        color.put(node, 1);
        for (UUID neighbor : adjacency.getOrDefault(node, List.of())) {
            if (color.get(neighbor) == 1) {
                return true;
            }
            if (color.get(neighbor) == 0 && dfsCycle(neighbor, adjacency, color)) {
                return true;
            }
        }
        color.put(node, 2);
        return false;
    }

    private record Adj(UUID target, String sourcePort, UUID edgeId) {}

    record ResolvedBinding(
            String targetPort, String targetPath, UUID sourceNodeId, String sourcePort, String sourcePath, String origin) {}

    static final class Graph {
        final JsonNode raw;
        final List<Node> nodes;
        final List<Edge> edges;
        private final Map<UUID, Node> nodeById;
        private final Map<UUID, Edge> edgeById;

        private Graph(JsonNode raw, List<Node> nodes, List<Edge> edges) {
            this.raw = raw;
            this.nodes = nodes;
            this.edges = edges;
            this.nodeById = new HashMap<>();
            nodes.forEach(node -> nodeById.put(node.id, node));
            this.edgeById = new HashMap<>();
            edges.forEach(edge -> edgeById.put(edge.id, edge));
        }

        static Graph parse(JsonNode raw) {
            List<Node> nodes = new ArrayList<>();
            for (JsonNode node : raw.path("nodes")) {
                List<ResolvedBinding> bindings = null;
                if (node.has("input_bindings") && !node.get("input_bindings").isNull()) {
                    bindings = new ArrayList<>();
                    for (JsonNode binding : node.get("input_bindings")) {
                        bindings.add(new ResolvedBinding(
                                binding.path("target_port").asText(),
                                binding.path("target_path").asText(),
                                UUID.fromString(binding.path("source_node_id").asText()),
                                binding.path("source_port").asText(),
                                binding.path("source_path").asText(),
                                binding.path("origin").asText()));
                    }
                }
                nodes.add(new Node(
                        UUID.fromString(node.path("id").asText()),
                        node.path("type").asText(),
                        node.path("config"),
                        bindings));
            }
            List<Edge> edges = new ArrayList<>();
            for (JsonNode edge : raw.path("edges")) {
                edges.add(new Edge(
                        UUID.fromString(edge.path("id").asText()),
                        UUID.fromString(edge.path("source_node_id").asText()),
                        edge.path("source_port").asText(),
                        UUID.fromString(edge.path("target_node_id").asText()),
                        edge.path("target_port").asText()));
            }
            return new Graph(raw, nodes, edges);
        }

        Node node(UUID id) {
            return nodeById.get(id);
        }

        Edge edge(UUID id) {
            return edgeById.get(id);
        }

        List<Edge> incoming(UUID nodeId) {
            return edges.stream().filter(edge -> edge.targetNodeId.equals(nodeId)).toList();
        }

        record Node(UUID id, String type, JsonNode config, List<ResolvedBinding> inputBindings) {}

        record Edge(UUID id, UUID sourceNodeId, String sourcePort, UUID targetNodeId, String targetPort) {}
    }
}
