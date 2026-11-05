# Web Frontend — Agent Guide

React 19 + TypeScript + Vite workbench application for the AI Workflow Platform. Provides the visual workflow graph builder, execution run monitor, approval inbox, dataset manager, and credential configuration UI.

---

## 1. Authoritative Documentation Map (Reference Method)

Before modifying code in this frontend application, refer to the authoritative documents below:

| Document | Path | Purpose & When to Read |
|---|---|---|
| **System High-Level Design** | [design/HLD.md](../../design/HLD.md) | **System topology & user flows**: Service interactions, SSE run streaming, security boundaries, and overall platform concepts. |
| **Control Plane LLD (APIs)** | [design/control-plane/LLD.md](../../design/control-plane/LLD.md) | **Backend REST API contracts**: Endpoints (`/api/v1/**`), request/response JSON payload formats, query parameters, and pagination specs. |
| **Shared Contracts** | [contracts/README.md](../../contracts/README.md) | **Canonical JSON schemas**: Workflow definition schema, node manifest schemas, and catalog metadata. |
| **Workflow Definition Schema** | [contracts/workflow/definition.schema.json](../../contracts/workflow/definition.schema.json) | **Graph data structure**: The exact schema required for nodes, edges, ports, configs, and condition ASTs. |
| **Node Catalog Manifests** | [contracts/nodes/catalog/](../../contracts/nodes/catalog/) | **Authoritative node definitions**: Input/output port definitions, property schemas, and display metadata for all node types. |
| **Local Run Guide** | [README.md](./README.md) | Vite development server commands, dev proxy configuration, and test scripts. |

---

## 2. Core Architectural Invariants & Boundaries

1. **Exclusive Backend Access**:
   - The web app talks **only** to the Control Plane at `/api/v1` (and SSE streams at `/api/v1/projects/{projectId}/runs/{runId}/events`).
   - Never attempts to communicate directly with Python execution services, the RAG service, RabbitMQ, or databases.
2. **Development Proxy**:
   - In development, Vite proxies `/api` requests to `http://localhost:8080` (Spring Boot Control Plane).
3. **Casing Conventions**:
   - Control Plane HTTP APIs consume and return `camelCase` DTOs.
   - Node configurations and graph definition payloads sent for storage/publishing adhere to the canonical schema (`snake_case` where mandated by `definition.schema.json`).
4. **State Management**:
   - **Server State / Caching**: Managed with `@tanstack/react-query`.
   - **Interactive Graph State**: Managed with Zustand stores and `@xyflow/react` (React Flow).
5. **Component System & Styling**:
   - Uses Tailwind CSS v4 and Radix UI headless primitives.
   - Styling tokens are defined in `src/styles/tokens.css` and `src/index.css`. Follow cohesive design rules; avoid introducing unstyled generic UI.

---

## 3. Directory Layout

```text
apps/web/src/
├── api/           # API client, HTTP fetchers, TanStack Query hooks, generated types
├── app/           # App root, React Router routes, layout providers
├── components/    # Reusable UI primitives (dialogs, dropdowns, inputs, buttons, shell)
├── features/      # Feature-specific pages and business logic
│   ├── approvals/   # Human-in-the-loop review and approval UI
│   ├── auth/        # Login and session handling
│   ├── builder/     # React Flow graph canvas, node palette, inspector panels
│   ├── credentials/ # Credential registration and secret management
│   ├── datasets/    # Dataset upload and document management
│   ├── projects/    # Project list, settings, and workspace navigation
│   ├── runs/        # Run history, step timelines, SSE event log viewer
│   ├── tasks/       # Heavy task tracking viewer
│   ├── triggers/    # Webhook and scheduled trigger configuration
│   └── workflows/   # Workflow listing, versions, drafts, and export
├── lib/           # Utility functions (cn, formatters, validation)
└── styles/        # Global design tokens and CSS configurations
```

---

## 4. Development & Verification Commands

Run from `apps/web`:

```bash
# Install dependencies
npm install

# Start Vite dev server (proxies /api to http://localhost:8080)
npm run dev

# Type check
npm run lint

# Run unit and component tests
npm test

# Build production bundle
npm run build
```
