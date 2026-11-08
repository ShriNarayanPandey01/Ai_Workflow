import { useState } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { triggerApi, workflowApi } from "@/api/resources"
import { EmptyState } from "@/components/EmptyState"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"

export const TriggersPage = () => {
  const { projectId = "" } = useParams()
  const workflows = useQuery({
    queryKey: ["workflows", projectId],
    queryFn: () => workflowApi.list(projectId),
    enabled: Boolean(projectId),
  })
  const [workflowId, setWorkflowId] = useState("")

  if (!projectId) {
    return <p className="text-sm">Select a project</p>
  }

  return (
    <div>
      <PageHeader title="Triggers" description="Pin to a published version. Draft test runs are started from the builder." />
      <div className="mb-4 max-w-sm">
        <Label>Workflow</Label>
        <Select value={workflowId} onValueChange={setWorkflowId}>
          <SelectTrigger aria-label="Workflow">
            <SelectValue placeholder="Choose workflow" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {workflows.data?.items.map((item) => (
                <SelectItem key={item.workflowId} value={item.workflowId}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      {workflowId ? <TriggerList projectId={projectId} workflowId={workflowId} /> : <EmptyState title="Pick a workflow" description="Triggers are stored per workflow." />}
    </div>
  )
}

const TriggerList = ({ projectId, workflowId }: { projectId: string; workflowId: string }) => {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["triggers", projectId, workflowId],
    queryFn: () => triggerApi.list(projectId, workflowId),
  })
  const versions = useQuery({
    queryKey: ["versions", projectId, workflowId],
    queryFn: () => workflowApi.versions(projectId, workflowId),
  })
  const [name, setName] = useState("Manual")
  const [type, setType] = useState("manual")
  const [versionId, setVersionId] = useState("")
  const [cron, setCron] = useState("0 * * * *")
  const create = useMutation({
    mutationFn: () =>
      triggerApi.create(projectId, workflowId, {
        type,
        name,
        workflowVersionId: versionId,
        config: type === "schedule" ? { cron } : {},
      }),
    onSuccess: (trigger) => {
      void queryClient.invalidateQueries({ queryKey: ["triggers", projectId, workflowId] })
      if (trigger.secret) {
        toast.success("Copy the webhook secret now — it is shown only once")
        void navigator.clipboard.writeText(trigger.secret)
      }
    },
  })
  const patch = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      triggerApi.patch(projectId, workflowId, id, { status }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["triggers", projectId, workflowId] }),
  })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <Label>Name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <Label>Type</Label>
          <Select value={type} onValueChange={setType}>
            <SelectTrigger className="w-40" aria-label="Trigger type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {["manual", "webhook", "schedule"].map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label>Published version</Label>
          <Select value={versionId} onValueChange={setVersionId}>
            <SelectTrigger className="w-48" aria-label="Published version">
              <SelectValue placeholder="Version" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {versions.data?.map((item) => (
                  <SelectItem key={item.versionId} value={item.versionId}>
                    v{item.versionNumber}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        {type === "schedule" ? (
          <div>
            <Label>Cron</Label>
            <Input className="font-mono" value={cron} onChange={(e) => setCron(e.target.value)} />
          </div>
        ) : null}
        <Button disabled={!versionId} onClick={() => create.mutate()}>
          Create
        </Button>
      </div>
      {query.data?.length === 0 ? <EmptyState title="No triggers" description="Publish a version first, then pin a trigger." /> : null}
      {query.data?.map((trigger) => (
        <Card key={trigger.triggerId}>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>
              {trigger.name} · {trigger.type}
            </CardTitle>
            <Switch
              checked={trigger.status === "active"}
              onCheckedChange={(checked) =>
                patch.mutate({ id: trigger.triggerId, status: checked ? "active" : "inactive" })
              }
              aria-label="Active"
            />
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Version {trigger.workflowVersionId}
            {trigger.publicId ? (
              <p className="mt-1 font-mono">/hooks/v1/{trigger.publicId}/&lt;secret&gt;</p>
            ) : null}
            {trigger.secret ? <p className="mt-1 font-mono">Secret (once): {trigger.secret}</p> : null}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
