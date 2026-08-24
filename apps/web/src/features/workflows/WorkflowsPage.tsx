import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { workflowApi } from "@/api/resources"
import { EmptyState } from "@/components/EmptyState"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export const WorkflowsPage = () => {
  const { projectId = "" } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["workflows", projectId],
    queryFn: () => workflowApi.list(projectId),
    enabled: Boolean(projectId),
  })
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const create = useMutation({
    mutationFn: () => workflowApi.create(projectId, name),
    onSuccess: (workflow) => {
      void queryClient.invalidateQueries({ queryKey: ["workflows", projectId] })
      setOpen(false)
      navigate(`/projects/${projectId}/workflows/${workflow.workflowId}`)
    },
  })

  if (!projectId) {
    return <p className="text-sm">Select a project</p>
  }

  return (
    <div>
      <PageHeader title="Workflows" actionLabel="New workflow" onAction={() => setOpen(true)} />
      {query.data?.items.length === 0 ? (
        <EmptyState
          title="No workflows"
          description="Create a workflow to open the builder."
          actionLabel="New workflow"
          onAction={() => setOpen(true)}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Published</TableHead>
              <TableHead>Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.items.map((workflow) => (
              <TableRow
                key={workflow.workflowId}
                className="cursor-pointer"
                tabIndex={0}
                onClick={() => navigate(`/projects/${projectId}/workflows/${workflow.workflowId}`)}
              >
                <TableCell>{workflow.name}</TableCell>
                <TableCell>{workflow.latestVersion > 0 ? `v${workflow.latestVersion}` : "Draft"}</TableCell>
                <TableCell>{new Date(workflow.updatedAt).toLocaleString()}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New workflow</DialogTitle>
          </DialogHeader>
          <Label htmlFor="wf">Name</Label>
          <Input id="wf" value={name} onChange={(e) => setName(e.target.value)} />
          <DialogFooter>
            <Button disabled={!name} onClick={() => create.mutate()}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
