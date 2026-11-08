import type {
  InputBinding,
  JsonValue,
  NodeManifest,
  PortDefinition,
  WorkflowDefinition,
  WorkflowNode,
} from "@/api/types"

export type JsonSchema = Record<string, JsonValue>

export type SchemaField = {
  path: string
  type: string
  required: boolean
  schema: JsonSchema
}

export type TargetBindingOption = SchemaField & {
  id: string
  port: string
  label: string
}

export type SourceBindingOption = SchemaField & {
  id: string
  sourceNodeId: string
  sourceNodeLabel: string
  sourcePort: string
  targetPort: string
  label: string
}

export type BindingOptions = {
  targets: TargetBindingOption[]
  sources: SourceBindingOption[]
}

const asSchema = (value: JsonValue | undefined): JsonSchema | undefined => {
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    return undefined
  }
  return value
}

const schemaTypes = (schema: JsonSchema): Set<string> | undefined => {
  if (typeof schema.type === "string") {
    return new Set([schema.type])
  }
  if (Array.isArray(schema.type)) {
    const types = schema.type.filter((item): item is string => typeof item === "string")
    return types.length > 0 ? new Set(types) : undefined
  }
  return undefined
}

const schemaTypeLabel = (schema: JsonSchema) => {
  const types = schemaTypes(schema)
  if (types) {
    return [...types].join(" | ")
  }
  return asSchema(schema.properties) ? "object" : "any"
}

const requiredProperties = (schema: JsonSchema) => {
  if (!Array.isArray(schema.required)) {
    return new Set<string>()
  }
  return new Set(schema.required.filter((item): item is string => typeof item === "string"))
}

const escapePointerToken = (token: string) => token.replaceAll("~", "~0").replaceAll("/", "~1")

const decodePointerToken = (token: string) => token.replaceAll("~1", "/").replaceAll("~0", "~")

/** Return the whole port plus statically addressable object properties. */
export const enumerateSchemaFields = (schema: JsonSchema): SchemaField[] => {
  const fields: SchemaField[] = [{ path: "/", type: schemaTypeLabel(schema), required: false, schema }]

  const visit = (current: JsonSchema, parentPath: string) => {
    const properties = asSchema(current.properties)
    if (!properties) {
      return
    }
    const required = requiredProperties(current)

    Object.entries(properties).forEach(([name, value]) => {
      const child = asSchema(value)
      if (!child) {
        return
      }
      const path = `${parentPath}/${escapePointerToken(name)}`
      fields.push({ path, type: schemaTypeLabel(child), required: required.has(name), schema: child })
      visit(child, path)
    })
  }

  visit(schema, "")
  return fields
}

export const pointerSuffix = (path: string) => {
  if (path === "" || path === "/") {
    return ""
  }
  return path
    .slice(1)
    .split("/")
    .map(decodePointerToken)
    .map((token) => (/^\d+$/.test(token) ? `[${token}]` : `.${token}`))
    .join("")
}

export const inputReference = (port: string, path: string) => `input.${port}${pointerSuffix(path)}`

export const sourceReference = (nodeLabel: string, port: string, path: string) =>
  `${nodeLabel}.output.${port}${pointerSuffix(path)}`

const effectiveInputSchema = (
  definition: WorkflowDefinition,
  node: WorkflowNode,
  port: PortDefinition,
) => (node.type === "data.output@1" && port.name === "value" ? definition.output_schema : port.schema)

const effectiveOutputSchema = (
  definition: WorkflowDefinition,
  node: WorkflowNode,
  port: PortDefinition,
) => (node.type === "data.input@1" && port.name === "value" ? definition.input_schema : port.schema)

const nodeLabel = (node: WorkflowNode, manifest: NodeManifest) => manifest.display_name || node.type

export const buildBindingOptions = (
  definition: WorkflowDefinition,
  catalog: NodeManifest[],
  targetNodeId: string,
): BindingOptions => {
  const targetNode = definition.nodes.find((node) => node.id === targetNodeId)
  const targetManifest = targetNode ? catalog.find((item) => item.type === targetNode.type) : undefined
  if (!targetNode || !targetManifest) {
    return { targets: [], sources: [] }
  }

  const targets = targetManifest.inputs.flatMap((port) =>
    enumerateSchemaFields(effectiveInputSchema(definition, targetNode, port)).map((field) => ({
      ...field,
      id: JSON.stringify([port.name, field.path]),
      port: port.name,
      required: field.path === "/" ? port.required : field.required,
      label: inputReference(port.name, field.path),
    })),
  )

  const sources: SourceBindingOption[] = []
  definition.edges
    .filter((edge) => edge.target_node_id === targetNodeId)
    .forEach((edge) => {
      const sourceNode = definition.nodes.find((node) => node.id === edge.source_node_id)
      const sourceManifest = sourceNode ? catalog.find((item) => item.type === sourceNode.type) : undefined
      const sourcePort = sourceManifest?.outputs.find((port) => port.name === edge.source_port)
      const targetPort = targetManifest.inputs.find((port) => port.name === edge.target_port)
      if (!sourceNode || !sourceManifest || !sourcePort || !targetPort) {
        return
      }

      const sourceNodeLabel = nodeLabel(sourceNode, sourceManifest)
      enumerateSchemaFields(effectiveOutputSchema(definition, sourceNode, sourcePort)).forEach((field) => {
        sources.push({
          ...field,
          id: JSON.stringify([sourceNode.id, sourcePort.name, field.path, edge.target_port]),
          required: field.path === "/" ? sourcePort.required : field.required,
          sourceNodeId: sourceNode.id,
          sourceNodeLabel,
          sourcePort: sourcePort.name,
          targetPort: edge.target_port,
          label: sourceReference(sourceNodeLabel, sourcePort.name, field.path),
        })
      })
    })

  return {
    targets,
    sources: sources.filter((option, index) => sources.findIndex((item) => item.id === option.id) === index),
  }
}

export const sameBindingTarget = (left: InputBinding, right: Pick<InputBinding, "target_port" | "target_path">) =>
  left.target_port === right.target_port && left.target_path === right.target_path

/** Add or replace one target mapping, collapsing legacy duplicates for that target. */
export const upsertInputBinding = (bindings: InputBinding[], binding: InputBinding): InputBinding[] => {
  const firstMatch = bindings.findIndex((item) => sameBindingTarget(item, binding))
  if (firstMatch < 0) {
    return [...bindings, binding]
  }

  return bindings.flatMap((item, index) => {
    if (!sameBindingTarget(item, binding)) {
      return [item]
    }
    return index === firstMatch ? [binding] : []
  })
}

const constrainedValues = (schema: JsonSchema): string[] | undefined => {
  if (Array.isArray(schema.enum)) {
    return schema.enum.map((value) => JSON.stringify(value))
  }
  if ("const" in schema) {
    return [JSON.stringify(schema.const)]
  }
  return undefined
}

/** Mirrors the backend's pragmatic source-to-target schema compatibility check. */
export const schemasCompatible = (source: JsonSchema, target: JsonSchema) => {
  const sourceTypes = schemaTypes(source)
  const targetTypes = schemaTypes(target)
  if (!sourceTypes || !targetTypes) {
    return true
  }

  const sameTypes = sourceTypes.size === targetTypes.size && [...sourceTypes].every((type) => targetTypes.has(type))
  const sourceNumeric = [...sourceTypes].every((type) => type === "integer" || type === "number")
  const targetNumeric = [...targetTypes].every((type) => type === "integer" || type === "number")
  const numericCompatible = targetTypes.has("number") || (sourceTypes.size === 1 && sourceTypes.has("integer"))
  if (!sameTypes && !(sourceNumeric && targetNumeric && numericCompatible)) {
    return false
  }

  const sourceValues = constrainedValues(source)
  const targetValues = constrainedValues(target)
  if (!sourceValues || !targetValues) {
    return true
  }
  return sourceValues.every((value) => targetValues.includes(value))
}

export const isValidJsonPointer = (path: string) => {
  if (path === "" || path === "/") {
    return true
  }
  if (!path.startsWith("/")) {
    return false
  }
  return path.substring(1).split("/").every((token) => {
    if (token.length === 0) {
      return false
    }
    for (let index = 0; index < token.length; index += 1) {
      if (token[index] === "~" && token[index + 1] !== "0" && token[index + 1] !== "1") {
        return false
      }
      if (token[index] === "~") {
        index += 1
      }
    }
    return true
  })
}

/** Converts an array of InputBinding objects into a clean key-value JSON mapping */
export const bindingsToShorthandJson = (
  bindings: InputBinding[],
  options: BindingOptions,
): Record<string, string> => {
  const result: Record<string, string> = {}
  bindings.forEach((binding) => {
    const target = options.targets.find(
      (t) => t.port === binding.target_port && t.path === binding.target_path,
    )
    const source = options.sources.find(
      (s) =>
        s.targetPort === binding.target_port &&
        s.sourceNodeId === binding.source_node_id &&
        s.sourcePort === binding.source_port &&
        s.path === binding.source_path,
    )
    const targetKey = target?.label ?? `input.${binding.target_port}${pointerSuffix(binding.target_path)}`
    const sourceVal = source?.label ?? `output.${binding.source_port}${pointerSuffix(binding.source_path)}`
    result[targetKey] = sourceVal
  })
  return result
}

/** Parses JSON (either shorthand key-value or array of InputBindings) into valid InputBinding[] */
export const parseBindingJson = (
  jsonText: string,
  options: BindingOptions,
): { bindings: InputBinding[]; errors: string[] } => {
  const errors: string[] = []
  let parsed: unknown
  try {
    parsed = JSON.parse(jsonText)
  } catch (err) {
    return {
      bindings: [],
      errors: [`Invalid JSON syntax: ${err instanceof Error ? err.message : "Malformed JSON"}`],
    }
  }

  if (Array.isArray(parsed)) {
    const bindings: InputBinding[] = []
    parsed.forEach((item, index) => {
      if (typeof item !== "object" || item === null) {
        errors.push(`Item at index ${index} must be an object`)
        return
      }
      const b = item as Record<string, unknown>
      if (!b.target_port || !b.source_node_id || !b.source_port) {
        errors.push(`Item at index ${index} is missing required binding fields`)
        return
      }
      bindings.push({
        target_port: String(b.target_port),
        target_path: String(b.target_path ?? "/"),
        source_node_id: String(b.source_node_id),
        source_port: String(b.source_port),
        source_path: String(b.source_path ?? "/"),
        origin: (b.origin as "user" | "default" | "pass_through") ?? "user",
      })
    })
    return { bindings, errors }
  }

  if (typeof parsed !== "object" || parsed === null) {
    return { bindings: [], errors: ["Expected a JSON object of bindings or an array of binding objects"] }
  }

  const entries = Object.entries(parsed as Record<string, unknown>)
  const bindings: InputBinding[] = []

  const resolveTarget = (key: string): TargetBindingOption | undefined => {
    const cleanKey = key.trim()
    // Exact label match e.g. "input.prompt"
    const exact = options.targets.find((t) => t.label === cleanKey)
    if (exact) return exact

    // Match by port name e.g. "prompt"
    const portMatch = options.targets.find((t) => t.port === cleanKey && t.path === "/")
    if (portMatch) return portMatch

    // Match by stripped "input." prefix e.g. "input.prompt" -> "prompt"
    if (cleanKey.startsWith("input.")) {
      const stripped = cleanKey.slice(6)
      const direct = options.targets.find((t) => t.port === stripped && t.path === "/")
      if (direct) return direct
      const withDot = options.targets.find((t) => t.label.toLowerCase() === cleanKey.toLowerCase())
      if (withDot) return withDot
    }

    // Match by JSON Pointer e.g. "/prompt"
    if (cleanKey.startsWith("/")) {
      const ptr = options.targets.find((t) => t.path === cleanKey)
      if (ptr) return ptr
    }

    return options.targets.find(
      (t) => t.port.toLowerCase() === cleanKey.toLowerCase() || t.label.toLowerCase() === cleanKey.toLowerCase(),
    )
  }

  const resolveSource = (valueStr: string, target?: TargetBindingOption): SourceBindingOption | undefined => {
    const cleanVal = valueStr.trim()
    const pool = target ? options.sources.filter((s) => s.targetPort === target.port) : options.sources

    // 1. Exact label match e.g. "Prompt Template.output.text"
    const exact = pool.find((s) => s.label === cleanVal)
    if (exact) return exact

    // 2. Case-insensitive label match
    const caseMatch = pool.find((s) => s.label.toLowerCase() === cleanVal.toLowerCase())
    if (caseMatch) return caseMatch

    // 3. Match "output.<port>" e.g. "output.text"
    if (cleanVal.startsWith("output.")) {
      const portName = cleanVal.slice(7)
      const match = pool.find((s) => s.sourcePort === portName && s.path === "/")
      if (match) return match
      const nested = pool.find((s) => s.label.endsWith(`output.${portName}`))
      if (nested) return nested
    }

    // 4. Match raw port name e.g. "text"
    const rawPort = pool.find((s) => s.sourcePort === cleanVal && s.path === "/")
    if (rawPort) return rawPort

    // 5. Match pointer path e.g. "/text"
    if (cleanVal.startsWith("/")) {
      const ptr = pool.find((s) => s.path === cleanVal)
      if (ptr) return ptr
    }

    // 6. Suffix match
    return pool.find((s) => s.label.endsWith(cleanVal) || s.sourcePort.toLowerCase() === cleanVal.toLowerCase())
  }

  entries.forEach(([targetKey, sourceVal]) => {
    const target = resolveTarget(targetKey)
    if (!target) {
      errors.push(`Target input "${targetKey}" could not be resolved. Available inputs: ${options.targets.map((t) => t.label).join(", ")}`)
      return
    }

    if (typeof sourceVal !== "string") {
      errors.push(`Binding for "${targetKey}" must have a string source reference`)
      return
    }

    const source = resolveSource(sourceVal, target)
    if (!source) {
      const available = options.sources.filter((s) => s.targetPort === target.port)
      errors.push(
        `Source output "${sourceVal}" could not be found for target "${target.label}". Connected sources: ${
          available.length > 0 ? available.map((s) => s.label).join(", ") : "None"
        }`,
      )
      return
    }

    if (!schemasCompatible(source.schema, target.schema)) {
      errors.push(`Type mismatch: source "${source.label}" (${source.type}) is incompatible with target "${target.label}" (${target.type})`)
      return
    }

    bindings.push({
      target_port: target.port,
      target_path: target.path,
      source_node_id: source.sourceNodeId,
      source_port: source.sourcePort,
      source_path: source.path,
      origin: "user",
    })
  })

  return { bindings, errors }
}