# Shared Contracts

Canonical formats live in [`contracts/`](../contracts/). Services must not invent parallel shapes.

## Families

| Family | Path | Used by |
| --- | --- | --- |
| Workflow definition | `contracts/workflow/definition.schema.json` | Drafts, versions, execution snapshots |
| Condition AST | `contracts/workflow/condition.schema.json` | Edges, loop exits |
| Node manifests | `contracts/nodes/manifest.schema.json` + `catalog/` | Catalog, validation, registry, default bindings |
| Workflow wiring | [05-workflow-wiring.md](./05-workflow-wiring.md) | Edges (structure), `input_bindings` (field mapping) |
| Message envelope | `contracts/messages/envelope.schema.json` | All RabbitMQ traffic |
| Command payloads | `contracts/messages/commands/` | Control → workers |
| Event payloads | `contracts/messages/events/` | Workers → control |
| Fixtures | `contracts/fixtures/{valid,invalid}/` | Cross-language CI |

## Casing rule

| Surface | Casing |
| --- | --- |
| Contracts, broker, stored definitions | `snake_case` |
| Public HTTP `/api/v1` | `camelCase` |

Control plane maps HTTP DTOs ↔ snake_case storage/broker. Execution plane only sees snake_case.

## Identifiers

- Resource IDs: UUID strings.
- Node type: `namespace.name@majorVersion` (e.g. `ai.chat-model@1`).
- Message type: dotted name (e.g. `execution.start`).
- Routing key: message type + `.v1` (e.g. `execution.start.v1`).
- `schema_version: "1.0"` required on definitions and envelopes.

## What schema covers vs semantic validation

JSON Schema enforces shape. Both Java and Python must also enforce:

- Unique node/edge IDs
- Port existence, direction, cardinality, compatibility
- Input bindings: required fields bound, reachable sources, path/type compatibility (see [05-workflow-wiring.md](./05-workflow-wiring.md))
- Pass-through inference when `input_bindings` is omitted (edge `source_port` → `target_port` at `/`)
- Reachability and single start entry
- Loop ownership of cycles (Tarjan SCC); reject arbitrary cycles
- Loop bounds vs platform caps
- Credential/dataset ownership at publish time
- Condition path allowlists and nesting depth

Invalid fixtures include `*.meta.json` describing expected failure class.

## Developer checklist when changing a contract

1. Update the JSON Schema.
2. Add/adjust valid and invalid fixtures.
3. Update Java validators/DTOs and Python Pydantic models.
4. Run fixture suites in both languages.
5. Bump major version if breaking; minor only for additive optional fields (with ADR).
6. Never silently coerce major versions.

## Envelope essentials

Every message includes: `message_id`, `message_type`, `schema_version`, `occurred_at`, `correlation_id`, `causation_id`, `idempotency_key`, `tenant`, `subject`, `sequence` (events only; commands must be `null`), `payload`.

Terminal success event type is **`execution.completed`** with payload status `SUCCEEDED`. Do not invent `execution.succeeded` on the wire.

## Workflow wiring (hybrid)

- **Edges + ports** — graph structure and control-flow branches (`true`/`false`, `body`/`done`).
- **`input_bindings`** — optional per-node field mappings (`target_port` + path ← `source_node` + port + path).
- **`default_bindings`** — optional catalog hints for editor auto-fill (e.g. Chat Model `prompt.text` ← upstream `text.text`).
- **MVP compatibility** — graphs without `input_bindings` infer whole-port pass-through from edges.

Full spec: [05-workflow-wiring.md](./05-workflow-wiring.md).

## Related

- [`contracts/README.md`](../contracts/README.md)
- [03-messaging.md](./03-messaging.md)
