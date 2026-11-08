import * as React from "react"
import * as SheetPrimitive from "@radix-ui/react-dialog"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"

export const Sheet = SheetPrimitive.Root
export const SheetTrigger = SheetPrimitive.Trigger
export const SheetClose = SheetPrimitive.Close

export const SheetContent = ({
  className,
  children,
  side = "right",
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & { side?: "right" | "left" }) => {
  return (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay className="fixed inset-0 bg-black/40" />
      <SheetPrimitive.Content
        className={cn(
          "fixed top-0 z-50 flex h-full w-full max-w-md flex-col border bg-card p-4",
          side === "right" ? "right-0 border-l" : "left-0 border-r",
          className,
        )}
        {...props}
      >
        {children}
        <SheetPrimitive.Close className="absolute right-3 top-3" aria-label="Close panel">
          <X className="size-4" />
        </SheetPrimitive.Close>
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  )
}

export const SheetHeader = ({ className, ...props }: React.ComponentProps<"div">) => {
  return <div className={cn("mb-4 flex flex-col gap-1", className)} {...props} />
}

export const SheetTitle = ({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Title>) => {
  return <SheetPrimitive.Title className={cn("text-sm font-semibold", className)} {...props} />
}

export const SheetDescription = ({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Description>) => {
  return (
    <SheetPrimitive.Description className={cn("text-xs text-muted-foreground", className)} {...props} />
  )
}
