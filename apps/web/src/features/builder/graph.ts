import type { InputBinding, JsonValue, NodeManifest, PortDefinition, WorkflowDefinition, WorkflowEdge, WorkflowNode } from "@/api/types"

export const cloneDefinition = (definition: WorkflowDefinition): WorkflowDefinition => {
  return structuredClone(definition)
}

export const findManifest = (catalog: NodeManifest[], type: string) => {
  return catalog.find((item) => item.type === type)
}

export const portSchemaType = (port?: PortDefinition) => {
  const schema = port?.schema
  if (!schema) {
    return "any"
  }
  const type = schema.type
  return typeof type === "string" ? type : "object"
}

export const portsCompatible = (source?: PortDefinition, target?: PortDefinition) => {
  if (!source || !target) {
    return false
  }
  if (source.direction !== "output" || target.direction !== "input") {
    return false
  }
  const sourceType = portSchemaType(source)
  const targetType = portSchemaType(target)
  if (sourceType === "any" || targetType === "any") {
    return true
  }
  if (sourceType === targetType) {
    return true
  }
  return sourceType === "object"
}

export const defaultBindingsForEdge = (
  catalog: NodeManifest[],
  source: WorkflowNode,
  target: WorkflowNode,
  sourcePort: string,
  targetPort: string,
): InputBinding[] => {
  const targetManifest = findManifest(catalog, target.type)
  const input = targetManifest?.inputs.find((port) => port.name === targetPort)
  if (!input) {
    return []
  }
  const match = input.default_bindings?.find((binding) => binding.match.source_ports.includes(sourcePort))
  if (match) {
    const sourcePath = match.match.source_paths[0] ?? "/"
    return [
      {
        target_port: targetPort,
        target_path: match.target_path,
        source_node_id: source.id,
        source_port: sourcePort,
        source_path: sourcePath,
        origin: "default",
      },
    ]
  }
  return [
    {
      target_port: targetPort,
      target_path: "/",
      source_node_id: source.id,
      source_port: sourcePort,
      source_path: "/",
      origin: "pass_through",
    },
  ]
}

export const applyEdgeBindings = (
  definition: WorkflowDefinition,
  catalog: NodeManifest[],
  edge: WorkflowEdge,
): WorkflowDefinition => {
  const next = cloneDefinition(definition)
  const source = next.nodes.find((node) => node.id === edge.source_node_id)
  const target = next.nodes.find((node) => node.id === edge.target_node_id)
  if (!source || !target) {
    return next
  }
  const created = defaultBindingsForEdge(catalog, source, target, edge.source_port, edge.target_port)
  const existing = target.input_bindings ?? []
  const merged = [
    ...existing.filter(
      (binding) =>
        !(binding.target_port === edge.target_port && binding.source_node_id === edge.source_node_id),
    ),
    ...created,
  ]
  target.input_bindings = merged
  return next
}

export const newNode = (
  type: string,
  position: { x: number; y: number },
  manifest?: NodeManifest,
): WorkflowNode => {
  const properties = manifest?.config_schema.properties
  const config: Record<string, JsonValue> = {}
  if (properties && typeof properties === "object" && !Array.isArray(properties)) {
    for (const [key, field] of Object.entries(properties)) {
      if (field && typeof field === "object" && !Array.isArray(field) && "default" in field) {
        const defaultValue = field.default
        if (defaultValue !== undefined) config[key] = defaultValue
      }
    }
  }
  return {
    id: crypto.randomUUID(),
    type,
    position,
    config,
    credential_refs: {},
    resource_refs: {},
    input_bindings: [],
  }
}
