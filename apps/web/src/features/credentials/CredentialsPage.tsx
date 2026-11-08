import { useState } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { credentialApi } from "@/api/resources"
import { EmptyState } from "@/components/EmptyState"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const TYPES = ["openai_compatible", "market_data", "search", "http_header"]

export const CredentialsPage = () => {
  const { projectId = "" } = useParams()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["credentials", projectId],
    queryFn: () => credentialApi.list(projectId),
    enabled: Boolean(projectId),
  })
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [type, setType] = useState(TYPES[0])
  const [apiKey, setApiKey] = useState("")
  const create = useMutation({
    mutationFn: () => credentialApi.create(projectId, type, name, { apiKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["credentials", projectId] })
      setOpen(false)
      setApiKey("")
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => credentialApi.delete(projectId, id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["credentials", projectId] }),
  })

  if (!projectId) {
    return <p className="text-sm">Select a project</p>
  }

  return (
    <div>
      <PageHeader title="Credentials" actionLabel="New credential" onAction={() => setOpen(true)} />
      {query.data?.length === 0 ? (
        <EmptyState title="No credentials" description="Secrets are stored encrypted and shown masked." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Hint</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.map((item) => (
              <TableRow key={item.credentialId}>
                <TableCell>{item.name}</TableCell>
                <TableCell>{item.type}</TableCell>
                <TableCell className="font-mono text-xs">{item.maskedHint}</TableCell>
                <TableCell>
                  <Button size="sm" variant="destructive" onClick={() => remove.mutate(item.credentialId)}>
                    Delete
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>New credential</SheetTitle>
          </SheetHeader>
          <div className="mt-4 flex flex-col gap-3">
            <Label htmlFor="cname">Name</Label>
            <Input id="cname" value={name} onChange={(e) => setName(e.target.value)} />
            <Label>Type</Label>
            <Select value={type} onValueChange={setType}>
              <SelectTrigger aria-label="Credential type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {TYPES.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Label htmlFor="secret">API key</Label>
            <Input id="secret" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
            <Button onClick={() => create.mutate()} disabled={!name || !apiKey}>
              Save
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
