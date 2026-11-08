import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { approvalApi, executionApi, taskApi } from "@/api/resources"
import { getAccessToken } from "@/api/client"
import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Textarea } from "@/components/ui/textarea"
import { applyEvent, initialProjection, parseSseBlock, type SseProjection } from "./sseClient"

type RunPanelProps = {
  projectId: string
  runId: string | null
}

export const RunPanel = ({ projectId, runId }: RunPanelProps) => {
  const detail = useQuery({
    queryKey: ["run", projectId, runId],
    queryFn: () => executionApi.get(projectId, runId ?? ""),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ["SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(status) ? false : 1500
    },
  })
  const [sse, setSse] = useState<SseProjection>(initialProjection())
  const lastIdRef = useRef<string | null>(null)
  const [payload, setPayload] = useState("{}")
  const approvals = useQuery({
    queryKey: ["approvals", projectId],
    queryFn: () => approvalApi.list(projectId),
    enabled: detail.data?.waitingReason === "HUMAN",
  })
  const tasks = useQuery({
    queryKey: ["run-tasks", projectId, runId],
    queryFn: () => taskApi.listForRun(projectId, runId ?? ""),
    enabled: Boolean(runId),
  })

  useEffect(() => {
    if (!runId) {
      return
    }
    let cancelled = false
    const connect = async () => {
      setSse((s) => ({ ...s, connection: "reconnecting" }))
      try {
        const response = await fetch(`/api/v1/projects/${projectId}/executions/${runId}/events`, {
          headers: {
            Authorization: `Bearer ${getAccessToken() ?? ""}`,
            ...(lastIdRef.current ? { "Last-Event-ID": lastIdRef.current } : {}),
          },
          credentials: "include",
        })
        if (!response.ok || !response.body || cancelled) {
          if (!cancelled) setSse((s) => ({ ...s, connection: "offline" }))
          return
        }
        setSse((s) => ({ ...s, connection: "connected" }))
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""
        while (!cancelled) {
          const { done, value } = await reader.read()
          if (done) {
            break
          }
          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split("\n\n")
          buffer = parts.pop() ?? ""
          parts.forEach((block) => {
            const event = parseSseBlock(block)
            if (event) {
              setSse((state) => {
                const next = applyEvent(state, event)
                lastIdRef.current = next.lastId
                if (next.connection === "ended") {
                  void detail.refetch()
                }
                return next
              })
            }
          })
        }
      } catch {
        if (!cancelled) {
          setSse((s) => ({ ...s, connection: "offline" }))
        }
      }
    }
    void connect()
    return () => {
      cancelled = true
    }
  }, [projectId, runId])

  const cancel = useMutation({
    mutationFn: () => executionApi.cancel(projectId, runId ?? ""),
    onSuccess: () => toast.success("Cancel requested"),
  })

  const decide = useMutation({
    mutationFn: (decision: string) => {
      const approval = approvals.data?.find((item) => item.runId === runId)
      if (!approval) {
        throw new Error("No approval")
      }
      return approvalApi.decide(projectId, runId ?? "", approval.approvalId, decision, JSON.parse(payload))
    },
    onSuccess: () => toast.success("Decision submitted"),
  })

  if (!runId) {
    return <p className="p-3 text-xs text-muted-foreground">Start a run to inspect live events.</p>
  }

  return (
    <div className="flex h-full flex-col p-2">
      <div className="mb-2 flex items-center gap-2">
        {detail.data ? <StatusBadge status={detail.data.status} waitingReason={detail.data.waitingReason} /> : null}
        <BadgeChip label={sse.connection} />
        <Button size="sm" variant="outline" onClick={() => cancel.mutate()}>
          Cancel
        </Button>
      </div>
      {detail.data?.waitingReason === "HUMAN" ? (
        <div className="mb-2 flex flex-col gap-1 rounded-md border p-2">
          <p className="text-xs font-medium">Pending approval</p>
          <Textarea value={payload} onChange={(e) => setPayload(e.target.value)} />
          <div className="flex gap-1">
            <Button size="sm" onClick={() => decide.mutate("APPROVE")}>
              Approve
            </Button>
            <Button size="sm" variant="destructive" onClick={() => decide.mutate("REJECT")}>
              Reject
            </Button>
          </div>
        </div>
      ) : null}
      {detail.data?.waitingReason === "TASK" && tasks.data?.[0] ? (
        <Link className="mb-2 text-xs underline" to={`/projects/${projectId}/tasks/${tasks.data[0].taskId}`}>
          Open task progress
        </Link>
      ) : null}
      <ScrollArea className="flex-1">
        <ol className="flex flex-col gap-1 text-xs">
          {sse.events.map((event) => (
            <li key={event.id} className="font-mono">
              {event.sequence} {event.type}
            </li>
          ))}
        </ol>
      </ScrollArea>
    </div>
  )
}

const BadgeChip = ({ label }: { label: string }) => {
  return <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] uppercase">{label}</span>
}
