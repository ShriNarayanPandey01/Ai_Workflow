# Shared Contracts

Canonical cross-language contracts for the AI Workflow Platform.

JSON Schema is the source of truth. TypeScript types, Java DTOs, and Pydantic
models must be generated from or validated against these schemas. Do not invent
parallel shapes in application code.

## Layout

```text
contracts/
|-- README.md                          # this file
|-- workflow/
|   |-- definition.schema.json         # workflow graph definition
|   `-- condition.schema.json          # structured condition AST
|-- nodes/
|   |-- manifest.schema.json           # node type manifest
|   `-- catalog/                       # versioned node manifests for the current MVP catalog
|-- messages/
|   |-- envelope.schema.json           # shared RabbitMQ envelope
|   |-- commands/                      # command payload schemas
|   `-- events/                        # event payload schemas
`-- fixtures/
    |-- valid/                         # must accept in all languages
    `-- invalid/                       # must reject in all languages
```

## Naming conventions

| Surface | Casing | Example |
| --- | --- | --- |
| **Canonical contracts** (this directory, broker messages, stored definitions) | `snake_case` | `workflow_id`, `source_node_id` |
| **Public HTTP API** (`/api/v1`) | `camelCase` | `workflowId`, `sourceNodeId` |

Control-plane HTTP handlers map between camelCase request/response DTOs and the
snake_case canonical definition stored in drafts/versions and published on the
broker. The execution plane validates only the snake_case forms.

## Identifiers

- All resource IDs are **UUID strings** (`format: uuid`).
- Node instance IDs and edge IDs inside a definition are UUID strings and must
  be unique within that graph.
- Node **types** use `namespace.name@majorVersion` (for example `data.input@1`).
- Message types use dotted names (for example `execution.start`).
- Routing keys for the MVP are the message type plus a major version suffix
  (for example `execution.start.v1`). The envelope still carries
  `schema_version` for payload evolution.

## Versioning

- `schema_version: "1.0"` is required on workflow definitions and message envelopes.
- Major version bumps are not silently coerced.
- Additive optional fields may appear in a minor schema version after an ADR.
- Unknown top-level properties are rejected for major version `1.x`
  (`additionalProperties: false`).

## Broker topology (reference)

| Exchange | Purpose |
| --- | --- |
| `aiw.commands.v1` | Commands from control plane to execution plane |
| `aiw.events.v1` | Events from execution plane to control plane |
| `aiw.dead.v1` | Dead-letter routing |

Command routing keys (MVP):

- `execution.start.v1`
- `execution.cancel.v1`
- `execution.resume.v1`
- `document.ingest.v1`
- `document.delete.v1`
- `task.start.v1`
- `task.cancel.v1`

Event routing keys (MVP):

- `execution.queued.v1` / `execution.started.v1` / `execution.waiting.v1`
- `execution.completed.v1` / `execution.failed.v1` / `execution.cancelled.v1`
- `node.started.v1` / `node.completed.v1` / `node.failed.v1`
- `document.ingestion.started.v1` / `completed.v1` / `failed.v1`
- `task.progress.v1` / `task.item.completed.v1` / `task.completed.v1` / `task.failed.v1`

## What JSON Schema does and does not cover

JSON Schema enforces **shape**: required fields, types, enums, formats, basic
bounds, envelope message discrimination, and scope-specific message subjects.

The following require **semantic validators** in Java and Python (and shared
fixtures document expected outcomes):

- Unique node/edge IDs inside a graph
- Port existence, direction, cardinality, and schema compatibility
- Reachability, single start entry, and output reachability
- Strongly connected components / Loop ownership (no arbitrary cycles)
- Bounded loop configuration vs platform caps
- Workflow-version equality between envelope subject and embedded published definition
- Credential and dataset ownership at publication time
- Condition path allowlists and nesting depth beyond the schema default

## Fixture policy

Every language must run the same fixtures in CI:

| Fixture class | Expectation |
| --- | --- |
| `fixtures/valid/*` | Parse and schema-validate successfully |
| `fixtures/invalid/*` | Fail schema validation **or** semantic validation with a stable error code |

Invalid fixtures include a sibling `*.meta.json` describing the expected failure
class when rejection is semantic rather than pure JSON Schema.

## Code generation (recommended)

Pin generators in each service; reject uncommitted drift in CI.

| Language | Suggested approach |
| --- | --- |
| TypeScript | `json-schema-to-typescript` or equivalent into `apps/web/src/api/generated/` |
| Java | networknt/json-schema-validator at runtime; optional POJO generation |
| Python | Pydantic models hand-maintained or `datamodel-code-generator`, always validated against fixtures |

## Related documents

- System plan: [`docs/plan.md`](../docs/plan.md)
- LLD contracts: [`docs/LLD.md`](../docs/LLD.md) section 4
- Contract data flow: [`docs/contracts-data-flow.md`](../docs/contracts-data-flow.md)
- Broker examples: [`docs/control_plane/EXECUTION-PLANE-API.md`](../docs/control_plane/EXECUTION-PLANE-API.md)
