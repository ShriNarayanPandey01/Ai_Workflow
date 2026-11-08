import { Handle, Position, type Node, type NodeProps } from "@xyflow/react"
import {
  Activity,
  BookOpen,
  Box,
  Clipboard,
  Edit3,
  FileText,
  GitBranch,
  Globe,
  Inbox,
  LineChart,
  List,
  LogIn,
  LogOut,
  Merge,
  MessageSquare,
  Repeat,
  Search,
  Trash2,
  UserCheck,
  type LucideIcon,
} from "lucide-react"
import type { NodeManifest } from "@/api/types"
import { categoryColor } from "@/components/StatusBadge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const ICONS: Record<string, LucideIcon> = {
  "message-square": MessageSquare,
  "git-branch": GitBranch,
  repeat: Repeat,
  "user-check": UserCheck,
  "edit-3": Edit3,
  globe: Globe,
  "trash-2": Trash2,
  list: List,
  clipboard: Clipboard,
  "log-in": LogIn,
  "log-out": LogOut,
  merge: Merge,
  activity: Activity,
  inbox: Inbox,
  "line-chart": LineChart,
  search: Search,
  "book-open": BookOpen,
  "file-text": FileText,
}

export type ManifestNodeData = {
  label: string
  type: string
  status?: string
  invalid?: boolean
  manifest?: NodeManifest
}

const statusBadgeClass = (status: string) => {
  switch (status.toUpperCase()) {
    case "RUNNING":
      return "bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30 animate-pulse"
    case "SUCCEEDED":
    case "COMPLETED":
      return "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30"
    case "FAILED":
      return "bg-destructive/15 text-destructive border-destructive/30"
    case "WAITING":
      return "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30"
    default:
      return "bg-muted text-muted-foreground border-border"
  }
}

export const ManifestNode = ({ data, selected }: NodeProps<Node<ManifestNodeData>>) => {
  const Icon = ICONS[data.manifest?.ui.icon ?? ""] ?? Box
  const color = categoryColor(data.manifest?.ui.color_token)
  const inputs = data.manifest?.inputs ?? []
  const outputs = data.manifest?.outputs ?? []

  return (
    <div
      className={cn(
        "w-[190px] rounded-lg border bg-card shadow-sm transition-all",
        selected && "ring-2 ring-ring shadow-md",
        data.invalid && "border-destructive ring-2 ring-destructive/50",
      )}
      style={{ borderLeftWidth: 6, borderLeftColor: color }}
    >
      {inputs.map((port, index) => (
        <Tooltip key={port.name}>
          <TooltipTrigger asChild>
            <Handle
              id={port.name}
              type="target"
              position={Position.Left}
              style={{ top: 28 + index * 16 }}
              aria-label={`Input ${port.name}`}
            />
          </TooltipTrigger>
          <TooltipContent>
            {port.name} · {String(port.schema.type ?? "object")}
          </TooltipContent>
        </Tooltip>
      ))}
      <div className="flex items-center gap-2 px-3 py-2">
        <Icon className="size-3.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium">{data.label}</p>
          <p className="truncate font-mono text-[10px] text-muted-foreground">{data.type}</p>
        </div>
        {data.invalid && (
          <span className="size-2 shrink-0 rounded-full bg-destructive" title="Validation issue" />
        )}
      </div>
      {data.status ? (
        <div className="px-3 pb-2">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
              statusBadgeClass(data.status),
            )}
          >
            {data.status === "RUNNING" && <span className="size-1.5 rounded-full bg-blue-500 animate-ping" />}
            {data.status}
          </span>
        </div>
      ) : null}
      {outputs.map((port, index) => (
        <Tooltip key={port.name}>
          <TooltipTrigger asChild>
            <Handle
              id={port.name}
              type="source"
              position={Position.Right}
              style={{ top: 28 + index * 16 }}
              aria-label={`Output ${port.name}`}
            />
          </TooltipTrigger>
          <TooltipContent>
            {port.name} · {String(port.schema.type ?? "object")}
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  )
}
