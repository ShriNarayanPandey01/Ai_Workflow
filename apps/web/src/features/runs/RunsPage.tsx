import { useNavigate, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { executionApi } from "@/api/resources"
import { PageHeader } from "@/components/PageHeader"
import { StatusBadge } from "@/components/StatusBadge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export const RunsPage = () => {
  const { projectId = "" } = useParams()
  const navigate = useNavigate()
  const query = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => executionApi.list(projectId),
    enabled: Boolean(projectId),
    refetchInterval: 4000,
  })

  if (!projectId) {
    return <p className="text-sm">Select a project</p>
  }

  return (
    <div>
      <PageHeader title="Runs" />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Started</TableHead>
            <TableHead>Workflow</TableHead>
            <TableHead>Mode</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {query.data?.items.map((run) => (
            <TableRow
              key={run.runId}
              className="cursor-pointer"
              tabIndex={0}
              onClick={() => navigate(`/projects/${projectId}/runs/${run.runId}`)}
            >
              <TableCell>{new Date(run.createdAt).toLocaleString()}</TableCell>
              <TableCell className="font-mono text-xs">{run.workflowId.slice(0, 8)}</TableCell>
              <TableCell>{run.mode}</TableCell>
              <TableCell>
                <StatusBadge status={run.status} waitingReason={run.waitingReason} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
