import { isApiError } from "@/api/problem"
import { Badge } from "@/components/ui/badge"

export const ProblemAlert = ({ error }: { error: unknown }) => {
  if (!error) {
    return null
  }
  if (!isApiError(error)) {
    return <p className="text-xs text-destructive">{error instanceof Error ? error.message : "Something went wrong"}</p>
  }
  return (
    <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3">
      <p className="text-sm font-medium">{error.problem.title}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {error.problem.code}
        {error.problem.correlationId ? (
          <Badge variant="outline" className="ml-2 font-mono">
            {error.problem.correlationId}
          </Badge>
        ) : null}
      </p>
      {error.problem.errors?.length ? (
        <ul className="mt-2 flex flex-col gap-1 text-xs">
          {error.problem.errors.map((item) => (
            <li key={`${item.code}-${item.path}-${item.message}`}>{item.message}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
