export type RunEvent = {
  id: string
  sequence: number
  type: string
  data: unknown
}

export type SseProjection = {
  lastId: string | null
  sequence: number
  events: RunEvent[]
  connection: "connected" | "reconnecting" | "offline" | "ended"
}

export const initialProjection = (): SseProjection => ({
  lastId: null,
  sequence: 0,
  events: [],
  connection: "offline",
})

export const applyEvent = (state: SseProjection, event: RunEvent): SseProjection => {
  if (state.events.some((item) => item.id === event.id)) {
    return state
  }
  if (event.sequence <= state.sequence) {
    return state
  }
  if (state.sequence > 0 && event.sequence > state.sequence + 1) {
    return { ...state, connection: "reconnecting" }
  }
  const terminal = ["execution.completed", "execution.failed", "execution.cancelled", "execution.timed_out"]
  return {
    lastId: event.id,
    sequence: event.sequence,
    events: [...state.events, event],
    connection: terminal.includes(event.type) ? "ended" : "connected",
  }
}

export const parseSseBlock = (block: string): RunEvent | null => {
  let id = ""
  let type = "message"
  const dataLines: string[] = []
  block.split("\n").forEach((line) => {
    if (line.startsWith("id:")) {
      id = line.slice(3).trim()
    } else if (line.startsWith("event:")) {
      type = line.slice(6).trim()
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim())
    }
  })
  if (!id && dataLines.length === 0) {
    return null
  }
  let data: unknown = dataLines.join("\n")
  try {
    data = JSON.parse(String(data))
  } catch {
    /* keep string */
  }
  const sequence = Number(id) || 0
  return { id: id || String(sequence), sequence, type, data }
}
