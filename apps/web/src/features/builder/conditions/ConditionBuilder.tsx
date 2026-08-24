import type { ConditionExpression, Operand } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const COMPARE_OPS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "startsWith", "endsWith"] as const

type ConditionBuilderProps = {
  value: ConditionExpression | null | undefined
  onChange: (value: ConditionExpression | null) => void
}

const defaultCompare = (): ConditionExpression => ({
  op: "eq",
  left: { kind: "path", value: "/input" },
  right: { kind: "literal", value: "" },
})

export const ConditionBuilder = ({ value, onChange }: ConditionBuilderProps) => {
  const current = value ?? defaultCompare()

  const handleOp = (op: string) => {
    if (op === "all" || op === "any") {
      onChange({ op, args: [defaultCompare()] })
      return
    }
    if (op === "not") {
      onChange({ op: "not", arg: defaultCompare() })
      return
    }
    if (op === "exists" || op === "isNull") {
      onChange({ op, value: { kind: "path", value: "/input" } })
      return
    }
    onChange({
      op: op as (typeof COMPARE_OPS)[number],
      left: { kind: "path", value: "/input" },
      right: { kind: "literal", value: "" },
    })
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border p-2">
      <div className="flex items-center gap-2">
        <Label>Operator</Label>
        <Select value={current.op} onValueChange={handleOp}>
          <SelectTrigger aria-label="Condition operator">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {["all", "any", "not", ...COMPARE_OPS, "exists", "isNull"].map((op) => (
                <SelectItem key={op} value={op}>
                  {op}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button size="sm" variant="ghost" onClick={() => onChange(null)}>
          Clear
        </Button>
      </div>
      {"args" in current
        ? current.args.map((arg, index) => (
            <ConditionBuilder
              key={index}
              value={arg}
              onChange={(next) => {
                const args = [...current.args]
                if (next) {
                  args[index] = next
                } else {
                  args.splice(index, 1)
                }
                onChange({ ...current, args })
              }}
            />
          ))
        : null}
      {"args" in current ? (
        <Button size="sm" variant="outline" onClick={() => onChange({ ...current, args: [...current.args, defaultCompare()] })}>
          Add clause
        </Button>
      ) : null}
      {"arg" in current ? <ConditionBuilder value={current.arg} onChange={(next) => next && onChange({ op: "not", arg: next })} /> : null}
      {"left" in current ? (
        <div className="grid grid-cols-2 gap-2">
          <OperandEditor label="Left" value={current.left} onChange={(left) => onChange({ ...current, left })} />
          <OperandEditor label="Right" value={current.right} onChange={(right) => onChange({ ...current, right })} />
        </div>
      ) : null}
      {"value" in current && !("left" in current) ? (
        <OperandEditor
          label="Path"
          value={current.value}
          onChange={(operand) => onChange({ ...current, value: operand })}
        />
      ) : null}
    </div>
  )
}

const OperandEditor = ({
  label,
  value,
  onChange,
}: {
  label: string
  value: Operand
  onChange: (value: Operand) => void
}) => {
  return (
    <div className="flex flex-col gap-1">
      <Label>{label}</Label>
      <Select
        value={value.kind}
        onValueChange={(kind) =>
          onChange(kind === "path" ? { kind: "path", value: "/" } : { kind: "literal", value: "" })
        }
      >
        <SelectTrigger aria-label={`${label} operand kind`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="path">Path</SelectItem>
            <SelectItem value="literal">Literal</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
      <Input
        className="font-mono"
        value={value.kind === "path" ? value.value : String(value.value ?? "")}
        onChange={(event) =>
          onChange(
            value.kind === "path"
              ? { kind: "path", value: event.target.value }
              : { kind: "literal", value: event.target.value },
          )
        }
      />
    </div>
  )
}
