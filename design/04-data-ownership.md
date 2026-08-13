# Data Ownership

Each service writes only its owned schema/objects. Cross-service reads go through APIs or projected events—not foreign table writes.

## PostgreSQL schemas

| Schema / area | Owner | Contents |
| --- | --- | --- |
| Platform (Spring / Flyway) | control-plane | users, workspaces, projects, drafts, versions, credentials, triggers, datasets/documents metadata, executions, node_executions, execution_events, approvals, task_jobs/items (read model), artifacts metadata, outbox, consumed_messages, audit, Quartz tables |
| Checkpoints | execution-engine (walker) | `ee.workflow_checkpoints`, pending interrupts |
| Vectors | rag service | `rag.rag_document_versions`, `rag.rag_chunks` (+ embeddings); execution-engine reads only |
| Worker inbox/outbox helpers | execution-engine | Worker-local idempotency / event outbox if used |

Use separate DB users and grants per service.

## Platform tables (control plane) — quick map

| Domain | Tables |
| --- | --- |
| Identity | `users`, `refresh_tokens` |
| Tenancy | `workspaces`, `workspace_memberships`, `projects` |
| Workflow | `workflows`, `workflow_drafts`, `workflow_versions` |
| Secrets | `credentials` |
| Triggers | `triggers` (+ Quartz JDBC) |
| Datasets | `datasets`, `documents` |
| Runs | `executions`, `node_executions`, `execution_events`, `approval_requests` |
| Tasks (read model) | `task_jobs`, `task_items`, `artifacts` |
| Messaging | `outbox_messages`, `consumed_messages` |
| Audit | `audit_events` |

All project resources carry workspace + project ownership columns. Indexes must support ownership checks, listing, trigger lookup, event replay, pending approvals, recent runs.

## Execution states

Legal run statuses: `QUEUED`, `RUNNING`, `WAITING`, `SUCCEEDED`, `FAILED`, `CANCELLING`, `CANCELLED`, `TIMED_OUT`.

- Terminal states never return to active.
- `WAITING` includes `waiting_reason = HUMAN | TASK`.
- Resume is legal only for matching unresolved interrupt.

Task jobs use their own: `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLING`, `CANCELLED`, `TIMED_OUT`.

## MinIO

| Content | Keying | Who writes | Who authorizes |
| --- | --- | --- | --- |
| Source documents | workspace/project scoped keys (server-generated) | Client via signed upload; workers read via intent | control-plane |
| Generated artifacts | project-scoped keys | task/execution workers | control-plane download API |

Never trust user-supplied paths. Validate MIME, size, and hash.

## Consistency model

- Identity, drafts, publish, run creation: local ACID in Spring.
- Commands: eventually published via outbox.
- Run status in UI: eventually consistent via event projection.
- Event order: per-run monotonic sequence.
- SSE reconnect: replay from `Last-Event-ID` / sequence.

## Retention (configurable)

| Data | Guidance |
| --- | --- |
| Refresh tokens | Expiry/revocation + short audit window |
| Execution events | Operational/audit window |
| Checkpoints | Active + post-terminal recovery window |
| Node I/O | Size limits + redaction |
| Documents/vectors | Until delete completes |
| Audit | Longer than operational logs |

## Rules for migrations

- Spring owns Flyway for platform schema; forward-only in normal deploys.
- Python owns checkpoint/vector migrations in its schemas.
- Never share mutable tables across languages.
- Adding a column that another service must read → prefer events/API, not cross-schema joins for writes.
