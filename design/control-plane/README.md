# Control Plane — Developer Entry

**Code:** `services/control-plane`  
**Stack:** Java 21, Spring Boot, Flyway, Quartz (clustered JDBC), Spring AMQP, JPA, MinIO SDK

## Purpose

Sole public backend and system of record for product state. Authenticates users, authorizes every operation, stores drafts/versions, encrypts credentials, serves the node catalog, manages triggers, datasets, approvals, and task/artifact read models, creates runs via transactional outbox, projects worker events, streams SSE, and writes audit.

## Boundaries

**Does**

- Public REST `/api/v1`, webhooks `/hooks/v1`, SSE
- Internal `/internal/v1` for workers (service auth; not on the public proxy)
- Platform PostgreSQL schema (Flyway)
- Outbox commands + event inbox/projector
- Signed MinIO **upload** intents and artifact **download** intents

**Does not**

- Execute workflows or call AI providers for workflow nodes
- Publish `task.start` (execution-worker does)
- Send `execution.resume` for `TASK` waits
- Write `ee.*` checkpoint or `rag.*` vector schemas
- Put secrets in browser responses, queue payloads, or logs

## Docs in this folder

| Doc | Contents |
| --- | --- |
| [LLD.md](./LLD.md) | Packages, services, controllers, data model, scale-out, join contract |
| [FEATURES.md](./FEATURES.md) | What to build, acceptance criteria |
| [BUILD-GUIDE.md](./BUILD-GUIDE.md) | Ordered implementation steps |

## Related cross-cutting docs

- [Service interactions](../01-service-interactions.md)
- [Contracts](../02-shared-contracts.md)
- [Messaging](../03-messaging.md)
- [Data ownership](../04-data-ownership.md)
- Public API tables: [../LLD.md](../LLD.md) §6.3–6.4

## Package layout

```text
com.example.aiworkflow/
|-- auth/ project/ workflow/ credential/ dataset/
|-- trigger/ execution/ approval/ task/ artifact/
|-- messaging/ security/ common/
`-- catalog/   # NodeCatalogService from contracts/nodes/catalog
```

Each feature: `api/` → `application/` → `domain/` + `persistence/`.
