import { useMemo, useState } from "react"
import type { NodeManifest } from "@/api/types"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"

type NodePaletteProps = {
  catalog: NodeManifest[]
  onAdd: (type: string) => void
}

export const NodePalette = ({ catalog, onAdd }: NodePaletteProps) => {
  const [query, setQuery] = useState("")
  const grouped = useMemo(() => {
    const filtered = catalog.filter((item) => {
      const q = query.toLowerCase()
      return item.display_name.toLowerCase().includes(q) || item.type.toLowerCase().includes(q)
    })
    const map = new Map<string, NodeManifest[]>()
    filtered.forEach((item) => {
      const list = map.get(item.category) ?? []
      list.push(item)
      map.set(item.category, list)
    })
    return [...map.entries()]
  }, [catalog, query])

  return (
    <div className="flex h-full w-56 flex-col border-r bg-card">
      <div className="p-2">
        <Input
          placeholder="Search nodes"
          aria-label="Search nodes"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <ScrollArea className="flex-1">
        <Accordion type="multiple" defaultValue={grouped.map(([cat]) => cat)} className="px-2">
          {grouped.map(([category, items]) => (
            <AccordionItem key={category} value={category}>
              <AccordionTrigger className="capitalize">{category}</AccordionTrigger>
              <AccordionContent>
                <div className="flex flex-col gap-1">
                  {items.map((item) => (
                    <button
                      key={item.type}
                      type="button"
                      className="rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent"
                      draggable
                      onDragStart={(event) => {
                        event.dataTransfer.setData("application/aiw-node", item.type)
                      }}
                      onClick={() => onAdd(item.type)}
                    >
                      <span className="block font-medium">{item.display_name}</span>
                      <span className="block text-[10px] text-muted-foreground">{item.type}</span>
                    </button>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </ScrollArea>
    </div>
  )
}
