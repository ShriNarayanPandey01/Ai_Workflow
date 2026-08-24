import { Link, useParams } from "react-router-dom"
import { useMutation, useQueries, useQuery } from "@tanstack/react-query"
import { executionApi, taskApi } from "@/api/resources"
import { EmptyState } from "@/components/EmptyState"
import { PageHeader } from "@/components/PageHeader"
import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"

export const TasksPage = () => {
  const { projectId = "" } = useParams()
  const runs = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => executionApi.list(projectId),
    enabled: Boolean(projectId),
  })
  const taskQueries = useQueries({
    queries: (runs.data?.items ?? []).slice(0, 10).map((run) => ({
      queryKey: ["run-tasks", projectId, run.runId],
      queryFn: () => taskApi.listForRun(projectId, run.runId),
      enabled: Boolean(projectId),
    })),
  })
  const tasks = taskQueries.flatMap((q) => q.data ?? [])

  if (!projectId) {
    return <p className="text-sm">Select a project</p>
  }

  return (
    <div>
      <PageHeader title="Tasks" />
      {tasks.length === 0 ? (
        <EmptyState title="No durable tasks" description="Heavy nodes publish task progress here." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Progress</TableHead>
              <TableHead>Run</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tasks.map((task) => (
              <TableRow key={task.taskId}>
                <TableCell>
                  <Link className="underline" to={`/projects/${projectId}/tasks/${task.taskId}`}>
                    {task.taskType}
                  </Link>
                </TableCell>
                <TableCell>
                  <StatusBadge status={task.status} />
                </TableCell>
                <TableCell>{task.percent}%</TableCell>
                <TableCell className="font-mono text-xs">{task.runId.slice(0, 8)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

export const TaskDetailPage = () => {
  const { projectId = "", taskId = "" } = useParams()
  const detail = useQuery({
    queryKey: ["task", projectId, taskId],
    queryFn: () => taskApi.get(projectId, taskId),
    refetchInterval: 2000,
  })
  const items = useQuery({
    queryKey: ["task-items", projectId, taskId],
    queryFn: () => taskApi.items(projectId, taskId),
  })
  const cancel = useMutation({
    mutationFn: () => taskApi.cancel(projectId, taskId),
  })
  const usage = detail.data?.usage
  const artifactId =
    usage && typeof usage === "object" && usage !== null && "artifactId" in usage
      ? String((usage as { artifactId: string }).artifactId)
      : null
  const download = useMutation({
    mutationFn: async () => {
      if (!artifactId) {
        throw new Error("No artifact")
      }
      const result = await taskApi.download(projectId, artifactId)
      window.open(result.downloadUrl, "_blank")
    },
  })

  return (
    <div>
      <PageHeader title={detail.data?.taskType ?? "Task"} description={taskId}>
        <Button variant="outline" onClick={() => cancel.mutate()}>
          Cancel
        </Button>
        {artifactId ? (
          <Button variant="secondary" onClick={() => download.mutate()}>
            Download artifact
          </Button>
        ) : null}
      </PageHeader>
      {detail.data?.taskType?.includes("momentum") ? (
        <p className="mb-3 rounded-md border p-2 text-xs">Informational ranking only — not personalized financial advice.</p>
      ) : null}
      <div className="mb-4">
        <Progress value={Number(detail.data?.percent ?? 0)} />
        <p className="mt-1 text-xs text-muted-foreground">
          {detail.data?.stage} · {detail.data?.completedItems}/{detail.data?.totalItems}
        </p>
      </div>
      {detail.data?.runId ? (
        <Link className="text-xs underline" to={`/projects/${projectId}/runs/${detail.data.runId}`}>
          Parent run
        </Link>
      ) : null}
      <Table className="mt-4">
        <TableHeader>
          <TableRow>
            <TableHead>Item</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.data?.items.map((item) => (
            <TableRow key={item.itemId}>
              <TableCell className="font-mono text-xs">{item.itemKey}</TableCell>
              <TableCell>
                <StatusBadge status={item.status} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="mt-4 text-sm font-medium">Usage / warnings</p>
      <Textarea readOnly className="mt-1 min-h-40" value={JSON.stringify({ usage: detail.data?.usage, warnings: detail.data?.warnings }, null, 2)} />
    </div>
  )
}
