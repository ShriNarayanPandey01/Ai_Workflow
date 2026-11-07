import { describe, expect, it } from "vitest"
import type { NodeManifest, WorkflowNode } from "@/api/types"
import { defaultBindingsForEdge, newNode, portsCompatible } from "./graph"

const port = (name: string, direction: "input" | "output", type: string) => ({
  name,
  direction,
  required: true,
  cardinality: "single" as const,
  schema: { type },
})

const manifest = (type: string, inputs: ReturnType<typeof port>[], outputs: ReturnType<typeof port>[]): NodeManifest => ({
  type,
  display_name: type,
  description: "",
  category: "ai",
  execution_owner: "execution-engine",
  inputs,
  outputs,
  config_schema: { type: "object" },
  credential_slots: [],
  resource_slots: [],
  ui: { icon: "box", color_token: "ai" },
})

describe("portsCompatible", () => {
  it("accepts matching output to input", () => {
    expect(portsCompatible(port("text", "output", "string"), port("prompt", "input", "string"))).toBe(true)
  })

  it("rejects input to input", () => {
    expect(portsCompatible(port("a", "input", "string"), port("b", "input", "string"))).toBe(false)
  })
})

describe("defaultBindingsForEdge", () => {
  it("applies catalog default bindings", () => {
    const source: WorkflowNode = { id: "s", type: "ai.prompt-template@1", position: { x: 0, y: 0 }, config: {} }
    const target: WorkflowNode = { id: "t", type: "ai.chat-model@1", position: { x: 1, y: 0 }, config: {} }
    const catalog = [
      manifest("ai.prompt-template@1", [], [port("text", "output", "object")]),
      {
        ...manifest("ai.chat-model@1", [port("prompt", "input", "object")], []),
        inputs: [
          {
            ...port("prompt", "input", "object"),
            default_bindings: [
              { target_path: "/text", match: { source_ports: ["text"], source_paths: ["/text"] } },
            ],
          },
        ],
      },
    ]
    const bindings = defaultBindingsForEdge(catalog, source, target, "text", "prompt")
    expect(bindings[0]?.origin).toBe("default")
    expect(bindings[0]?.target_path).toBe("/text")
  })
})

describe("newNode", () => {
  it("applies catalog config defaults", () => {
    const chatManifest = {
      ...manifest("ai.chat-model@1", [], []),
      config_schema: {
        type: "object",
        properties: { model: { type: "string", default: "meta-models/muse-spark-open-1026" } },
      },
    }

    expect(newNode(chatManifest.type, { x: 0, y: 0 }, chatManifest).config).toEqual({
      model: "meta-models/muse-spark-open-1026",
    })
  })
})
