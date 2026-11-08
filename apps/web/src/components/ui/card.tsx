import * as React from "react"
import { cn } from "@/lib/utils"

export const Card = ({ className, ...props }: React.ComponentProps<"div">) => {
  return <div className={cn("rounded-lg border bg-card text-card-foreground", className)} {...props} />
}

export const CardHeader = ({ className, ...props }: React.ComponentProps<"div">) => {
  return <div className={cn("flex flex-col gap-1 p-4", className)} {...props} />
}

export const CardTitle = ({ className, ...props }: React.ComponentProps<"h3">) => {
  return <h3 className={cn("text-sm font-semibold", className)} {...props} />
}

export const CardDescription = ({ className, ...props }: React.ComponentProps<"p">) => {
  return <p className={cn("text-xs text-muted-foreground", className)} {...props} />
}

export const CardContent = ({ className, ...props }: React.ComponentProps<"div">) => {
  return <div className={cn("p-4 pt-0", className)} {...props} />
}

export const CardFooter = ({ className, ...props }: React.ComponentProps<"div">) => {
  return <div className={cn("flex items-center p-4 pt-0", className)} {...props} />
}
