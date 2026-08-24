import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { projectApi } from "@/api/resources"
import { EmptyState } from "@/components/EmptyState"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"

export const ProjectsPage = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ["projects"], queryFn: projectApi.list })
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const create = useMutation({
    mutationFn: () => projectApi.create(name, description),
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] })
      setOpen(false)
      navigate(`/projects/${project.projectId}/workflows`)
    },
  })

  return (
    <div>
      <PageHeader title="Projects" actionLabel="New project" onAction={() => setOpen(true)} />
      {query.isLoading ? <Skeleton className="h-24 w-full" /> : null}
      {query.data?.items.length === 0 ? (
        <EmptyState
          title="No projects yet"
          description="Create a project to start authoring workflows."
          actionLabel="New project"
          onAction={() => setOpen(true)}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.items.map((project) => (
              <TableRow
                key={project.projectId}
                tabIndex={0}
                className="cursor-pointer"
                onClick={() => navigate(`/projects/${project.projectId}/workflows`)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    navigate(`/projects/${project.projectId}/workflows`)
                  }
                }}
              >
                <TableCell>{project.name}</TableCell>
                <TableCell className="text-muted-foreground">{new Date(project.updatedAt).toLocaleString()}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
            <Label htmlFor="desc">Description</Label>
            <Input id="desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <DialogFooter>
            <Button onClick={() => create.mutate()} disabled={!name}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
