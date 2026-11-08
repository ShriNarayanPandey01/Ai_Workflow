import { http, HttpResponse } from "msw"
import { setupServer } from "msw/node"
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest"
import { catalogApi } from "@/api/resources"
import { setAccessToken } from "@/api/client"

const server = setupServer(
  http.get("/api/v1/node-catalog", () =>
    HttpResponse.json({
      items: [
        {
          type: "data.input@1",
          display_name: "Input",
          description: "",
          category: "data",
          execution_owner: "control-plane",
          inputs: [],
          outputs: [{ name: "value", direction: "output", required: true, cardinality: "single", schema: { type: "object" } }],
          config_schema: { type: "object" },
          credential_slots: [],
          resource_slots: [],
          ui: { icon: "log-in", color_token: "data" },
        },
      ],
    }),
  ),
)

describe("catalogApi", () => {
  beforeAll(() => server.listen())
  afterEach(() => server.resetHandlers())
  afterAll(() => server.close())

  it("loads node catalog", async () => {
    setAccessToken("test")
    const result = await catalogApi.list()
    expect(result.items[0]?.type).toBe("data.input@1")
  })
})
