import { describe, expect, it } from "vitest"
import type {
  InputBinding,
  NodeManifest,
  PortDefinition,
  WorkflowDefinition,
  WorkflowNode,
} from "@/api/types"
import {
  bindingsToShorthandJson,
  buildBindingOptions,
  enumerateSchemaFields,
  isValidJsonPointer,
  parseBindingJson,
  pointerSuffix,
  schemasCompatible,
  upsertInputBinding,
  type JsonSchema,
} from "./bindingOptions"

const port = (
  name: string,
  direction: "input" | "output",
  schema: JsonSchema,
): PortDefinition => ({
  name,
  direction,
  required: true,
  cardinality: "single",
  schema,
})

const manifest = (
  type: string,
  inputs: PortDefinition[],
  outputs: PortDefinition[],
  displayName = type,
): NodeManifest => ({
  type,
  display_name: displayName,
  description: "",
  category: "data",
  execution_owner: "execution-engine",
  inputs,
  outputs,
  config_schema: { type: "object" },
  credential_slots: [],
  resource_slots: [],
  ui: { icon: "box", color_token: "data" },
})

const node = (id: string, type: string): WorkflowNode => ({
  id,
  type,
  position: { x: 0, y: 0 },
  config: {},
})

const definition = (nodes: WorkflowNode[], edges: WorkflowDefinition["edges"]): WorkflowDefinition => ({
  schema_version: "1.0",
  workflow_id: "11111111-1111-4111-8111-111111111100",
  name: "Bindings",
  input_schema: {
    type: "object",
    required: ["query"],
    properties: { query: { type: "string" }, attempts: { type: "integer" } },
  },
  output_schema: {
    type: "object",
    required: ["result"],
    properties: { result: { type: "string" }, score: { type: "number" } },
  },
  nodes,
  edges,
  execution_policy: {
    timeout_seconds: 300,
    max_node_executions: 50,
    max_parallel_nodes: 4,
    max_fan_out_items: 100,
    max_task_seconds: 600,
    max_provider_calls: 100,
    max_artifact_bytes: 10485760,
    default_retry: {
      max_attempts: 3,
      initial_backoff_ms: 500,
      max_backoff_ms: 10000,
      multiplier: 2,
      jitter: true,
    },
  },
})

describe("enumerateSchemaFields", () => {
  it("includes the whole value and recursively escapes property pointers", () => {
    const fields = enumerateSchemaFields({
      type: "object",
      required: ["profile"],
      properties: {
        profile: {
          type: "object",
          required: ["display/name"],
          properties: {
            "display/name": { type: "string" },
            "til~de": { type: "integer" },
          },
        },
      },
    })

    expect(fields.map((field) => field.path)).toEqual([
      "/",
      "/profile",
      "/profile/display~1name",
      "/profile/til~0de",
    ])
    expect(fields.find((field) => field.path === "/profile")?.required).toBe(true)
    expect(fields.find((field) => field.path === "/profile/display~1name")?.required).toBe(true)
    expect(pointerSuffix("/profile/display~1name")).toBe(".profile.display/name")
  })
})

describe("buildBindingOptions", () => {
  it("resolves data input and output value ports from workflow schemas", () => {
    const inputNode = node("input-node", "data.input@1")
    const outputNode = node("output-node", "data.output@1")
    const workflow = definition(
      [inputNode, outputNode],
      [
        {
          id: "edge-1",
          source_node_id: inputNode.id,
          source_port: "value",
          target_node_id: outputNode.id,
          target_port: "value",
        },
      ],
    )
    const catalog = [
      manifest("data.input@1", [], [port("value", "output", { type: "object" })], "Input"),
      manifest("data.output@1", [port("value", "input", { type: "object" })], [], "Output"),
    ]

    const options = buildBindingOptions(workflow, catalog, outputNode.id)

    expect(options.targets.map((option) => [option.path, option.type])).toEqual([
      ["/", "object"],
      ["/result", "string"],
      ["/score", "number"],
    ])
    expect(options.sources.map((option) => [option.path, option.type])).toEqual([
      ["/", "object"],
      ["/query", "string"],
      ["/attempts", "integer"],
    ])
  })

  it("returns only direct incoming edge ports and tags their exact target ports", () => {
    const source = node("source", "test.source@1")
    const disconnected = node("disconnected", "test.source@1")
    const target = node("target", "test.target@1")
    const otherTarget = node("other-target", "test.target@1")
    const workflow = definition(
      [source, disconnected, target, otherTarget],
      [
        {
          id: "edge-first",
          source_node_id: source.id,
          source_port: "alpha",
          target_node_id: target.id,
          target_port: "first",
        },
        {
          id: "edge-second",
          source_node_id: source.id,
          source_port: "beta",
          target_node_id: target.id,
          target_port: "second",
        },
        {
          id: "edge-other-target",
          source_node_id: disconnected.id,
          source_port: "alpha",
          target_node_id: otherTarget.id,
          target_port: "first",
        },
      ],
    )
    const catalog = [
      manifest(
        "test.source@1",
        [],
        [
          port("alpha", "output", { type: "object", properties: { name: { type: "string" } } }),
          port("beta", "output", { type: "object", properties: { count: { type: "integer" } } }),
        ],
        "Source",
      ),
      manifest(
        "test.target@1",
        [
          port("first", "input", { type: "object", properties: { name: { type: "string" } } }),
          port("second", "input", { type: "object", properties: { count: { type: "number" } } }),
        ],
        [],
        "Target",
      ),
    ]

    const options = buildBindingOptions(workflow, catalog, target.id)

    expect(options.sources.filter((option) => option.targetPort === "first").map((option) => option.sourcePort)).toEqual([
      "alpha",
      "alpha",
    ])
    expect(options.sources.filter((option) => option.targetPort === "second").map((option) => option.sourcePort)).toEqual([
      "beta",
      "beta",
    ])
    expect(options.sources.some((option) => option.sourceNodeId === disconnected.id)).toBe(false)
  })
})

describe("schemasCompatible", () => {
  it("matches backend type widening and enum subset behavior", () => {
    expect(schemasCompatible({ type: "string" }, { type: "string" })).toBe(true)
    expect(schemasCompatible({ type: "string" }, { type: "number" })).toBe(false)
    expect(schemasCompatible({ type: "integer" }, { type: "number" })).toBe(true)
    expect(schemasCompatible({ type: "number" }, { type: "integer" })).toBe(false)
    expect(schemasCompatible({ type: "string", enum: ["a"] }, { type: "string", enum: ["a", "b"] })).toBe(true)
    expect(schemasCompatible({ type: "string", enum: ["a", "c"] }, { type: "string", enum: ["a", "b"] })).toBe(false)
    expect(schemasCompatible({}, { type: "boolean" })).toBe(true)
  })
})

describe("upsertInputBinding", () => {
  it("replaces and collapses mappings for the same canonical target", () => {
    const old: InputBinding = {
      target_port: "variables",
      target_path: "/name",
      source_node_id: "old",
      source_port: "value",
      source_path: "/name",
      origin: "default",
    }
    const other: InputBinding = { ...old, target_path: "/email", source_path: "/email" }
    const replacement: InputBinding = {
      ...old,
      source_node_id: "new",
      source_path: "/display_name",
      origin: "user",
    }

    expect(upsertInputBinding([old, other, { ...old, source_node_id: "duplicate" }], replacement)).toEqual([
      replacement,
      other,
    ])
  })
})

describe("isValidJsonPointer", () => {
  it("accepts canonical whole and escaped pointers and rejects malformed tokens", () => {
    expect(isValidJsonPointer("/")).toBe(true)
    expect(isValidJsonPointer("/profile/display~1name")).toBe(true)
    expect(isValidJsonPointer("profile/name")).toBe(false)
    expect(isValidJsonPointer("/profile//name")).toBe(false)
    expect(isValidJsonPointer("/profile/~2name")).toBe(false)
  })
})

describe("parseBindingJson and bindingsToShorthandJson", () => {
  const sourceNode = node("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1", "test.source@1")
  const targetNode = node("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2", "test.target@1")
  const catalog = [
    manifest(
      "test.source@1",
      [],
      [port("text", "output", { type: "string" })],
      "Prompt Template",
    ),
    manifest(
      "test.target@1",
      [port("prompt", "input", { type: "string" })],
      [],
      "Chat Model",
    ),
  ]
  const workflow = definition(
    [sourceNode, targetNode],
    [
      {
        id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        source_node_id: sourceNode.id,
        source_port: "text",
        target_node_id: targetNode.id,
        target_port: "prompt",
      },
    ],
  )
  const options = buildBindingOptions(workflow, catalog, targetNode.id)

  it("parses shorthand key-value JSON { 'input.prompt': 'output.text' }", () => {
    const json = JSON.stringify({ "input.prompt": "output.text" })
    const { bindings, errors } = parseBindingJson(json, options)
    expect(errors).toEqual([])
    expect(bindings).toHaveLength(1)
    expect(bindings[0]).toEqual({
      target_port: "prompt",
      target_path: "/",
      source_node_id: sourceNode.id,
      source_port: "text",
      source_path: "/",
      origin: "user",
    })
  })

  it("parses shorthand key-value with node label { 'input.prompt': 'Prompt Template.output.text' }", () => {
    const json = JSON.stringify({ "input.prompt": "Prompt Template.output.text" })
    const { bindings, errors } = parseBindingJson(json, options)
    expect(errors).toEqual([])
    expect(bindings).toHaveLength(1)
    expect(bindings[0].target_port).toBe("prompt")
    expect(bindings[0].source_port).toBe("text")
  })

  it("serializes bindings to shorthand JSON", () => {
    const bindings: InputBinding[] = [
      {
        target_port: "prompt",
        target_path: "/",
        source_node_id: sourceNode.id,
        source_port: "text",
        source_path: "/",
        origin: "user",
      },
    ]
    const shorthand = bindingsToShorthandJson(bindings, options)
    expect(shorthand).toEqual({
      "input.prompt": "Prompt Template.output.text",
    })
  })

  it("returns error for unresolvable target or source", () => {
    const json = JSON.stringify({ "nonexistent_input": "output.text" })
    const { bindings, errors } = parseBindingJson(json, options)
    expect(bindings).toHaveLength(0)
    expect(errors).toHaveLength(1)
    expect(errors[0]).toContain("could not be resolved")
  })
})