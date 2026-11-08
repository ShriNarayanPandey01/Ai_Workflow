import { describe, expect, it } from "vitest"
import { applyEvent, initialProjection, parseSseBlock } from "./sseClient"

describe("sseClient", () => {
  it("parses an SSE block", () => {
    const event = parseSseBlock("id: 2\nevent: node.completed\ndata: {\"ok\":true}")
    expect(event?.sequence).toBe(2)
    expect(event?.type).toBe("node.completed")
  })

  it("deduplicates and ignores older sequences", () => {
    let state = initialProjection()
    state = applyEvent(state, { id: "1", sequence: 1, type: "execution.started", data: {} })
    state = applyEvent(state, { id: "1", sequence: 1, type: "execution.started", data: {} })
    expect(state.events).toHaveLength(1)
    state = applyEvent(state, { id: "0", sequence: 0, type: "old", data: {} })
    expect(state.sequence).toBe(1)
  })

  it("flags replay gaps", () => {
    let state = applyEvent(initialProjection(), { id: "1", sequence: 1, type: "a", data: {} })
    state = applyEvent(state, { id: "4", sequence: 4, type: "b", data: {} })
    expect(state.connection).toBe("reconnecting")
  })

  it("closes after a terminal event", () => {
    let state = applyEvent(initialProjection(), { id: "1", sequence: 1, type: "execution.started", data: {} })
    state = applyEvent(state, { id: "2", sequence: 2, type: "execution.completed", data: {} })
    expect(state.connection).toBe("ended")
  })
})
