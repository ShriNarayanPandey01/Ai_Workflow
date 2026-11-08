import type { CSSProperties } from "react"
import type { RunStatus } from "@/api/types"
import { cn } from "@/lib/utils"

const STATUS_CLASS: Record<RunStatus, string> = {
  QUEUED: "border-transparent bg-muted text-muted-foreground",
  RUNNING: "border-transparent text-white",
  WAITING: "border-transparent text-white",
  SUCCEEDED: "border-transparent text-white",
  FAILED: "border-transparent text-white",
  CANCELLING: "border-transparent text-white",
  CANCELLED: "border-transparent bg-muted text-muted-foreground",
  TIMED_OUT: "border-transparent text-white",
}

const STATUS_STYLE: Partial<Record<RunStatus, CSSProperties>> = {
  RUNNING: { backgroundColor: "var(--status-running)" },
  WAITING: { backgroundColor: "var(--status-waiting)" },
  SUCCEEDED: { backgroundColor: "var(--status-succeeded)" },
  FAILED: { backgroundColor: "var(--status-failed)" },
  TIMED_OUT: { backgroundColor: "var(--status-failed)" },
  CANCELLING: { backgroundColor: "var(--status-cancelling)" },
}

type StatusBadgeProps = {
  status: string
  waitingReason?: string | null
  className?: string
}

export const StatusBadge = ({ status, waitingReason, className }: StatusBadgeProps) => {
  const key = status as RunStatus
  const label = waitingReason ? `${status} · ${waitingReason}` : status
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-1.5 py-0 text-[11px] font-medium",
        STATUS_CLASS[key] ?? "border bg-background",
        status === "RUNNING" && "animate-pulse",
        className,
      )}
      style={STATUS_STYLE[key]}
    >
      {label}
    </span>
  )
}

export const CATEGORY_COLOR: Record<string, string> = {
  data: "var(--node-data)",
  control: "var(--node-control)",
  ai: "var(--node-ai)",
  rag: "var(--node-rag)",
  human: "var(--node-human)",
  action: "var(--node-action)",
  market: "var(--node-market)",
  research: "var(--node-research)",
}

export const categoryColor = (token?: string) => CATEGORY_COLOR[token ?? ""] ?? "var(--node-data)"
