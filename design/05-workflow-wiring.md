# Workflow Wiring — Hybrid Model

How data flows between nodes in a workflow graph.

**Decision:** Use a **hybrid** model — **ports + edges** for graph structure and control flow; **input bindings** for field-level data mapping; **catalog default bindings** for convenience.

When this doc and older prose disagree on wiring, **this doc wins** until `contracts/workflow/definition.schema.json` is updated to match.

## 1. Problem

Node manifests (catalog/registry) define what each node type **can** accept and produce. A workflow author must still decide **how** upstream output reaches downstream input — especially when:

- Form or review nodes emit variable object shapes.
- Only some fields from a large object are needed downstream.
- Common AI nodes (Prompt Template → Chat Model) should wire quickly with sensible defaults.

A pure port-to-port model (whole object passthrough only) is simple but weak for partial mapping. A pure field-mapping model without ports is awkward for Condition, Loop, and other branch ports.

## 2. Four layers

```text
┌──────────────────────────────────────────────────────────┐
│ 1. Catalog / registry                                    │
│    ports, port schemas, optional default_bindings        │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│ 2. Workflow edges                                        │
│    source_node + source_port → target_node + target_port │
│    structure, execution order, branches                  │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│ 3. Input bindings (on target node)                       │
│    target_port.target_path ← source_node.source_port.path│
│    origin: user | default | pass_through                 │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│ 4. Compiler / runtime                                    │
│    resolve bindings → build inputs dict → execute        │
└──────────────────────────────────────────────────────────┘
```

| Layer | Answers |
| --- | --- |
| **Ports** (catalog) | What named inputs/outputs exist and their JSON schemas |
| **Edges** | Which nodes are connected and in what execution order |
| **Bindings** | Which upstream field feeds which downstream field |
| **Defaults** (catalog) | Auto-suggested bindings when an edge is drawn |

**Rule:** Edges say *who talks to whom*. Bindings say *what data flows*.

## 3. Ports and port values

Each manifest port has a `name`, `direction`, `cardinality`, and `schema`. Port values are JSON objects (or primitives where the schema allows). Keys inside an object port are addressed with **JSON Pointer** paths (e.g. `/text`, `/email`, `/query`).

Control-flow nodes keep **named output ports** for routing — do not flatten them into a single key-value bag:

| Node | Ports used for structure |
| --- | --- |
| `control.condition@1` | `true`, `false` |
| `control.loop@1` | `body`, `done` |
| `control.for-each@1` | item / collection ports per manifest |

Bindings apply to **data ports** on ordinary nodes, not to replacing branch routing.

## 4. Workflow definition shape

### 4.1 Edges (unchanged role)

```json
{
  "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
  "source_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
  "source_port": "text",
  "target_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
  "target_port": "prompt",
  "label": null,
  "condition": null
}
```

Edges declare structural links. They do **not** carry field mappings.

### 4.2 Input bindings (on target node)

Optional array on each `workflowNode`:

```json
{
  "id": "chat-1",
  "type": "ai.chat-model@1",
  "config": { "model": "gpt-4" },
  "input_bindings": [
    {
      "target_port": "prompt",
      "target_path": "/text",
      "source_node_id": "prompt-1",
      "source_port": "text",
      "source_path": "/text",
      "origin": "default"
    }
  ]
}
```

| Field | Description |
| --- | --- |
| `target_port` | Input port name on this (target) node |
| `target_path` | JSON Pointer into the port value; `/` = entire port value |
| `source_node_id` | Upstream node instance UUID |
| `source_port` | Upstream output port name |
| `source_path` | JSON Pointer into upstream port value |
| `origin` | `user` (explicit), `default` (catalog auto), or `pass_through` (whole-port 1:1) |

### 4.3 Pass-through shorthand

Backward-compatible with existing fixtures that only use edges:

```json
{
  "target_port": "value",
  "target_path": "/",
  "source_node_id": "input-1",
  "source_port": "value",
  "source_path": "/",
  "origin": "pass_through"
}
```

When `input_bindings` is **omitted**, validators and the compiler **infer** pass-through bindings from edges: for each edge, map `source_port` at `/` → `target_port` at `/`.

### 4.4 Catalog default bindings

Optional per input port in node manifests:

```json
{
  "name": "prompt",
  "direction": "input",
  "schema": {
    "type": "object",
    "properties": { "text": { "type": "string" } }
  },
  "default_bindings": [
    {
      "target_path": "/text",
      "match": {
        "source_ports": ["text", "response"],
        "source_paths": ["/text", "/response/text"]
      }
    }
  ]
}
```

When the editor creates an edge into `prompt`, it may pre-fill a binding if exactly one upstream candidate matches. User overrides always win.

## 5. Binding resolution (compiler)

When node `N` runs:

1. Load `input_bindings` for `N` (or infer pass-through from incoming edges).
2. For each binding:
   - `value = node_outputs[source_node_id][source_port]`
   - `extracted = json_pointer_get(value, source_path)`
   - `json_pointer_set(inputs[target_port], target_path, extracted)`
3. Validate assembled `inputs` against registry Pydantic models.
4. Invoke `executor.execute(context, config, inputs)`.
5. Store outputs under `node_outputs[N.id][port]`.

Runtime state shape (unchanged):

```python
node_outputs: dict[str, dict[str, JsonValue]]  # node_id → port → value
```

Bindings read from `node_outputs`; they do not use global flat keys.

## 6. Default binding priority

| Priority | `origin` | Behavior |
| --- | --- | --- |
| 1 (highest) | `user` | Always use; never auto-overwrite |
| 2 | `default` | Catalog match when edge is drawn |
| 3 | `pass_through` | Whole port `/` → `/` when ports are compatible |
| 4 | — | Missing required binding → **publish error** |

Rules:

- Apply catalog defaults only when **exactly one** unambiguous upstream match exists.
- If two upstream nodes could satisfy the same target field, require explicit `user` binding.
- Optional input ports may remain unbound.

## 7. Validation (publish time)

Both control plane and execution engine re-validate before run. Add binding checks after port/edge validation:

1. Every **required** input port has a binding, inferred pass-through, or valid default.
2. `source_node_id` is an upstream node reachable via edges (same branch context where applicable).
3. `source_path` and `target_path` are valid JSON Pointers.
4. Types are compatible at the mapped paths (source schema satisfies target).
5. No duplicate `(target_port, target_path)` unless node policy allows reducers.
6. `origin: "user"` bindings reference a source connected to the target by an edge on those ports.

Stable error codes:

| Code | Meaning |
| --- | --- |
| `BINDING_MISSING` | Required input port/field has no binding |
| `BINDING_INCOMPATIBLE` | Types or paths do not match |
| `BINDING_AMBIGUOUS` | Multiple upstream candidates; user must choose |
| `BINDING_UNREACHABLE` | Source node not upstream of target |

Example:

```json
{
  "code": "BINDING_INCOMPATIBLE",
  "path": "/nodes/2/input_bindings/0",
  "nodeId": "chat-1",
  "message": "source /text (string) is not compatible with target /messages (array)"
}
```

## 8. Editor UX

### Simple linear flow

1. User drags `Prompt Template` → `Chat Model`.
2. Edge: `text` → `prompt`.
3. Inspector shows bindings; catalog default pre-fills `prompt.text ← text.text` (`origin: default`).
4. User publishes without extra steps.

### Variable form / review output

1. User drags `human.review@1` → `ai.prompt-template@1`.
2. Bindings panel lists target fields; user maps:
   - `variables.name` ← `review.value.name`
   - `variables.email` ← `review.value.email`
3. Saved as `origin: user`.

### Canvas affordances

- Typed handles per catalog port.
- Edge click opens bindings for that link.
- Badge: `auto` vs `manual` per binding.
- Publish-blocking summary groups node, edge, and binding errors.

## 9. Node-specific notes

| Node | Wiring |
| --- | --- |
| `data.input@1` / `data.output@1` | Pass-through on `value` |
| `ai.prompt-template@1` | Bind `variables.*` from upstream; template `{{var}}` renders inside node |
| `ai.chat-model@1` | Default: `prompt.text` ← upstream `text.text` |
| `human.review@1` / `human.approval@1` | Output `value` / `decision` is `object`; bind fields downstream |
| `control.condition@1` | Branch via `true`/`false` **edges**; condition AST in config |
| `control.loop@1` | `body`/`done` **edges**; iteration data via bindings if needed |
| `control.merge@1` | Keep `config.mappings` for MVP; may converge with bindings later |

## 10. Implementation phases

| Phase | Scope |
| --- | --- |
| **MVP** | Edges + inferred pass-through when `input_bindings` omitted |
| **Phase 2** | `input_bindings` in contract; publish fails on missing required bindings |
| **Phase 3** | Catalog `default_bindings`; editor auto-fill |
| **Phase 4** | Field picker UI for forms and partial objects |
| **Phase 5** | Evaluate simplifying `control.merge@1` config vs bindings |

Contract changes (when implemented):

- `contracts/workflow/definition.schema.json` — optional `input_bindings` on `workflowNode`
- `contracts/nodes/manifest.schema.json` — optional `default_bindings` on input ports
- Fixtures: keep existing valid graphs working via pass-through inference; add `workflow-field-bindings` fixture

## 11. Examples

### Linear pass-through (equivalent to `workflow-linear.json`)

Edge only; no `input_bindings`. Compiler infers:

`output.value ← input.value` (pass_through).

### Fan-out with explicit field bind

Edge: `input.value` → `prompt_a.variables`.

Binding on `prompt_a`:

```json
{
  "target_port": "variables",
  "target_path": "/query",
  "source_node_id": "input-1",
  "source_port": "value",
  "source_path": "/query",
  "origin": "default"
}
```

### Chat model default

Edge: `prompt-1.text` → `chat-1.prompt`.

Binding on `chat-1` (catalog default):

```json
{
  "target_port": "prompt",
  "target_path": "/text",
  "source_node_id": "prompt-1",
  "source_port": "text",
  "source_path": "/text",
  "origin": "default"
}
```

## Related

- [02-shared-contracts.md](./02-shared-contracts.md)
- [LLD.md](./LLD.md) §4, §9, §10.3
- [execution-engine/LLD.md](./execution-engine/LLD.md) §6
- [control-plane/LLD.md](./control-plane/LLD.md) §6
- `contracts/workflow/definition.schema.json`
- `contracts/nodes/manifest.schema.json`
