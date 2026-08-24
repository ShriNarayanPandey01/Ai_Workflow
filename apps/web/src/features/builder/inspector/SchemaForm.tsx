import type { JsonValue } from "@/api/types"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"

type JsonSchema = Record<string, JsonValue>

type SchemaFormProps = {
  schema: JsonSchema
  value: Record<string, JsonValue>
  onChange: (value: Record<string, JsonValue>) => void
}

export const SchemaForm = ({ schema, value, onChange }: SchemaFormProps) => {
  const properties = (schema.properties as Record<string, JsonSchema> | undefined) ?? {}
  const required = (schema.required as string[] | undefined) ?? []

  const handleChange = (key: string, next: JsonValue) => {
    onChange({ ...value, [key]: next })
  }

  return (
    <div className="flex flex-col gap-3">
      {Object.entries(properties).map(([key, field]) => {
        const fieldType = field.type
        const enums = field.enum as string[] | undefined
        const label = `${key}${required.includes(key) ? " *" : ""}`
        if (enums?.length) {
          return (
            <div key={key} className="flex flex-col gap-1">
              <Label htmlFor={key}>{label}</Label>
              <Select value={String(value[key] ?? "")} onValueChange={(v) => handleChange(key, v)}>
                <SelectTrigger id={key} aria-label={key}>
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {enums.map((option) => (
                      <SelectItem key={option} value={option}>
                        {option}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
          )
        }
        if (fieldType === "boolean") {
          return (
            <div key={key} className="flex items-center justify-between gap-2">
              <Label htmlFor={key}>{label}</Label>
              <Switch
                id={key}
                checked={Boolean(value[key])}
                onCheckedChange={(checked) => handleChange(key, checked)}
              />
            </div>
          )
        }
        if (fieldType === "integer" || fieldType === "number") {
          return (
            <div key={key} className="flex flex-col gap-1">
              <Label htmlFor={key}>{label}</Label>
              <Input
                id={key}
                type="number"
                value={value[key] === undefined || value[key] === null ? "" : String(value[key])}
                onChange={(event) => handleChange(key, event.target.value === "" ? null : Number(event.target.value))}
              />
            </div>
          )
        }
        if (fieldType === "object") {
          return (
            <div key={key} className="flex flex-col gap-1">
              <Label htmlFor={key}>{label}</Label>
              <Textarea
                id={key}
                value={JSON.stringify(value[key] ?? {}, null, 2)}
                onChange={(event) => {
                  try {
                    handleChange(key, JSON.parse(event.target.value) as JsonValue)
                  } catch {
                    /* keep typing */
                  }
                }}
              />
            </div>
          )
        }
        return (
          <div key={key} className="flex flex-col gap-1">
            <Label htmlFor={key}>{label}</Label>
            <Input
              id={key}
              value={value[key] === undefined || value[key] === null ? "" : String(value[key])}
              onChange={(event) => handleChange(key, event.target.value)}
            />
          </div>
        )
      })}
    </div>
  )
}
