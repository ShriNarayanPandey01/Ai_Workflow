import type { ProblemError } from "@/api/types"
import { ScrollArea } from "@/components/ui/scroll-area"

type ValidationPanelProps = {
  errors: ProblemError[]
  onFocus: (nodeId?: string | null, edgeId?: string | null) => void
}

export const ValidationPanel = ({ errors, onFocus }: ValidationPanelProps) => {
  if (errors.length === 0) {
    return <p className="px-3 py-2 text-xs text-muted-foreground">No validation issues</p>
  }
  return (
    <ScrollArea className="h-full">
      <ul className="flex flex-col gap-1 p-2">
        {errors.map((error, index) => (
          <li key={`${error.code}-${index}`}>
            <button
              type="button"
              className="w-full rounded-md px-2 py-1 text-left text-xs hover:bg-accent"
              onClick={() => onFocus(error.nodeId, error.edgeId)}
            >
              <span className="font-medium">{error.code}</span>
              <span className="ml-2 text-muted-foreground">{error.message}</span>
            </button>
          </li>
        ))}
      </ul>
    </ScrollArea>
  )
}
