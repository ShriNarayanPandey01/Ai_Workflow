import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { approvalApi } from "@/api/resources"
import { EmptyState } from "@/components/EmptyState"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export const ApprovalsPage = () => {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ["approvals"], queryFn: () => approvalApi.list() })
  const decide = useMutation({
    mutationFn: (item: { projectId: string; runId: string; approvalId: string; decision: string }) =>
      approvalApi.decide(item.projectId, item.runId, item.approvalId, item.decision),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["approvals"] }),
  })
  const pending = query.data?.filter((item) => item.status === "PENDING") ?? []

  return (
    <div>
      <PageHeader title="Approvals" />
      {pending.length === 0 ? (
        <EmptyState title="No pending approvals" description="Human nodes will appear here when a run waits." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Run</TableHead>
              <TableHead>Node</TableHead>
              <TableHead>Requested</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {pending.map((item) => (
              <TableRow key={item.approvalId}>
                <TableCell>
                  <Link className="underline" to={`/projects/${item.projectId}/runs/${item.runId}`}>
                    {item.runId.slice(0, 8)}
                  </Link>
                </TableCell>
                <TableCell className="font-mono text-xs">{item.nodeId.slice(0, 8)}</TableCell>
                <TableCell>{new Date(item.createdAt).toLocaleString()}</TableCell>
                <TableCell className="flex gap-1">
                  <Button size="sm" onClick={() => decide.mutate({ ...item, decision: "APPROVE" })}>
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => decide.mutate({ ...item, decision: "REJECT" })}
                  >
                    Reject
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
