import { useCallback, useEffect, useMemo, useState } from "react"
import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useParams } from "react-router-dom"
import { toast } from "sonner"
import { isApiError } from "@/api/problem"
import { catalogApi, executionApi, workflowApi } from "@/api/resources"
import type { ExecutionDetail, ProblemError, WorkflowEdge } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { NodePalette } from "./canvas/NodePalette"
import { NodeInspector } from "./inspector/NodeInspector"
import { ManifestNode, type ManifestNodeData } from "./nodes/ManifestNode"
import { applyEdgeBindings, findManifest, newNode, portsCompatible } from "./graph"
import { localValidate } from "./validation/localValidate"
import { ValidationPanel } from "./validation/ValidationPanel"
import { useWorkflowEditorStore } from "./workflowEditorStore"
import { RunPanel } from "@/features/runs/RunPanel"

const nodeTypes = { manifest: ManifestNode }

export const WorkflowBuilder = () => {
  const { projectId = "", workflowId = "" } = useParams()
  const catalogQuery = useQuery({ queryKey: ["catalog"], queryFn: catalogApi.list })
  const catalog = catalogQuery.data?.items ?? []
  const draftQuery = useQuery({
    queryKey: ["draft", projectId, workflowId],
    queryFn: () => workflowApi.getDraft(projectId, workflowId),
    enabled: Boolean(projectId && workflowId),
  })
  const workflowQuery = useQuery({
    queryKey: ["workflow", projectId, workflowId],
    queryFn: () => workflowApi.get(projectId, workflowId),
    enabled: Boolean(projectId && workflowId),
  })
  const load = useWorkflowEditorStore((s) => s.load)
  const definition = useWorkflowEditorStore((s) => s.definition)
  const dirty = useWorkflowEditorStore((s) => s.dirty)
  const conflict = useWorkflowEditorStore((s) => s.conflict)
  const mutate = useWorkflowEditorStore((s) => s.mutate)
  const undo = useWorkflowEditorStore((s) => s.undo)
  const redo = useWorkflowEditorStore((s) => s.redo)
  const setSelection = useWorkflowEditorStore((s) => s.setSelection)
  const markSaved = useWorkflowEditorStore((s) => s.markSaved)
  const setConflict = useWorkflowEditorStore((s) => s.setConflict)
  const baseRevision = useWorkflowEditorStore((s) => s.baseRevision)
  const selectedNodeId = useWorkflowEditorStore((s) => s.selectedNodeId)
  const [runId, setRunId] = useState<string | null>(null)
  const [runOpen, setRunOpen] = useState(false)
  const [runInput, setRunInput] = useState("{}")
  const [runExpanded, setRunExpanded] = useState(false)
  const [serverErrors, setServerErrors] = useState<ProblemError[]>([])

  useEffect(() => {
    if (draftQuery.data && !dirty) {
      load(draftQuery.data.revision, draftQuery.data.definition)
    }
  }, [draftQuery.data, dirty, load])

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault()
        event.returnValue = ""
      }
    }
    window.addEventListener("beforeunload", handleBeforeUnload)
    return () => window.removeEventListener("beforeunload", handleBeforeUnload)
  }, [dirty])

  const localErrors = useMemo(() => (definition ? localValidate(definition) : []), [definition])
  const allErrors = useMemo(() => [...localErrors, ...serverErrors], [localErrors, serverErrors])

  const runQuery = useQuery({
    queryKey: ["run", projectId, runId],
    queryFn: () => executionApi.get(projectId, runId ?? ""),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ["SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(status) ? false : 1500
    },
  })

  const invalidNodeIds = useMemo(() => {
    const ids = new Set<string>()
    allErrors.forEach((err) => {
      if (err.nodeId) {
        ids.add(err.nodeId)
      }
    })
    return ids
  }, [allErrors])

  const runNodes = runQuery.data?.nodes
  const nodeStatusMap = useMemo(() => {
    const map = new Map<string, string>()
    if (runNodes) {
      runNodes.forEach((n) => {
        map.set(n.nodeId, n.status)
      })
    }
    return map
  }, [runNodes])

  const rfNodes = useMemo<Node<ManifestNodeData>[]>(() => {
    if (!definition) {
      return []
    }
    return definition.nodes.map((node) => ({
      id: node.id,
      type: "manifest",
      position: node.position,
      data: {
        label: findManifest(catalog, node.type)?.display_name ?? node.type,
        type: node.type,
        manifest: findManifest(catalog, node.type),
        invalid: invalidNodeIds.has(node.id),
        status: nodeStatusMap.get(node.id),
      },
    }))
  }, [definition, catalog, invalidNodeIds, nodeStatusMap])

  const rfEdges = useMemo<Edge[]>(() => {
    if (!definition) {
      return []
    }
    return definition.edges.map((edge) => ({
      id: edge.id,
      source: edge.source_node_id,
      target: edge.target_node_id,
      sourceHandle: edge.source_port,
      targetHandle: edge.target_port,
      label: edge.label ?? edge.condition?.op,
    }))
  }, [definition])

  const [nodes, setNodes, onNodesChange] = useNodesState(rfNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(rfEdges)

  useEffect(() => {
    setNodes(rfNodes)
  }, [rfNodes, setNodes])

  useEffect(() => {
    setEdges(rfEdges)
  }, [rfEdges, setEdges])

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!definition || !connection.source || !connection.target) {
        return
      }
      const sourceNode = definition.nodes.find((n) => n.id === connection.source)
      const targetNode = definition.nodes.find((n) => n.id === connection.target)
      const sourceManifest = sourceNode ? findManifest(catalog, sourceNode.type) : undefined
      const targetManifest = targetNode ? findManifest(catalog, targetNode.type) : undefined
      const sourcePort = sourceManifest?.outputs.find((p) => p.name === connection.sourceHandle)
      const targetPort = targetManifest?.inputs.find((p) => p.name === connection.targetHandle)
      if (!portsCompatible(sourcePort, targetPort)) {
        toast.error("Incompatible ports")
        return
      }
      const edge: WorkflowEdge = {
        id: crypto.randomUUID(),
        source_node_id: connection.source,
        source_port: connection.sourceHandle ?? sourceManifest?.outputs[0]?.name ?? "value",
        target_node_id: connection.target,
        target_port: connection.targetHandle ?? targetManifest?.inputs[0]?.name ?? "value",
      }
      mutate((def) => {
        const withEdge = { ...def, edges: [...def.edges, edge] }
        return applyEdgeBindings(withEdge, catalog, edge)
      })
      setEdges((eds) => addEdge(connection, eds))
    },
    [catalog, definition, mutate, setEdges],
  )

  const handleAddNode = (type: string) => {
    mutate((def) => ({
      ...def,
      nodes: [
        ...def.nodes,
        newNode(type, { x: 120 + def.nodes.length * 24, y: 80 }, findManifest(catalog, type)),
      ],
    }))
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!definition) {
        throw new Error("No definition")
      }
      return workflowApi.putDraft(projectId, workflowId, baseRevision, definition)
    },
    onSuccess: (draft) => {
      markSaved(draft.revision, draft.definition)
      toast.success("Draft saved")
    },
    onError: (error) => {
      if (isApiError(error) && error.problem.status === 409) {
        setConflict(true)
        return
      }
      toast.error(error instanceof Error ? error.message : "Save failed")
    },
  })

  const validateMutation = useMutation({
    mutationFn: async () => {
      if (dirty && definition) {
        const saved = await workflowApi.putDraft(projectId, workflowId, baseRevision, definition)
        markSaved(saved.revision, saved.definition)
      }
      return workflowApi.validate(projectId, workflowId)
    },
    onSuccess: (result) => {
      setServerErrors(result.errors ?? [])
      if (result.valid) {
        toast.success("Workflow is valid")
      } else {
        const count = result.errors?.length ?? 1
        toast.error(`Workflow has ${count} validation issue${count > 1 ? "s" : ""}`)
        setRunExpanded(true)
      }
    },
    onError: (error) => {
      if (isApiError(error)) {
        setServerErrors(error.problem.errors ?? [])
        setRunExpanded(true)
        toast.error(error.problem.detail || error.problem.title || "Validation failed")
      } else {
        toast.error(error instanceof Error ? error.message : "Validation failed")
      }
    },
  })

  const publishMutation = useMutation({
    mutationFn: () => workflowApi.publish(projectId, workflowId),
    onSuccess: (version) => {
      toast.success(`Published v${version.versionNumber}`)
    },
    onError: (error) => {
      if (isApiError(error)) {
        setServerErrors(error.problem.errors ?? [])
        setRunExpanded(true)
        toast.error(error.problem.detail || error.problem.title || "Publish failed")
      } else {
        toast.error("Publish failed")
      }
    },
  })

  const startRun = useMutation({
    mutationFn: async () => {
      let input: unknown
      try {
        input = JSON.parse(runInput)
      } catch (err) {
        throw new Error(`Invalid JSON input: ${err instanceof Error ? err.message : "Malformed JSON"}`)
      }
      if (dirty && definition) {
        const saved = await workflowApi.putDraft(projectId, workflowId, baseRevision, definition)
        markSaved(saved.revision, saved.definition)
      }
      return executionApi.start(projectId, workflowId, {
        mode: "draft",
        input,
        idempotencyKey: crypto.randomUUID(),
      })
    },
    onSuccess: (result) => {
      setRunId(result.runId)
      setRunOpen(false)
      setRunExpanded(true)
      toast.success("Run accepted")
    },
    onError: (error) => {
      if (isApiError(error)) {
        if (error.problem.errors) {
          setServerErrors(error.problem.errors)
          setRunExpanded(true)
        }
        toast.error(error.problem.detail || error.problem.title || "Failed to start run")
      } else {
        toast.error(error instanceof Error ? error.message : "Failed to start run")
      }
    },
  })

  if (draftQuery.isLoading || !definition) {
    return <p className="p-6 text-sm text-muted-foreground">Loading draft…</p>
  }

  return (
    <div className="-m-6 flex h-[calc(100vh-3rem)] flex-col">
      <div className="flex items-center justify-between border-b bg-card px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{workflowQuery.data?.name ?? "Workflow"}</span>
          <Badge variant={dirty ? "secondary" : conflict ? "destructive" : "outline"}>
            {conflict ? "Conflict" : dirty ? "Dirty" : "Saved"}
          </Badge>
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" onClick={undo} aria-label="Undo">
            Undo
          </Button>
          <Button size="sm" variant="ghost" onClick={redo} aria-label="Redo">
            Redo
          </Button>
          <Button size="sm" disabled={!dirty} onClick={() => saveMutation.mutate()}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => validateMutation.mutate()}>
            Validate
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={dirty || allErrors.length > 0}
            onClick={() => publishMutation.mutate()}
          >
            Publish
          </Button>
          <Button size="sm" variant={dirty ? "outline" : "default"} onClick={() => setRunOpen(true)}>
            Run
          </Button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <NodePalette catalog={catalog} onAdd={handleAddNode} />
        <div className="relative min-w-0 flex-1">
          <div className="lg:hidden p-6 text-sm">Open the builder on a desktop viewport to edit the canvas.</div>
          <div className="hidden h-full lg:block">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onNodeDragStop={(_event, node) => {
                mutate((def) => ({
                  ...def,
                  nodes: def.nodes.map((n) => (n.id === node.id ? { ...n, position: node.position } : n)),
                }))
              }}
              onDragOver={(event) => {
                event.preventDefault()
                event.dataTransfer.dropEffect = "move"
              }}
              onDrop={(event) => {
                event.preventDefault()
                const type = event.dataTransfer.getData("application/aiw-node")
                if (!type) {
                  return
                }
                handleAddNode(type)
              }}
              onEdgesChange={onEdgesChange}
              onConnect={handleConnect}
              onSelectionChange={({ nodes: selected }) => setSelection(selected[0]?.id ?? null)}
              fitView
              proOptions={{ hideAttribution: true }}
              onPaneContextMenu={(e) => e.preventDefault()}
              aria-label="Workflow canvas"
            >
              <Background />
              <MiniMap />
              <Controls />
            </ReactFlow>
          </div>
        </div>
        <NodeInspector
          projectId={projectId}
          catalog={catalog}
          nodeIo={nodeIoFor(runQuery.data, selectedNodeId)}
        />
      </div>
      <div className="border-t bg-card" style={{ height: runExpanded ? 240 : 36 }}>
        <button
          type="button"
          className="flex h-9 w-full items-center justify-between px-3 text-xs"
          onClick={() => setRunExpanded((v) => !v)}
        >
          <span>Run inspector {runId ? `· ${runId.slice(0, 8)}` : ""}</span>
          <span>{runExpanded ? "Collapse" : "Expand"}</span>
        </button>
        {runExpanded ? (
          <div className="grid h-[204px] grid-cols-2 gap-2">
            <RunPanel projectId={projectId} runId={runId} />
            <ValidationPanel errors={allErrors} onFocus={(nodeId) => setSelection(nodeId ?? null)} />
          </div>
        ) : null}
      </div>
      <Dialog open={runOpen} onOpenChange={setRunOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Start draft run</DialogTitle>
            <DialogDescription>Provide JSON matching the workflow input schema.</DialogDescription>
          </DialogHeader>
          <Textarea value={runInput} onChange={(event) => setRunInput(event.target.value)} />
          <DialogFooter>
            <Button onClick={() => startRun.mutate()}>Start</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={conflict} onOpenChange={setConflict}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Draft conflict</DialogTitle>
            <DialogDescription>The server revision changed. Keep local edits or reload.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConflict(false)}>
              Keep local
            </Button>
            <Button
              onClick={() => {
                if (draftQuery.data) {
                  load(draftQuery.data.revision, draftQuery.data.definition)
                }
                void draftQuery.refetch()
              }}
            >
              Reload server
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

const nodeIoFor = (detail: ExecutionDetail | undefined, nodeId: string | null) => {
  const node = detail?.nodes.find((item) => item.nodeId === nodeId)
  return node ? { input: node.input, output: node.output } : undefined
}
