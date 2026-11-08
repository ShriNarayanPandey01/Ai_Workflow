# Control Plane — Agent Guide

Spring Boot 3 / Java 21 control plane service providing identity, project management, node catalog, workflow authoring (drafts/versions), clustered scheduling, run management, and transactional event/command routing.

---

## 1. Authoritative Documentation Map (Reference Method)

Before modifying code in this service, refer to the authoritative documents below:

| Document | Path | Purpose & When to Read |
|---|---|---|
| **Control Plane LLD** | [design/control-plane/LLD.md](../../design/control-plane/LLD.md) | **Primary technical blueprint**: REST endpoints (`/api/v1/**`), Flyway DDL (`public.*`), Quartz clustered scheduler, Transactional Outbox, SSE projector. Read before touching controllers, entities, or DB migrations. |
| **Control Plane Features** | [design/control-plane/FEATURES.md](../../design/control-plane/FEATURES.md) | **Acceptance criteria (F1–F16)**: Acceptance tests, edge cases, RBAC rules, draft versioning policies, and lifecycle state machines. |
| **Java Standards & Rules** | [.agents/rules/java-production.md](../../.agents/rules/java-production.md) | **Production coding standards**: Java 21 features, DTO record rules, `@Transactional` boundaries, exception handling (`ProblemDetail`), and repository patterns. |
| **System High-Level Design** | [design/HLD.md](../../design/HLD.md) | **System topology**: Cross-service interaction flows, RabbitMQ broker topology, schema ownership, and security model. |
| **Shared Contracts** | [contracts/README.md](../../contracts/README.md) | **Canonical JSON schemas**: Single source of truth for workflow definitions, node manifests, broker commands, and events. |
| **Local Run Guide** | [README.md](./README.md) | Local environment startup, Maven commands, and Postman collections. |

---

## 2. Core Architectural Invariants & Boundaries

1. **Sole Public Entrypoint**: The control plane is the **only** service exposed to browsers (`/api/v1/**`, `/hooks/v1/**`). All other services (execution-engine, rag, databases, RabbitMQ) are strictly private.
2. **Schema Ownership (`public.*`)**: This service owns the `public.*` PostgreSQL schema via Flyway migrations. Never query or write to `ee.*` or `rag.*`.
3. **Transactional Outbox / Inbox**: Commands dispatched to the execution plane (`aiw.commands.v1`) must be written to the `outbox_messages` table within the same database transaction. Events from the execution plane (`aiw.events.v1`) are deduplicated via the `inbox_messages` table.
4. **Casing Boundary**:
   - HTTP API request/response DTOs: `camelCase` (e.g. `workflowId`, `projectId`).
   - Stored graph definitions and broker message payloads: `snake_case` (e.g. `workflow_id`, `project_id`) adhering strictly to `contracts/`.
5. **Secrets by Reference**: Workflow drafts and execution requests store credential references/IDs, never plaintext secrets. Resolving credentials occurs securely via `CredentialService`.

---

## 3. Package Structure (Vertical Slice Architecture)

Code is organized by business feature under `com.example.aiworkflow`:

```text
src/main/java/com/example/aiworkflow/
├── catalog/       # Node manifest catalog loader & validation
├── common/        # ProblemDetail, IDs, pagination, time clock
├── config/        # AiwProperties and application configuration
├── credential/    # Encrypted credential storage & resolution
├── dataset/       # Dataset metadata and MinIO presigned uploads
├── execution/     # Run management, execution triggers, SSE run streaming
├── messaging/     # Outbox publisher, RabbitMQ topology, Inbox deduplication
├── project/       # Workspace, projects, membership, RBAC
├── security/      # JWT filter, access tokens, service auth tokens
├── storage/       # S3/MinIO presigned URL generator & object store
├── task/          # Long-running task tracking and status projections
├── trigger/       # Webhooks, schedules (Quartz clustered), manual triggers
└── workflow/      # Workflow definitions, versioning, drafts, graph validation
```

Within each feature package:
- `api/`: REST Controllers and request/response DTOs (Java records).
- `application/`: Service use cases and `@Transactional` boundaries.
- `domain/`: JPA Entities, value objects, domain policies, and domain exceptions.
- `persistence/`: Spring Data JPA repositories.

---

## 4. Development & Verification Commands

Run from `services/control-plane`:

```powershell
# Set contracts path and run locally
$env:AIW_CONTRACTS_ROOT = (Resolve-Path ..\..\contracts).Path
./mvnw spring-boot:run

# Run unit tests
./mvnw test

# Run integration tests (requires Docker or local PostgreSQL)
./mvnw verify -DskipUnitTests=false
```
