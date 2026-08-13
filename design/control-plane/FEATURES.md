# Control Plane — Features

Checklist for developers. Each feature lists scope, key types/endpoints, and done criteria. Skip UI work; APIs and projections only.

## F1 — Identity and sessions

| | |
| --- | --- |
| **Includes** | Register, login, refresh rotation, logout, `/me`, personal workspace |
| **Key APIs** | `POST /api/v1/auth/register\|login\|refresh\|logout`, `GET /api/v1/auth/me` |
| **Done when** | Argon2id hashes; refresh cookie rotates; reuse revokes family; auth errors do not reveal account existence; rate limits on auth endpoints |

## F2 — Projects and authorization

| | |
| --- | --- |
| **Includes** | Project CRUD; membership checks on every resource (MVP owner/member; no advanced RBAC) |
| **Key APIs** | `/api/v1/projects` |
| **Done when** | Cross-workspace/project access returns `403`/`404`; client IDs alone never authorize |

## F3 — Node catalog

| | |
| --- | --- |
| **Includes** | Serve manifests from `contracts/nodes/catalog` (ports, schemas, optional `default_bindings`) |
| **Key APIs** | `GET /api/v1/node-catalog` |
| **Done when** | Catalog matches contracts; shared fixtures pass in Java; no hardcoded drift |

## F4 — Workflow drafts

| | |
| --- | --- |
| **Includes** | Create workflow + draft; get/put draft with `baseRevision` |
| **Key APIs** | `/api/v1/projects/{projectId}/workflows/{workflowId}/draft` |
| **Done when** | Optimistic concurrency; stale revision → `409`; camelCase HTTP mapped to snake_case storage |

## F5 — Validation and publication

| | |
| --- | --- |
| **Includes** | Authoritative graph validation (ports, edges, input bindings); immutable versions |
| **Key APIs** | `POST .../validate`, `POST .../publish`, version list/get |
| **Done when** | Arbitrary cycles and unbounded loops rejected; required input bindings validated (or pass-through inferred); publish atomic; draft edits never mutate published versions |

## F6 — Credentials

| | |
| --- | --- |
| **Includes** | Encrypt/store/list/update/delete; masked responses; internal resolve |
| **Key APIs** | `/api/v1/projects/{projectId}/credentials`, `POST /internal/v1/executions/{runId}/credentials:resolve` |
| **Done when** | AES-GCM + key_id + AAD; plaintext never in list/API logs; resolve checks the **run snapshot** (draft or published); `workflowVersionId` may be null; service auth required internally |

## F7 — Messaging backbone

| | |
| --- | --- |
| **Includes** | Outbox table + publisher; event consumer + inbox; envelope validation |
| **Done when** | Run+outbox atomic; SKIP LOCKED publisher; duplicate events no-op; DLQ path for poison messages; commands `sequence: null`; `causation_id` set when a parent message exists |

## F8 — Execution lifecycle

| | |
| --- | --- |
| **Includes** | Start draft/published run; list/detail; cancel; state machine |
| **Key APIs** | `POST /api/v1/projects/{projectId}/workflows/{workflowId}/executions`, run get/list/cancel |
| **Done when** | Legal transitions only (`QUEUED`, `RUNNING`, `WAITING`, `SUCCEEDED`, `FAILED`, `CANCELLING`, `CANCELLED`, `TIMED_OUT`); cancel → `CANCELLING` + outbox `execution.cancel`; unique `idempotency_key` per accepted run; redacted I/O in read model; `202` with `runId` |

## F9 — SSE run stream

| | |
| --- | --- |
| **Includes** | Authenticated SSE with replay |
| **Key APIs** | `GET /api/v1/projects/{projectId}/executions/{runId}/events` |
| **Done when** | `Last-Event-ID` replay from `execution_events`; sequence ordering; heartbeats; close on terminal |

## F10 — Triggers

| | |
| --- | --- |
| **Includes** | Webhook, schedule, and production-manual **trigger rows** pinned to a published version. Draft test runs are F8 (`mode=draft`), not a trigger pin. |
| **Key APIs** | `/api/v1/projects/{projectId}/workflows/{workflowId}/triggers`; `POST /hooks/v1/{publicId}/{secret}` |
| **Done when** | Clustered Quartz JDBC survives restart without double-fire; webhook secret hashed; schedule dispatches one idempotent run command |

## F11 — Approvals

| | |
| --- | --- |
| **Includes** | Persist pending from `execution.waiting` with `waiting_reason=HUMAN` only; decision → resume command |
| **Key APIs** | `GET /api/v1/approvals`, `POST /api/v1/projects/{projectId}/executions/{runId}/approvals/{approvalId}/decision` |
| **Done when** | Authorize per run; atomic resolve; resume only for HUMAN wait; never `execution.resume` for TASK; audit recorded |

## F12 — Datasets and documents

| | |
| --- | --- |
| **Includes** | Dataset CRUD; signed upload; confirm → ingest outbox to **rag-worker**; delete queue |
| **Key APIs** | Dataset/document endpoints; `POST /internal/v1/documents/{documentId}/download-intent` |
| **Done when** | MIME/size validation; server-generated keys; status projected from `document.ingestion.*`; ingest/delete not routed to execution-worker |

## F13 — Tasks and artifacts (read model)

| | |
| --- | --- |
| **Includes** | Project task progress/items; cancel; signed artifact **download** (workers write objects) |
| **Key APIs** | `/api/v1/projects/{projectId}/tasks`, `/api/v1/projects/{projectId}/artifacts/{id}/download` |
| **Done when** | Events update progress/budgets; user cancel task → `task.cancel` **and** parent `execution.cancel`; never publish `task.start`; download short-lived and project-scoped |

## F14 — Audit and observability

| | |
| --- | --- |
| **Includes** | Audit for auth/publish/credential/trigger/run/approval; structured logs; metrics; readiness |
| **Done when** | Correlation IDs on responses; no secrets in logs; readiness checks DB + broker |

## Non-features (control plane)

- Running workflow graphs or embedding pipelines
- Calling OpenAI/market/research providers for node execution
- Publishing `task.start` or `execution.resume` for TASK waits
- Writing `ee.*` / `rag.*` tables
- Browser-facing Python proxies
