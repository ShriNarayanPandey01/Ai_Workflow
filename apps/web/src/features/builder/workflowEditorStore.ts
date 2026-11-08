import { create } from "zustand"
import type { ProblemError, WorkflowDefinition, WorkflowEdge, WorkflowNode } from "@/api/types"
import { cloneDefinition } from "./graph"

type EditorSnapshot = {
  definition: WorkflowDefinition
}

type EditorState = {
  baseRevision: number
  definition: WorkflowDefinition | null
  dirty: boolean
  conflict: boolean
  selectedNodeId: string | null
  selectedEdgeId: string | null
  undoStack: EditorSnapshot[]
  redoStack: EditorSnapshot[]
  localErrors: ProblemError[]
  load: (revision: number, definition: WorkflowDefinition) => void
  mutate: (updater: (definition: WorkflowDefinition) => WorkflowDefinition) => void
  setSelection: (nodeId: string | null, edgeId?: string | null) => void
  undo: () => void
  redo: () => void
  markSaved: (revision: number, definition: WorkflowDefinition) => void
  setConflict: (value: boolean) => void
  setLocalErrors: (errors: ProblemError[]) => void
}

export const emptyPolicy = {
  timeout_seconds: 300,
  max_node_executions: 50,
  max_parallel_nodes: 4,
  max_fan_out_items: 100,
  max_task_seconds: 600,
  max_provider_calls: 100,
  max_artifact_bytes: 10485760,
  max_estimated_cost: null,
  default_retry: {
    max_attempts: 3,
    initial_backoff_ms: 500,
    max_backoff_ms: 10000,
    multiplier: 2,
    jitter: true,
  },
}

export const useWorkflowEditorStore = create<EditorState>((set, get) => ({
  baseRevision: 1,
  definition: null,
  dirty: false,
  conflict: false,
  selectedNodeId: null,
  selectedEdgeId: null,
  undoStack: [],
  redoStack: [],
  localErrors: [],
  load: (revision, definition) => {
    set({
      baseRevision: revision,
      definition: cloneDefinition(definition),
      dirty: false,
      conflict: false,
      undoStack: [],
      redoStack: [],
      selectedNodeId: null,
      selectedEdgeId: null,
    })
  },
  mutate: (updater) => {
    const current = get().definition
    if (!current) {
      return
    }
    const previous = cloneDefinition(current)
    const next = updater(cloneDefinition(current))
    set({
      definition: next,
      dirty: true,
      undoStack: [...get().undoStack, { definition: previous }],
      redoStack: [],
    })
  },
  setSelection: (nodeId, edgeId = null) => {
    set({ selectedNodeId: nodeId, selectedEdgeId: edgeId })
  },
  undo: () => {
    const { undoStack, definition, redoStack } = get()
    const snapshot = undoStack.at(-1)
    if (!snapshot || !definition) {
      return
    }
    set({
      definition: snapshot.definition,
      dirty: true,
      undoStack: undoStack.slice(0, -1),
      redoStack: [...redoStack, { definition: cloneDefinition(definition) }],
    })
  },
  redo: () => {
    const { redoStack, definition, undoStack } = get()
    const snapshot = redoStack.at(-1)
    if (!snapshot || !definition) {
      return
    }
    set({
      definition: snapshot.definition,
      dirty: true,
      redoStack: redoStack.slice(0, -1),
      undoStack: [...undoStack, { definition: cloneDefinition(definition) }],
    })
  },
  markSaved: (revision, definition) => {
    set({
      baseRevision: revision,
      definition: cloneDefinition(definition),
      dirty: false,
      conflict: false,
    })
  },
  setConflict: (value) => set({ conflict: value }),
  setLocalErrors: (errors) => set({ localErrors: errors }),
}))

export const updateNode = (
  definition: WorkflowDefinition,
  nodeId: string,
  patch: Partial<WorkflowNode>,
): WorkflowDefinition => {
  return {
    ...definition,
    nodes: definition.nodes.map((node) => (node.id === nodeId ? { ...node, ...patch } : node)),
  }
}

export const updateEdge = (
  definition: WorkflowDefinition,
  edgeId: string,
  patch: Partial<WorkflowEdge>,
): WorkflowDefinition => {
  return {
    ...definition,
    edges: definition.edges.map((edge) => (edge.id === edgeId ? { ...edge, ...patch } : edge)),
  }
}
