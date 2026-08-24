import * as React from "react"
import { cn } from "@/lib/utils"

export const Table = ({ className, ...props }: React.ComponentProps<"table">) => {
  return (
    <div className="w-full overflow-auto">
      <table className={cn("w-full caption-bottom text-sm", className)} {...props} />
    </div>
  )
}

export const TableHeader = ({ className, ...props }: React.ComponentProps<"thead">) => {
  return <thead className={cn("[&_tr]:border-b", className)} {...props} />
}

export const TableBody = ({ className, ...props }: React.ComponentProps<"tbody">) => {
  return <tbody className={cn("[&_tr:last-child]:border-0", className)} {...props} />
}

export const TableRow = ({ className, ...props }: React.ComponentProps<"tr">) => {
  return (
    <tr
      className={cn("h-10 border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted", className)}
      {...props}
    />
  )
}

export const TableHead = ({ className, ...props }: React.ComponentProps<"th">) => {
  return (
    <th className={cn("px-3 text-left text-xs font-medium text-muted-foreground", className)} {...props} />
  )
}

export const TableCell = ({ className, ...props }: React.ComponentProps<"td">) => {
  return <td className={cn("px-3 align-middle", className)} {...props} />
}
