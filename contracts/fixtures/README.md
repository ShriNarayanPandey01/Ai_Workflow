# Contract Fixtures

Shared accept/reject cases for TypeScript, Java, and Python validators.

## Valid (`valid/`)

| File | Schema under test |
| --- | --- |
| `workflow-linear.json` | `workflow/definition.schema.json` |
| `workflow-conditional.json` | `workflow/definition.schema.json` |
| `workflow-fan-out-fan-in.json` | `workflow/definition.schema.json` |
| `workflow-bounded-loop.json` | `workflow/definition.schema.json` |
| `condition-nested.json` | `workflow/condition.schema.json` |
| `manifest-chat-model.json` | `nodes/manifest.schema.json` |
| `envelope-execution-start.json` | `messages/envelope.schema.json` (+ start payload) |
| `envelope-execution-completed.json` | `messages/envelope.schema.json` (+ completed payload) |
| `envelope-document-ingest.json` | `messages/envelope.schema.json` (+ document ingest payload) |
| `envelope-task-progress.json` | `messages/envelope.schema.json` (+ task progress payload) |

These must parse and pass JSON Schema validation in every language. Semantic
graph checks must also pass for the workflow fixtures. Every file in
`nodes/catalog/` must also validate against `nodes/manifest.schema.json`.

## Invalid (`invalid/`)

Each fixture has a sibling `*.meta.json` describing expectations:

| Field | Meaning |
| --- | --- |
| `json_schema_valid` | Whether pure JSON Schema validation should succeed |
| `semantic_valid` | Whether graph/catalog semantic validation should succeed |
| `error_codes` | Stable codes the platform validators should emit (one or more) |

| File | Failure class |
| --- | --- |
| `workflow-missing-node-ref.json` | Semantic: unknown edge endpoint |
| `workflow-invalid-port.json` | Semantic: unknown port |
| `workflow-invalid-condition-op.json` | Schema: illegal condition operator |
| `workflow-arbitrary-cycle.json` | Semantic: cycle without Loop node |
| `workflow-unbounded-loop.json` | Semantic: loop missing `max_iterations` |
| `workflow-unsupported-node-version.json` | Semantic: unknown node type version |
| `workflow-unknown-top-level.json` | Schema: additional property |
| `envelope-missing-message-id.json` | Schema: required field |
| `envelope-invalid-message-type.json` | Schema: enum |
| `envelope-command-with-sequence.json` | Schema: commands cannot carry event sequence numbers |
| `envelope-document-subject-scope.json` | Schema: document messages use document scope only |
| `envelope-payload-type-mismatch.json` | Schema: message-type payload discriminator |
| `envelope-published-start-missing-version.json` | Schema: published starts require versioned definitions |

## CI expectation

1. Load every `valid/*` fixture against its schema -> pass.
2. Load every `invalid/*` fixture:
   - if `json_schema_valid: false` -> schema validator fails;
   - if `json_schema_valid: true` and `semantic_valid: false` -> schema passes, semantic validator fails with one of `error_codes`.
3. Load every `nodes/catalog/*.json` manifest against `nodes/manifest.schema.json` -> pass.
4. Fail the build on drift between languages.
