import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, Plus, RefreshCw, Trash2 } from "lucide-react"
import type { InputBinding, JsonValue, NodeManifest, WorkflowDefinition, WorkflowNode } from "@/api/types"
import { credentialApi, datasetApi } from "@/api/resources"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { ConditionBuilder } from "../conditions/ConditionBuilder"
import { SchemaForm } from "../inspector/SchemaForm"
import { findManifest } from "../graph"
import { updateNode, useWorkflowEditorStore } from "../workflowEditorStore"
import {
  bindingsToShorthandJson,
  buildBindingOptions,
  isValidJsonPointer,
  parseBindingJson,
  sameBindingTarget,
  schemasCompatible,
  upsertInputBinding,
} from "./bindingOptions"
import { toast } from "sonner"

type NodeInspectorProps = {
  projectId: string
  catalog: NodeManifest[]
  nodeIo?: { input?: JsonValue; output?: JsonValue }
}

export const NodeInspector = ({ projectId, catalog, nodeIo }: NodeInspectorProps) => {
  const definition = useWorkflowEditorStore((s) => s.definition)
  const selectedNodeId = useWorkflowEditorStore((s) => s.selectedNodeId)
  const mutate = useWorkflowEditorStore((s) => s.mutate)
  const node = definition?.nodes.find((item) => item.id === selectedNodeId)
  const manifest = node ? findManifest(catalog, node.type) : undefined
  const credentials = useQuery({
    queryKey: ["credentials", projectId],
    queryFn: () => credentialApi.list(projectId),
    enabled: Boolean(projectId),
  })
  const datasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => datasetApi.list(projectId),
    enabled: Boolean(projectId),
  })

  if (!definition || !node || !manifest) {
    return (
      <aside className="w-80 border-l bg-card p-3 text-xs text-muted-foreground">
        Select a node to configure it.
      </aside>
    )
  }

  const patchNode = (patch: Partial<WorkflowNode>) => {
    mutate((def) => updateNode(def, node.id, patch))
  }

  return (
    <aside className="flex w-80 flex-col border-l bg-card">
      <div className="sticky top-0 border-b p-3">
        <p className="text-sm font-medium">{manifest.display_name}</p>
        <p className="font-mono text-[10px] text-muted-foreground">{node.id}</p>
      </div>
      <Tabs defaultValue="config" className="flex min-h-0 flex-1 flex-col p-3">
        <TabsList>
          <TabsTrigger value="config">Config</TabsTrigger>
          <TabsTrigger value="bindings">Bindings</TabsTrigger>
          <TabsTrigger value="io">IO</TabsTrigger>
        </TabsList>
        <ScrollArea className="flex-1">
          <TabsContent value="config">
            <SchemaForm
              schema={manifest.config_schema}
              value={node.config}
              onChange={(config) => patchNode({ config })}
            />
            {node.type === "control.condition@1" ? (
              <div className="mt-3">
                <Label>Condition</Label>
                <ConditionBuilder
                  value={(node.config.condition as never) ?? null}
                  onChange={(condition) => patchNode({ config: { ...node.config, condition: condition as never } })}
                />
              </div>
            ) : null}
            {manifest.credential_slots?.map((slot) => (
              <div key={slot.name} className="mt-3 flex flex-col gap-1">
                <Label>{slot.name}</Label>
                <Select
                  value={node.credential_refs?.[slot.name] ?? ""}
                  onValueChange={(value) =>
                    patchNode({ credential_refs: { ...node.credential_refs, [slot.name]: value } })
                  }
                >
                  <SelectTrigger aria-label={slot.name}>
                    <SelectValue placeholder="Select credential" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {credentials.data
                        ?.filter((item) => item.type === slot.credential_type)
                        .map((item) => (
                          <SelectItem key={item.credentialId} value={item.credentialId}>
                            {item.name} · {item.maskedHint}
                          </SelectItem>
                        ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
            ))}
            {manifest.resource_slots?.map((slot) => (
              <div key={slot.name} className="mt-3 flex flex-col gap-1">
                <Label>{slot.name}</Label>
                <Select
                  value={node.resource_refs?.[slot.name] ?? ""}
                  onValueChange={(value) =>
                    patchNode({ resource_refs: { ...node.resource_refs, [slot.name]: value } })
                  }
                >
                  <SelectTrigger aria-label={slot.name}>
                    <SelectValue placeholder="Select dataset" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {datasets.data?.map((item) => (
                        <SelectItem key={item.datasetId} value={item.datasetId}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
            ))}
          </TabsContent>
          <TabsContent value="bindings">
            <BindingsTable
              key={node.id}
              definition={definition}
              catalog={catalog}
              node={node}
              bindings={node.input_bindings ?? []}
              onChange={(input_bindings) => patchNode({ input_bindings })}
            />
          </TabsContent>
          <TabsContent value="io">
            <Label>Input</Label>
            <Textarea readOnly value={JSON.stringify(nodeIo?.input ?? null, null, 2)} className="mt-1" />
            <Label className="mt-3">Output</Label>
            <Textarea readOnly value={JSON.stringify(nodeIo?.output ?? null, null, 2)} className="mt-1" />
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </aside>
  )
}

export const BindingsTable = ({
  definition,
  catalog,
  node,
  bindings,
  onChange,
}: {
  definition: WorkflowDefinition
  catalog: NodeManifest[]
  node: WorkflowNode
  bindings: InputBinding[]
  onChange: (bindings: InputBinding[]) => void
}) => {
  const options = useMemo(
    () => buildBindingOptions(definition, catalog, node.id),
    [catalog, definition, node.id],
  )
  const [editorMode, setEditorMode] = useState<"visual" | "json">("visual")
  const [targetId, setTargetId] = useState<string>()
  const [sourceId, setSourceId] = useState<string>()
  const [showSchemaRef, setShowSchemaRef] = useState(false)

  // JSON editor state
  const shorthandJson = useMemo(
    () => JSON.stringify(bindingsToShorthandJson(bindings, options), null, 2),
    [bindings, options],
  )
  const [jsonText, setJsonText] = useState(shorthandJson)
  const [jsonErrors, setJsonErrors] = useState<string[]>([])

  const selectedTarget = options.targets.find((option) => option.id === targetId)
  const availableSources = selectedTarget
    ? options.sources.filter((option) => option.targetPort === selectedTarget.port)
    : []
  const selectedSource = availableSources.find((option) => option.id === sourceId)
  const draftBinding: InputBinding | undefined =
    selectedTarget && selectedSource && schemasCompatible(selectedSource.schema, selectedTarget.schema)
      ? {
          target_port: selectedTarget.port,
          target_path: selectedTarget.path,
          source_node_id: selectedSource.sourceNodeId,
          source_port: selectedSource.sourcePort,
          source_path: selectedSource.path,
          origin: "user",
        }
      : undefined
  const replacesExisting = draftBinding ? bindings.some((binding) => sameBindingTarget(binding, draftBinding)) : false

  const selectTarget = (id: string) => {
    setTargetId(id)
    const target = options.targets.find((option) => option.id === id)
    const existing = target
      ? bindings.find((binding) => binding.target_port === target.port && binding.target_path === target.path)
      : undefined
    const existingSource = existing
      ? options.sources.find(
          (option) =>
            option.targetPort === existing.target_port &&
            option.sourceNodeId === existing.source_node_id &&
            option.sourcePort === existing.source_port &&
            option.path === existing.source_path,
        )
      : undefined
    setSourceId(existingSource && target && schemasCompatible(existingSource.schema, target.schema) ? existingSource.id : undefined)
  }

  const handleApplyJson = () => {
    const result = parseBindingJson(jsonText, options)
    if (result.errors.length > 0) {
      setJsonErrors(result.errors)
      toast.error("Invalid JSON bindings")
      return
    }
    setJsonErrors([])
    onChange(result.bindings)
    toast.success("Applied JSON bindings")
  }

  return (
    <div className="flex flex-col gap-3 pb-3">
      {/* Mode switcher */}
      <div className="flex items-center justify-between gap-1 rounded-md border bg-muted/40 p-1">
        <Button
          type="button"
          size="sm"
          variant={editorMode === "visual" ? "secondary" : "ghost"}
          className="h-7 flex-1 text-xs"
          onClick={() => {
            setEditorMode("visual")
            setJsonErrors([])
          }}
        >
          Visual Builder
        </Button>
        <Button
          type="button"
          size="sm"
          variant={editorMode === "json" ? "secondary" : "ghost"}
          className="h-7 flex-1 text-xs"
          onClick={() => {
            setEditorMode("json")
            setJsonText(JSON.stringify(bindingsToShorthandJson(bindings, options), null, 2))
            setJsonErrors([])
          }}
        >
          JSON Editor
        </Button>
      </div>

      {/* Collapsible Schemas Reference for all upstream & downstream ports */}
      <div className="rounded-md border bg-muted/20 p-2">
        <button
          type="button"
          className="flex w-full items-center justify-between text-[11px] font-medium text-muted-foreground hover:text-foreground"
          onClick={() => setShowSchemaRef((prev) => !prev)}
        >
          <span>Available Node Schemas ({options.sources.length} output fields)</span>
          <span>{showSchemaRef ? "Hide" : "Show"}</span>
        </button>
        {showSchemaRef && (
          <div className="mt-2 flex flex-col gap-2 border-t pt-2 text-[10px]">
            <div>
              <p className="font-semibold text-foreground">Connected Upstream Outputs:</p>
              {options.sources.length === 0 ? (
                <p className="italic text-muted-foreground">No upstream nodes connected.</p>
              ) : (
                <ul className="mt-1 flex flex-col gap-1">
                  {options.sources.map((s) => (
                    <li key={s.id} className="rounded border bg-card p-1">
                      <span className="font-mono font-medium text-foreground">{s.label}</span>
                      <div className="flex items-center gap-1.5 text-muted-foreground">
                        <Badge variant="outline" className="text-[9px] px-1 py-0">{s.type}</Badge>
                        <span>to target port <strong>{s.targetPort}</strong></span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <p className="font-semibold text-foreground">Target Inputs for this Node:</p>
              <ul className="mt-1 flex flex-col gap-1">
                {options.targets.map((t) => (
                  <li key={t.id} className="rounded border bg-card p-1">
                    <span className="font-mono font-medium text-foreground">{t.label}</span>
                    <div className="flex items-center gap-1.5 text-muted-foreground">
                      <Badge variant="outline" className="text-[9px] px-1 py-0">{t.type}</Badge>
                      {t.required && <Badge variant="destructive" className="text-[9px] px-1 py-0">Required</Badge>}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>

      {editorMode === "json" ? (
        /* JSON Editor Mode */
        <div className="flex flex-col gap-2 border-b pb-3">
          <div className="flex items-center justify-between">
            <Label htmlFor="json-binding-editor">Bindings JSON</Label>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-6 text-[10px]"
              onClick={() => {
                setJsonText(JSON.stringify(bindingsToShorthandJson(bindings, options), null, 2))
                setJsonErrors([])
              }}
            >
              Reset
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground">
            Bind input to output in JSON format, e.g. <code className="font-mono bg-muted px-1">{"{ \"input.prompt\": \"output.text\" }"}</code>
          </p>
          <Textarea
            id="json-binding-editor"
            aria-label="Bindings JSON Editor"
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            className="min-h-[140px] font-mono text-[11px]"
            placeholder={'{\n  "input.prompt": "output.text"\n}'}
          />
          {jsonErrors.length > 0 && (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 p-2 text-[11px] text-destructive">
              <p className="font-semibold">Binding Errors:</p>
              <ul className="list-inside list-disc">
                {jsonErrors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}
          <Button size="sm" onClick={handleApplyJson} className="gap-1.5">
            Apply JSON Bindings
          </Button>
        </div>
      ) : (
        /* Visual Builder Mode */
        <div className="flex flex-col gap-2 border-b pb-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="binding-target">Target input</Label>
            <Select value={selectedTarget?.id} onValueChange={selectTarget}>
              <SelectTrigger id="binding-target" aria-label="Target input">
                <SelectValue placeholder="Select input field" />
              </SelectTrigger>
              <SelectContent className="w-[var(--radix-select-trigger-width)]">
                <SelectGroup>
                  {options.targets.map((option) => (
                    <SelectItem key={option.id} value={option.id}>
                      <span className="flex min-w-0 flex-col">
                        <span className="break-all font-mono text-[11px]">{option.label}</span>
                        <span className="text-[10px] text-muted-foreground">
                          {option.type} · {option.required ? "required" : "optional"}
                        </span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1">
            <Label htmlFor="binding-source">Connected output</Label>
            <Select
              value={selectedSource?.id}
              onValueChange={setSourceId}
              disabled={!selectedTarget || availableSources.length === 0}
            >
              <SelectTrigger id="binding-source" aria-label="Connected output">
                <SelectValue placeholder="Select output field" />
              </SelectTrigger>
              <SelectContent className="w-[var(--radix-select-trigger-width)]">
                <SelectGroup>
                  {availableSources.map((option) => {
                    const compatible = selectedTarget ? schemasCompatible(option.schema, selectedTarget.schema) : false
                    return (
                      <SelectItem key={option.id} value={option.id} disabled={!compatible}>
                        <span className="flex min-w-0 flex-col">
                          <span className="break-all font-mono text-[11px]">{option.label}</span>
                          <span className="text-[10px] text-muted-foreground">
                            {option.type} · {compatible ? "compatible" : "incompatible"}
                          </span>
                        </span>
                      </SelectItem>
                    )
                  })}
                </SelectGroup>
              </SelectContent>
            </Select>
            {selectedTarget && availableSources.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">No incoming edge reaches {selectedTarget.port}.</p>
            ) : null}
          </div>

          {selectedTarget ? (
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <Badge variant="outline">Target: {selectedTarget.type}</Badge>
              <Badge variant="outline">{selectedTarget.required ? "Required" : "Optional"}</Badge>
              {selectedSource ? <Badge variant="secondary">Source: {selectedSource.type}</Badge> : null}
            </div>
          ) : null}

          <div className="flex flex-col gap-1">
            <Label>JSON preview</Label>
            <pre
              aria-label="Binding JSON preview"
              className="max-h-44 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-[10px] leading-4"
            >
              {JSON.stringify(draftBinding ?? null, null, 2)}
            </pre>
          </div>

          <Button
            size="sm"
            disabled={!draftBinding}
            onClick={() => draftBinding && onChange(upsertInputBinding(bindings, draftBinding))}
          >
            {replacesExisting ? <RefreshCw className="size-3.5" /> : <Plus className="size-3.5" />}
            {replacesExisting ? "Replace mapping" : "Add mapping"}
          </Button>
        </div>
      )}

      {/* Saved Mappings List */}
      <div className="flex items-center justify-between">
        <Label>Saved mappings</Label>
        <Badge variant="secondary">{bindings.length}</Badge>
      </div>
      {bindings.length === 0 ? <p className="text-xs text-muted-foreground">No explicit mappings.</p> : null}
      {bindings.map((binding, index) => {
        const target = options.targets.find(
          (option) => option.port === binding.target_port && option.path === binding.target_path,
        )
        const source = options.sources.find(
          (option) =>
            option.targetPort === binding.target_port &&
            option.sourceNodeId === binding.source_node_id &&
            option.sourcePort === binding.source_port &&
            option.path === binding.source_path,
        )
        const duplicate = bindings.findIndex((item) => sameBindingTarget(item, binding)) !== index
        const validPointers = isValidJsonPointer(binding.target_path) && isValidJsonPointer(binding.source_path)
        const compatible = target && source ? schemasCompatible(source.schema, target.schema) : false
        const sourceNode = definition.nodes.find((item) => item.id === binding.source_node_id)
        const sourceManifest = sourceNode ? findManifest(catalog, sourceNode.type) : undefined
        const targetLabel = target?.label ?? `input.${binding.target_port}${binding.target_path === "/" ? "" : binding.target_path}`
        const sourceLabel =
          source?.label ??
          `${sourceManifest?.display_name ?? binding.source_node_id}.output.${binding.source_port}${binding.source_path === "/" ? "" : binding.source_path}`

        return (
          <div
            key={`${binding.target_port}-${binding.target_path}-${binding.source_node_id}-${binding.source_port}-${binding.source_path}-${index}`}
            className="rounded-md border p-2"
          >
            <div className="mb-1.5 flex items-start justify-between gap-2">
              <div className="flex flex-wrap gap-1">
                <Badge variant="outline">
                  {binding.origin === "default" ? "Auto" : binding.origin === "user" ? "Manual" : "Pass-through"}
                </Badge>
                {!validPointers ? <Badge variant="destructive">Invalid pointer</Badge> : null}
                {validPointers && (!target || !source) ? <Badge variant="destructive">Unresolved</Badge> : null}
                {validPointers && target && source && !compatible ? (
                  <Badge variant="destructive">Incompatible</Badge>
                ) : null}
                {duplicate ? <Badge variant="destructive">Duplicate target</Badge> : null}
              </div>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="-mr-1 -mt-1 size-7"
                aria-label={`Remove mapping ${index + 1}`}
                title="Remove mapping"
                onClick={() => onChange(bindings.filter((_, itemIndex) => itemIndex !== index))}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
            <p className="break-all font-mono text-[11px] font-medium">{targetLabel}</p>
            <div className="mt-1 flex items-start gap-1 text-muted-foreground">
              <ArrowLeft className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
              <p className="break-all font-mono text-[10px]">{sourceLabel}</p>
            </div>
          </div>
        )
      })}
    </div>
  )
}
