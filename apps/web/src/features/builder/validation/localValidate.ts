import type { ProblemError, WorkflowDefinition } from "@/api/types"

export const localValidate = (definition: WorkflowDefinition): ProblemError[] => {
  const errors: ProblemError[] = []
  const nodeIds = new Set(definition.nodes.map((node) => node.id))
  if (definition.nodes.length > 250) {
    errors.push({ code: "GRAPH_TOO_LARGE", message: "Graph exceeds 250 nodes", path: "/nodes" })
  }
  definition.edges.forEach((edge, index) => {
    if (!nodeIds.has(edge.source_node_id) || !nodeIds.has(edge.target_node_id)) {
      errors.push({
        code: "MISSING_NODE_REF",
        message: "Edge references an unknown node",
        path: `/edges/${index}`,
        edgeId: edge.id,
      })
    }
  })
  definition.nodes.forEach((node) => {
    if (node.type === "control.loop@1") {
      const max = node.config.maxIterations
      if (typeof max !== "number" || max < 1) {
        errors.push({
          code: "UNBOUNDED_LOOP",
          message: "Loop requires maxIterations",
          path: "/config/maxIterations",
          nodeId: node.id,
        })
      }
    }
  })
  return errors
}
