import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { datasetApi } from "@/api/resources"
import { EmptyState } from "@/components/EmptyState"
import { PageHeader } from "@/components/PageHeader"
import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useState } from "react"

const sha256Hex = async (buffer: ArrayBuffer) => {
  const hash = await crypto.subtle.digest("SHA-256", buffer)
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("")
}

export const DatasetsPage = () => {
  const { projectId = "" } = useParams()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => datasetApi.list(projectId),
    enabled: Boolean(projectId),
  })
  const [name, setName] = useState("")
  const create = useMutation({
    mutationFn: () => datasetApi.create(projectId, name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["datasets", projectId] })
      setName("")
    },
  })

  if (!projectId) {
    return <p className="text-sm">Select a project</p>
  }

  return (
    <div>
      <PageHeader title="Datasets" />
      <div className="mb-4 flex gap-2">
        <Input placeholder="Dataset name" value={name} onChange={(e) => setName(e.target.value)} />
        <Button disabled={!name} onClick={() => create.mutate()}>
          Create
        </Button>
      </div>
      {query.data?.length === 0 ? (
        <EmptyState title="No datasets" description="Create a dataset, then upload documents for RAG." />
      ) : (
        <div className="flex flex-col gap-4">
          {query.data?.map((dataset) => (
            <DatasetCard key={dataset.datasetId} projectId={projectId} datasetId={dataset.datasetId} name={dataset.name} />
          ))}
        </div>
      )}
    </div>
  )
}

const DatasetCard = ({
  projectId,
  datasetId,
  name,
}: {
  projectId: string
  datasetId: string
  name: string
}) => {
  const queryClient = useQueryClient()
  const docs = useQuery({
    queryKey: ["documents", projectId, datasetId],
    queryFn: () => datasetApi.documents(projectId, datasetId),
    refetchInterval: 4000,
  })
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const intent = await datasetApi.uploadIntent(projectId, datasetId, file.name, file.type || "application/octet-stream", file.size)
      await fetch(intent.uploadUrl, {
        method: "PUT",
        body: file,
        headers: intent.headers,
      })
      const hash = await sha256Hex(await file.arrayBuffer())
      return datasetApi.confirm(projectId, datasetId, intent.documentId, hash)
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["documents", projectId, datasetId] }),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>{name}</CardTitle>
      </CardHeader>
      <CardContent>
        <label className="mb-3 flex cursor-pointer items-center justify-center rounded-md border border-dashed p-4 text-xs">
          Drop or choose a file
          <input
            type="file"
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) {
                upload.mutate(file)
              }
            }}
          />
        </label>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Size</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {docs.data?.map((doc) => (
              <TableRow key={doc.documentId}>
                <TableCell>{doc.originalName}</TableCell>
                <TableCell>
                  <StatusBadge status={doc.status.toUpperCase()} />
                </TableCell>
                <TableCell>{doc.sizeBytes}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
