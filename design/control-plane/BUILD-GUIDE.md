# Control Plane — Build Guide

Ordered vertical slices for `services/control-plane`. Write failing tests first; keep units hermetic; use Testcontainers for integration. Target ≥80% coverage on changed code.

**Prereqs:** Java 21, Maven Wrapper, Docker, access to repo-root `contracts/`.

Working directory: `services/control-plane`.

---

## Step 0 — Scaffold

1. Spring Boot app with Web, Security, Validation, JPA, PostgreSQL, Flyway, Quartz (clustered JDBC), AMQP, Actuator, Testcontainers.
2. Package skeleton from [LLD.md](./LLD.md).
3. `./mvnw -q verify` passes empty context test.

## Step 1 — Common foundations

- Problem responses (`code`, `correlationId`)
- Injected `Clock`
- Cursor pagination helpers

## Step 2 — Flyway identity/tenancy

Tables: `users`, `workspaces`, `workspace_memberships`, `projects`, `refresh_tokens` + indexes.

## Step 3 — Auth

Argon2id, JWT access, rotating refresh cookie, register/login/refresh/logout/`me`, rate limits.

**Done:** session rotation + replay family revoke covered by tests.

## Step 4 — Projects + authz pattern

Establish service-layer ownership checks reused everywhere (MVP membership, not advanced roles).

## Step 5 — Contracts + catalog

Bind JSON Schema + shared fixtures (same accept/reject as Python); `NodeCatalogService` from `contracts/nodes/catalog`.

## Step 6 — Drafts

`workflows` / `workflow_drafts`; optimistic concurrency; `409` on stale revision.

## Step 7 — Validate + publish

Full pipeline (ports, edges, input bindings, conditions, Tarjan loops, reachability, refs); immutable `workflow_versions`.

## Step 8 — Credentials

AES-GCM storage, masked list, delete-if-unreferenced; prepare internal resolve against the **run snapshot** (wire service auth in Step 16).

## Step 9 — Outbox + inbox messaging

`outbox_messages`, `consumed_messages`; publisher confirms; envelope validation; topology from [../03-messaging.md](../03-messaging.md). Control plane does **not** publish `task.start`.

## Step 10 — Execution lifecycle

Create run + outbox atomically (`mode=draft|published`); unique `idempotency_key`; projector for lifecycle/node/task/ingestion events; cancel command; legal state machine including `TIMED_OUT`.

## Step 11 — SSE

Authorized stream, replay from `execution_events`, heartbeats, terminal close.

## Step 12 — Triggers

Webhook + Quartz schedule + production-manual rows pinned to a **published** version; webhook opacity on bad secret. Draft test runs stay on Step 10.

## Step 13 — Datasets / MinIO

Signed upload intent, confirm → `document.ingest` to **rag-worker**, delete command, internal download-intent (service auth).

## Step 14 — Approvals

Pending from `execution.waiting` with `waiting_reason=HUMAN` only; decision → `execution.resume` outbox. Never resume TASK waits.

## Step 15 — Tasks / artifacts read model

Project `task.*` events; user cancel → `task.cancel` + parent `execution.cancel`; signed **downloads** only.

## Step 16 — Hardening

Service auth on all `/internal/**`; audit events; metrics; retention jobs; non-root image; README runbook.

---

## Verification commands (typical)

```powershell
./mvnw -q test
./mvnw -q verify   # includes Testcontainers if configured
```

## Definition of done for a slice

- [ ] Behavior tests green (unit ± integration)
- [ ] Contract fixtures still pass
- [ ] No secrets in logs/responses
- [ ] Flyway migration (if any) applies cleanly
- [ ] Feature marked done in [FEATURES.md](./FEATURES.md)

## Pointers

- API shapes: [../LLD.md](../LLD.md) §6.3–6.4
- Join contract and scale-out: [LLD.md](./LLD.md) §15–§16
- Start payload schema: `contracts/messages/commands/execution.start.schema.json`
