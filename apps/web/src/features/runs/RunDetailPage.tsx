import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { executionApi } from "@/api/resources"
import { PageHeader } from "@/components/PageHeader"
import { RunPanel } from "./RunPanel"
import { Textarea } from "@/components/ui/textarea"

export const RunDetailPage = () => {
  const { projectId = "", runId = "" } = useParams()
  const query = useQuery({
    queryKey: ["run", projectId, runId],
    queryFn: () => executionApi.get(projectId, runId),
    enabled: Boolean(projectId && runId),
  })

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div>
        <PageHeader title="Run inspector" description={runId} />
        <RunPanel projectId={projectId} runId={runId} />
      </div>
      <div>
        <p className="mb-2 text-sm font-medium">Output</p>
        <Textarea readOnly value={JSON.stringify(query.data?.output ?? query.data ?? {}, null, 2)} className="min-h-80" />
      </div>
    </div>
  )
}
